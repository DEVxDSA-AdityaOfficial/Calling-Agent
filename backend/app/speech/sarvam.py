"""Sarvam AI speech-to-text.

REST:      POST {SARVAM_BASE_URL}/speech-to-text            (multipart; ≤30 s; header api-subscription-key)
Streaming: WSS  {SARVAM_WS_URL}?language_code=…&model=…     (header Api-Subscription-Key)
Docs: https://docs.sarvam.ai/api-reference/speech-to-text/transcribe
      https://docs.sarvam.ai/api-reference/speech-to-text/transcribe/realtime/ws

The two APIs differ: language codes (`auto` vs `unknown`, `or-IN` vs `od-IN`), model ids
(`saaras:v3-realtime` is streaming-only, `saaras:v3` REST-only) and payloads, so each has its own mapping.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import time
from urllib.parse import urlencode

import httpx
import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus

from ..config import get_settings
from .base import (
    EventHandler,
    LanguageInfo,
    ModelInfo,
    SpeechConfig,
    STTAuthError,
    STTBadResponseError,
    STTConfigError,
    STTConnectionError,
    STTError,
    STTRateLimitError,
    STTTimeoutError,
    TranscriptEvent,
    TranscriptionResult,
    sanitize,
)

log = logging.getLogger(__name__)

MODELS = [
    ModelInfo("saaras:v4", "Saaras v4 (recommended)", streaming=True, batch=True,
              note="Latest. Indian + Global English, 22 Indic languages, code-mixed speech."),
    ModelInfo("saaras:v3-realtime", "Saaras v3 realtime", streaming=True, batch=False,
              note="Streaming-only model; file tests use saaras:v3."),
]
MODES = ["transcribe", "codemix", "translit", "verbatim", "translate"]
MODE_LABELS = {
    "transcribe": "Transcribe (original script)",
    "codemix": "Code-mixed (English words in English)",
    "translit": "Transliterate (Roman script)",
    "verbatim": "Verbatim (keep fillers)",
    "translate": "Translate to English",
}
STREAM_TYPES = ["balanced", "fast"]

# Canonical (our) code -> streaming code. REST uses `unknown` for auto and `od-IN` for Odia.
LANGUAGES: list[LanguageInfo] = [
    LanguageInfo("auto", "Auto-detect"),
    LanguageInfo("hi-IN", "Hindi"),
    LanguageInfo("en-IN", "English (India)"),
    LanguageInfo("bn-IN", "Bengali"),
    LanguageInfo("ta-IN", "Tamil"),
    LanguageInfo("te-IN", "Telugu"),
    LanguageInfo("mr-IN", "Marathi"),
    LanguageInfo("gu-IN", "Gujarati"),
    LanguageInfo("kn-IN", "Kannada"),
    LanguageInfo("ml-IN", "Malayalam"),
    LanguageInfo("pa-IN", "Punjabi"),
    LanguageInfo("od-IN", "Odia"),
    LanguageInfo("ur-IN", "Urdu"),
    LanguageInfo("as-IN", "Assamese"),
    LanguageInfo("ne-IN", "Nepali"),
]
_STREAM_LANG = {"auto": "auto", "od-IN": "or-IN"}
_REST_LANG = {"auto": "unknown"}
_REST_MODEL = {"saaras:v3-realtime": "saaras:v3"}

# Agent language -> Sarvam defaults when the provider language is "agent".
_AGENT_LANGUAGE = {"hinglish": ("hi-IN", "codemix"), "hi-IN": ("hi-IN", "transcribe"), "en-IN": ("en-IN", "transcribe")}


class SarvamSTTProvider:
    id = "sarvam"
    name = "Sarvam AI"

    def capabilities(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "summary": "Speech-to-text · 22 Indian languages + English · code-mixed Hinglish",
            "models": [m.__dict__ for m in MODELS],
            "languages": [{"code": "agent", "label": "Match the agent's language"}] + [l.__dict__ for l in LANGUAGES],
            "modes": [{"code": m, "label": MODE_LABELS[m]} for m in MODES],
            "stream_types": STREAM_TYPES,
            "defaults": {"model": "saaras:v4", "language": "agent", "mode": "auto", "stream_type": "balanced"},
        }

    def validate_config(self, values: dict, *, agent_language: str | None = None) -> SpeechConfig:
        model = values.get("model") or "saaras:v4"
        if model not in {m.id for m in MODELS}:
            raise STTConfigError(f"Unsupported Sarvam model '{model}'.")
        language = values.get("language") or "agent"
        mode = values.get("mode") or "auto"
        if language == "agent":
            language, agent_mode = _AGENT_LANGUAGE.get(agent_language or "", ("auto", "transcribe"))
            if agent_language and agent_language.endswith("-IN") and agent_language not in _AGENT_LANGUAGE:
                language = agent_language if agent_language in {l.code for l in LANGUAGES} else "auto"
        else:
            agent_mode = "transcribe"
        if language not in {l.code for l in LANGUAGES}:
            raise STTConfigError(f"Sarvam doesn't support language '{language}'.")
        if mode == "auto":
            mode = agent_mode
        if mode not in MODES:
            raise STTConfigError(f"Unsupported Sarvam mode '{mode}'.")
        stream_type = values.get("stream_type") or "balanced"
        if stream_type not in STREAM_TYPES:
            raise STTConfigError(f"Unsupported stream type '{stream_type}'.")
        return SpeechConfig(self.id, model, language, mode, {"stream_type": stream_type})

    # --- REST ---
    async def transcribe(self, api_key, audio, *, filename, content_type, config: SpeechConfig) -> TranscriptionResult:
        s = get_settings()
        data = {
            "model": _REST_MODEL.get(config.model, config.model),
            "mode": config.mode or "transcribe",
            "language_code": _REST_LANG.get(config.language, config.language),
        }
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(s.stt_request_timeout_s, connect=10)) as http:
                r = await http.post(
                    f"{s.sarvam_base_url.rstrip('/')}/speech-to-text",
                    headers={"api-subscription-key": api_key},
                    data=data,
                    files={"file": (filename, audio, content_type)},
                )
        except httpx.TimeoutException as exc:
            raise STTTimeoutError() from exc
        except httpx.HTTPError as exc:
            raise STTConnectionError(f"Could not reach Sarvam: {sanitize(str(exc), [api_key])}") from exc
        latency = int((time.perf_counter() - started) * 1000)
        _raise_for_status(r, api_key)
        try:
            body = r.json()
            text = (body["transcript"] or "").strip()
        except (ValueError, KeyError, TypeError) as exc:
            raise STTBadResponseError("Sarvam returned an unexpected response.") from exc
        return TranscriptionResult(
            text=text,
            provider=self.id,
            model=data["model"],
            status="completed" if text else "empty",
            language=body.get("language_code"),
            language_confidence=body.get("language_probability"),
            latency_ms=latency,
            request_id=body.get("request_id"),
        )

    # --- Streaming ---
    def stream_url(self, config: SpeechConfig) -> str:
        query = {
            "language_code": _STREAM_LANG.get(config.language, config.language),
            "model": config.model,
            "mode": config.mode or "transcribe",
            "stream_type": config.options.get("stream_type", "balanced"),
            "endpointing": "vad",
            "encoding": "mulaw",  # Twilio audio passes through unconverted
            "sample_rate": "8000",
        }
        return f"{get_settings().sarvam_ws_url}?{urlencode(query)}"

    def open_stream(self, api_key: str, config: SpeechConfig, on_event: EventHandler) -> "SarvamStream":
        return SarvamStream(self, api_key, config, on_event)

    async def health_check(self, api_key: str, config: SpeechConfig) -> str:
        """Opens a streaming session and waits for session.begin. No audio is sent, so nothing is billed."""
        stream = SarvamStream(self, api_key, config, _noop)
        try:
            await stream.start()
        finally:
            await stream.close()
        lang = "auto-detect" if config.language == "auto" else config.language
        return f"Connected · {config.model} · {lang} · mode {config.mode}"


async def _noop(_event: TranscriptEvent) -> None:
    return None


def _raise_for_status(r: httpx.Response, api_key: str) -> None:
    if r.status_code < 400:
        return
    try:
        err = r.json().get("error") or {}
        message, code = err.get("message") or "", err.get("code") or ""
    except ValueError:
        message, code = r.text, ""
    safe = sanitize(message, [api_key]) or f"HTTP {r.status_code}"
    if r.status_code in (401, 403) or code in ("invalid_api_key_error", "authentication_error"):
        raise STTAuthError("Sarvam rejected the API key.")
    if r.status_code == 429 or code in ("rate_limit_exceeded_error", "insufficient_quota_error"):
        raise STTRateLimitError("Sarvam rate limit or quota exceeded.")
    if r.status_code in (400, 422):
        raise STTConfigError(f"Sarvam rejected the request: {safe}")
    if r.status_code in (408, 504):
        raise STTTimeoutError()
    raise STTError(f"Sarvam error {r.status_code}: {safe}", retryable=r.status_code >= 500)


class SarvamStream:
    def __init__(self, provider: SarvamSTTProvider, api_key: str, config: SpeechConfig, on_event: EventHandler):
        self.provider = provider.id
        self._p = provider
        self._key = api_key
        self._config = config
        self._on_event = on_event
        self._ws = None
        self._reader: asyncio.Task | None = None
        self._pinger: asyncio.Task | None = None
        self._ready = asyncio.Event()
        self._closed = False
        self._speech_ended_at: float | None = None
        self.request_id: str | None = None
        self.error: STTError | None = None

    async def start(self) -> None:
        timeout = get_settings().stt_connect_timeout_s
        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(
                    self._p.stream_url(self._config),
                    additional_headers={"Api-Subscription-Key": self._key},
                    max_size=2**20,
                    open_timeout=timeout,
                ),
                timeout,
            )
        except InvalidStatus as exc:
            status = exc.response.status_code
            if status in (401, 403):
                raise STTAuthError("Sarvam rejected the API key.") from exc
            if status == 429:
                raise STTRateLimitError() from exc
            raise STTConnectionError(f"Sarvam refused the streaming connection (HTTP {status}).") from exc
        except (asyncio.TimeoutError, TimeoutError) as exc:
            raise STTTimeoutError("Timed out connecting to Sarvam streaming.") from exc
        except OSError as exc:
            raise STTConnectionError(f"Could not reach Sarvam streaming: {sanitize(str(exc), [self._key])}") from exc
        self._reader = asyncio.create_task(self._read())
        try:
            await asyncio.wait_for(self._ready.wait(), timeout)
        except (asyncio.TimeoutError, TimeoutError):
            await self.close()
            raise self.error or STTTimeoutError("Sarvam didn't start the streaming session.")
        if self.error:
            raise self.error
        self._pinger = asyncio.create_task(self._ping())

    async def _ping(self) -> None:
        with contextlib.suppress(Exception):
            while not self._closed:
                await asyncio.sleep(20)
                await self._ws.send(json.dumps({"event": "ping"}))

    async def send_audio(self, mulaw_8k: bytes) -> None:
        if self._closed or not self._ws or not mulaw_8k:
            return
        try:
            await self._ws.send(json.dumps({"event": "audio_input", "audio": base64.b64encode(mulaw_8k).decode()}))
        except ConnectionClosed as exc:
            raise STTConnectionError("Sarvam streaming connection closed.") from exc

    async def _read(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except (TypeError, ValueError):
                    log.warning("Ignoring malformed Sarvam message")
                    continue
                await self._handle(msg)
        except ConnectionClosed as exc:
            if not self._closed:
                self.error = self.error or _close_error(exc.rcvd.code if exc.rcvd else None)
        except Exception as exc:  # noqa: BLE001 - never let the reader die silently
            log.exception("Sarvam stream reader failed")
            self.error = self.error or STTConnectionError(sanitize(str(exc), [self._key]))
        finally:
            self._ready.set()
            if self.error and not self._closed:
                await self._on_event(TranscriptEvent("error", self.provider, text=str(self.error), fatal=True))

    async def _handle(self, msg: dict) -> None:
        event = msg.get("event")
        if event == "session.begin":
            self.request_id = msg.get("request_id")
            self._ready.set()
        elif event == "vad.speech_start":
            await self._on_event(TranscriptEvent("speech_start", self.provider, segment_id=str(msg.get("utterance_idx"))))
        elif event == "vad.speech_end":
            self._speech_ended_at = time.perf_counter()
            await self._on_event(TranscriptEvent("speech_end", self.provider, segment_id=str(msg.get("utterance_idx"))))
        elif event == "transcript.partial":
            await self._on_event(
                TranscriptEvent("partial", self.provider, text=(msg.get("text") or "").strip(),
                                segment_id=str(msg.get("utterance_idx")), language=msg.get("language"))
            )
        elif event == "transcript.final":
            latency = int((time.perf_counter() - self._speech_ended_at) * 1000) if self._speech_ended_at else None
            await self._on_event(
                TranscriptEvent("final", self.provider, text=(msg.get("text") or "").strip(),
                                segment_id=str(msg.get("utterance_idx")), language=msg.get("language"), latency_ms=latency)
            )
        elif event == "error":
            safe = sanitize(msg.get("message") or msg.get("code") or "error", [self._key])
            if msg.get("is_fatal"):
                status = msg.get("status_code")
                self.error = (
                    STTAuthError("Sarvam rejected the API key.") if status in (401, 403)
                    else STTRateLimitError() if status == 429
                    else STTConfigError(f"Sarvam rejected the session: {safe}") if status == 400
                    else STTError(f"Sarvam streaming error: {safe}")
                )
                self._ready.set()
            else:
                log.warning("Sarvam non-fatal error: %s", safe)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.send(json.dumps({"event": "end"}))
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._ws.close(), 3)
        for task in (self._pinger, self._reader):
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task


def _close_error(code: int | None) -> STTError:
    if code == 1003:
        return STTAuthError("Sarvam closed the stream: invalid key, rate limit or quota exhausted.")
    if code == 4000:
        return STTConfigError("Sarvam rejected the stream settings (model, language or parameters).")
    if code == 1008:
        return STTTimeoutError("Sarvam closed the stream after inactivity.")
    return STTConnectionError(f"Sarvam streaming connection closed (code {code}).")
