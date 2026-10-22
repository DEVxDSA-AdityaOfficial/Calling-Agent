"""Custom Brain: Retell's custom-LLM WebSocket.

Retell handles telephony, speech recognition, turn-taking and voice; for every turn it sends the
transcript here and speaks whatever our ConversationModel streams back.
Protocol: https://docs.retellai.com/api-references/llm-websocket
"""

import asyncio
import contextlib
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from ..call_sync import set_live_transcript
from ..conversation.base import ConversationModel, ConversationModelError
from ..conversation.brain import EndCallFilter, build_messages, render_variables
from ..conversation.factory import get_conversation_model
from ..db import SessionLocal
from ..models import Agent, Call, User

log = logging.getLogger(__name__)
router = APIRouter()

FALLBACK_REPLY = "Sorry, I'm having a little trouble on my side. Could you say that again?"


async def _find_call(retell_call_id: str, agent: Agent, attempts: int = 10) -> Call | None:
    """The call row is linked to its Retell id right after create-phone-call returns; wait briefly for it."""
    for _ in range(attempts):
        with SessionLocal() as db:
            call = db.scalar(select(Call).where(Call.retell_call_id == retell_call_id, Call.agent_id == agent.id))
            if call:
                return call
        await asyncio.sleep(0.5)
    return None


class _Session:
    def __init__(self, ws: WebSocket, agent: Agent, call_id: int, model: ConversationModel):
        self.ws = ws
        self.agent = agent
        self.call_id = call_id
        self.model = model
        self.variables: dict[str, str] = {}
        self.latest_response_id = 0
        self.task: asyncio.Task | None = None
        self.send_lock = asyncio.Lock()

    async def send(self, payload: dict) -> None:
        async with self.send_lock:
            await self.ws.send_text(json.dumps(payload))

    async def respond(self, response_id: int, transcript: list[dict], reminder: bool) -> None:
        messages = build_messages(self.agent.generated_prompt, transcript, self.variables, reminder=reminder)
        end_filter = EndCallFilter()
        try:
            async for chunk in self.model.stream(messages):
                if response_id != self.latest_response_id:
                    return  # Retell moved on (the customer spoke again); stop paying for unheard tokens
                text = end_filter.feed(chunk)
                if text:
                    await self.send({"response_type": "response", "response_id": response_id, "content": text, "content_complete": False})
                if end_filter.ended:
                    break
            tail = end_filter.flush()
            await self.send(
                {
                    "response_type": "response",
                    "response_id": response_id,
                    "content": tail,
                    "content_complete": True,
                    "end_call": end_filter.ended,
                }
            )
        except ConversationModelError as exc:
            log.error("Conversation model failed on call %s: %s", self.call_id, exc)
            await self.send({"response_type": "response", "response_id": response_id, "content": FALLBACK_REPLY, "content_complete": True})

    def store_transcript(self, transcript: list[dict]) -> None:
        with SessionLocal() as db:
            call = db.get(Call, self.call_id)
            if call:
                set_live_transcript(call, transcript)
                db.commit()


@router.websocket("/api/llm-ws/{ws_token}/{retell_call_id}")
async def llm_websocket(websocket: WebSocket, ws_token: str, retell_call_id: str):
    with SessionLocal() as db:
        agent = db.scalar(select(Agent).where(Agent.ws_token == ws_token))
        user = db.get(User, agent.user_id) if agent else None
        model = None
        if agent and user and agent.mode == "custom_brain":
            try:
                model = get_conversation_model(db, user)
            except ConversationModelError as exc:
                log.error("No conversation model for agent %s: %s", agent.id, exc)
    if not agent or agent.mode != "custom_brain" or model is None:
        await websocket.close(code=1008)
        return
    await websocket.accept()

    call = await _find_call(retell_call_id, agent)
    if call is None:
        log.warning("Rejecting LLM websocket for unknown call %s", retell_call_id)
        await websocket.close(code=1008)
        return

    session = _Session(websocket, agent, call.id, model)
    await session.send({"response_type": "config", "config": {"auto_reconnect": True, "call_details": True}})
    log.info("Custom Brain connected for call %s (%s)", call.id, model.name)

    try:
        while True:
            request = json.loads(await websocket.receive_text())
            kind = request.get("interaction_type")
            if kind == "ping_pong":
                await session.send({"response_type": "ping_pong", "timestamp": int(time.time() * 1000)})
            elif kind == "call_details":
                session.variables = (request.get("call") or {}).get("retell_llm_dynamic_variables") or {}
                # Begin message (response_id 0). Without a fixed opening, the model writes it.
                if agent.begin_message:
                    await session.send(
                        {
                            "response_type": "response",
                            "response_id": 0,
                            "content": render_variables(agent.begin_message, session.variables),
                            "content_complete": True,
                        }
                    )
                else:
                    session.latest_response_id = 0
                    session.task = asyncio.create_task(session.respond(0, [], reminder=False))
            elif kind == "update_only":
                await asyncio.to_thread(session.store_transcript, request.get("transcript") or [])
            elif kind in ("response_required", "reminder_required"):
                transcript = request.get("transcript") or []
                session.latest_response_id = request["response_id"]
                if session.task and not session.task.done():
                    session.task.cancel()
                session.task = asyncio.create_task(
                    session.respond(request["response_id"], transcript, reminder=kind == "reminder_required")
                )
                await asyncio.to_thread(session.store_transcript, transcript)
    except WebSocketDisconnect:
        log.info("Custom Brain disconnected for call %s", call.id)
    finally:
        if session.task and not session.task.done():
            session.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await session.task
