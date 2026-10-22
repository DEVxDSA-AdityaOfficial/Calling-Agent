"""Twilio side of “Twilio + Custom Brain” calls: Media Stream WebSocket + call status callbacks."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from ..call_sync import TERMINAL_STATUSES, apply_retell_call, finish_direct_call
from ..config import get_settings
from ..conversation.analysis import analyze_transcript
from ..conversation.base import ConversationModelError
from ..conversation.factory import get_conversation_model
from ..db import SessionLocal
from ..models import Agent, Call, User, utcnow
from ..providers import credential_values, get_credential
from ..routers.agents import spec_for
from ..speech.audio import TelephonyFormatError
from ..speech.base import STTError
from ..speech.router import resolve_fallback, resolve_speech
from ..speech.tts import ElevenLabsTTS
from ..telephony.twilio import REASON_MAP, STATUS_MAP, TwilioClient, TwilioError, validate_signature
from ..voice.pipeline import Diagnostics, VoicePipeline

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/twilio", tags=["twilio"])

_ANALYSES: set[int] = set()  # calls with an analysis in flight (per process)


def twilio_for(db, user: User) -> tuple[TwilioClient, dict]:
    values = credential_values(get_credential(db, user, "twilio"))
    return TwilioClient(values.get("account_sid", ""), values.get("auth_token", "")), values


def _tts_language(agent_language: str) -> str | None:
    return {"hinglish": "hi", "hi-IN": "hi"}.get(agent_language) or (agent_language.split("-")[0] if agent_language else None)


async def run_analysis(call_id: int) -> None:
    """Post-call analysis for direct calls (Retell analyses its own calls)."""
    if call_id in _ANALYSES:
        return
    _ANALYSES.add(call_id)
    try:
        with SessionLocal() as db:
            call = db.get(Call, call_id)
            if call is None or call.analysis_raw is not None or not call.transcript_object:
                return
            agent, user = db.get(Agent, call.agent_id), db.get(User, call.user_id)
            try:
                model = get_conversation_model(db, user)
                analysis = await analyze_transcript(model, spec_for(agent), call.transcript_object)
            except ConversationModelError as exc:
                log.warning("Analysis failed for call %s: %s", call_id, exc)
                return
            apply_retell_call(call, {"call_analysis": analysis})
            db.commit()
    finally:
        _ANALYSES.discard(call_id)


@router.post("/status/{token}", status_code=204)
async def status_callback(token: str, request: Request, background: BackgroundTasks):
    form = dict((await request.form()).items())
    settings = get_settings()
    with SessionLocal() as db:
        call = db.scalar(select(Call).where(Call.media_token == token))
        if call is None:
            return Response(status_code=204)
        user = db.get(User, call.user_id)
        values = credential_values(get_credential(db, user, "twilio"))
        # Validate against the public URL Twilio called (proxies may rewrite the Host header).
        url = f"{settings.public_base_url}{request.url.path}"
        if not validate_signature(url, {k: str(v) for k, v in form.items()}, request.headers.get("x-twilio-signature"), values.get("auth_token", "")):
            raise HTTPException(403, "Invalid Twilio signature")
        status = STATUS_MAP.get(form.get("CallStatus", ""))
        if status and not (call.status in TERMINAL_STATUSES and status not in TERMINAL_STATUSES):
            call.status = status
        if form.get("CallStatus") in REASON_MAP:
            call.disconnection_reason = REASON_MAP[form["CallStatus"]]
        if form.get("CallStatus") == "completed" and not call.disconnection_reason:
            call.disconnection_reason = "call_completed"
        if form.get("CallDuration"):
            call.duration_ms = int(form["CallDuration"]) * 1000
        if status in TERMINAL_STATUSES:
            call.ended_at = call.ended_at or utcnow()
            finish_direct_call(call)  # derive outcome / goal_status from status + reason
        db.commit()
        if status == "completed" and call.transcript_object and call.analysis_raw is None:
            background.add_task(run_analysis, call.id)
    return Response(status_code=204)


@router.websocket("/media/{token}")
async def media_stream(websocket: WebSocket, token: str):
    with SessionLocal() as db:
        call = db.scalar(select(Call).where(Call.media_token == token, Call.mode == "direct"))
        if call is None or call.status in TERMINAL_STATUSES:
            await websocket.close(code=1008)
            return
        call_id = call.id
        agent, user = db.get(Agent, call.agent_id), db.get(User, call.user_id)
        try:
            # Pinned to the provider chosen when the call was placed: never switch mid-call.
            speech = resolve_speech(db, user, agent, provider_id=call.stt_provider)
            fallback = resolve_fallback(db, user, agent, call.stt_provider)
            model = get_conversation_model(db, user)
            el_key = credential_values(get_credential(db, user, "elevenlabs")).get("api_key")
            twilio, _ = twilio_for(db, user)
        except (STTError, ConversationModelError, TwilioError) as exc:
            log.error("Can't run direct call %s: %s", call_id, exc)
            await websocket.close(code=1011)
            return
        prompt, begin, sid = agent.generated_prompt, agent.begin_message, call.twilio_call_sid
        variables = {"customer_name": call.customer_name} if call.customer_name else {}
        if call.customer_name:
            variables["greeting"] = f"Hi, is this {call.customer_name}?"
        max_s = max(agent.max_duration_minutes, 1) * 60 + 60
        tts = ElevenLabsTTS(el_key or "", agent.voice_id, language=_tts_language(agent.language))
        # Report why this provider was chosen when the call was placed (agent / default), not "pinned".
        original_source = ((call.diagnostics or {}).get("stt") or {}).get("source", speech.source)
        diag = Diagnostics(stt_provider=speech.provider.id, stt_model=speech.config.model, stt_source=original_source)

    await websocket.accept()
    send_lock = asyncio.Lock()

    async def send(msg: dict) -> None:
        async with send_lock:
            await websocket.send_text(json.dumps(msg))

    async def hangup() -> None:
        if sid:
            await asyncio.to_thread(twilio.hangup, sid)

    async def persist(transcript: list[dict]) -> None:
        def _save():
            with SessionLocal() as db2:
                c = db2.get(Call, call_id)
                if c:
                    c.transcript_object = [dict(t) for t in transcript]
                    c.transcript = "\n".join(f"{t['role']}: {t['content']}" for t in transcript)
                    c.diagnostics = {**(c.diagnostics or {}), **diag.as_dict()}
                    db2.commit()

        await asyncio.to_thread(_save)

    pipeline = VoicePipeline(
        prompt=prompt, begin_message=begin, variables=variables, model=model, tts=tts,
        send=send, hangup=hangup, persist=persist, max_duration_s=max_s, diagnostics=diag,
    )

    async def open_stt():
        """Open the pinned provider; use the fallback only if the user enabled it and audio hasn't started."""
        stream = speech.provider.open_stream(speech.api_key, speech.config, pipeline.on_transcript)
        try:
            await stream.start()
            return stream
        except STTError as exc:
            diag.errors.append(str(exc))
            if fallback is None:
                raise
            diag.fallback_events.append({"from": speech.provider.id, "to": fallback.provider.id, "reason": exc.code, "at": utcnow().isoformat()})
            log.warning("STT %s failed to start (%s); falling back to %s", speech.provider.id, exc.code, fallback.provider.id)
            stream = fallback.provider.open_stream(fallback.api_key, fallback.config, pipeline.on_transcript)
            await stream.start()
            diag.stt_provider, diag.stt_model, diag.stt_source = fallback.provider.id, fallback.config.model, "fallback"
            return stream

    try:
        while True:
            msg = json.loads(await websocket.receive_text())
            event = msg.get("event")
            if event == "start":
                try:
                    stt = await open_stt()
                except STTError as exc:
                    log.error("STT unavailable for call %s: %s", call_id, exc)
                    await hangup()
                    break
                try:
                    await pipeline.start(msg, stt)
                except TelephonyFormatError as exc:
                    log.error("Call %s: %s", call_id, exc)
                    await stt.close()
                    break
                with SessionLocal() as db:
                    c = db.get(Call, call_id)
                    c.status, c.started_at = "in_progress", c.started_at or utcnow()
                    c.stt_provider = diag.stt_provider
                    c.diagnostics = {**(c.diagnostics or {}), **diag.as_dict()}
                    db.commit()
            elif event == "media":
                if (msg.get("media") or {}).get("track", "inbound") == "inbound":
                    pipeline.on_media((msg.get("media") or {}).get("payload", ""))
            elif event == "mark":
                await pipeline.on_mark((msg.get("mark") or {}).get("name", ""))
            elif event == "stop":
                break
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("Media stream for call %s failed", call_id)
    finally:
        await pipeline.close()
        with SessionLocal() as db:
            c = db.get(Call, call_id)
            ready = c and c.status == "completed" and c.analysis_raw is None and c.transcript_object
        if ready:
            asyncio.create_task(run_analysis(call_id))
        log.info("Media stream closed for call %s (%s)", call_id, diag.as_dict())
