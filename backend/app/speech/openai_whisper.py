"""OpenAI Whisper speech-to-text.

Files / tests:  POST {OPENAI_BASE_URL}/audio/transcriptions  model=whisper-1 (deprecated; shuts down 2027-02-26)
Live calls:     WSS  {OPENAI_REALTIME_URL}  transcription session, model=gpt-realtime-whisper
Docs: https://developers.openai.com/api/docs/guides/speech-to-text
      https://developers.openai.com/api/docs/guides/realtime-transcription

`whisper-1` isn't available in Realtime sessions, and `gpt-realtime-whisper` isn't available on the
file endpoint, so each path uses the Whisper model that endpoint supports — never a non-Whisper model.
`gpt-realtime-whisper` has no server-side VAD (turn_detection must be null): we endpoint with a
local energy VAD and send `input_audio_buffer.commit` at the end of each utterance.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import time

import httpx
import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus

from ..config import get_settings
from .audio import EnergyVAD
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

STREAMING_MODEL = "gpt-realtime-whisper"
BATCH_MODEL = "whisper-1"
MODELS = [
    ModelInfo(STREAMING_MODEL, "Whisper realtime (live calls)", streaming=True, batch=False,
              note="Streaming Whisper for live audio. No server VAD: endpointing is done locally."),
    ModelInfo(BATCH_MODEL, "Whisper v1 (files & tests)", streaming=False, batch=True,
              note="Deprecated by OpenAI; available until 26 Feb 2027."),
]
DELAYS = ["minimal", "low", "medium", "high"]
LANGUAGES = [
    LanguageInfo("auto", "Auto-detect"),
    LanguageInfo("en", "English"),
    LanguageInfo("hi", "Hindi"),
    LanguageInfo("bn", "Bengali"),
    LanguageInfo("ta", "Tamil"),
    LanguageInfo("te", "Telugu"),
    LanguageInfo("mr", "Marathi"),
    LanguageInfo("gu", "Gujarati"),
    LanguageInfo("kn", "Kannada"),
    LanguageInfo("ml", "Malayalam"),
    LanguageInfo("pa", "Punjabi"),
    LanguageInfo("ur", "Urdu"),
    LanguageInfo("es", "Spanish"),
    LanguageInfo("fr", "French"),
    LanguageInfo("de", "German"),
]
# Hinglish is code-mixed: a single-language hint would push Whisper toward one script, so auto-detect.
_AGENT_LANGUAGE = {"hinglish": "auto"}


class OpenAIWhisperProvider:
    id = "whisper"
    name = "OpenAI Whisper"

    def capabilities(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "summary": "Speech-to-text · Multilingual",
            "models": [m.__dict__ for m in MODELS],
            "languages": [{"code": "agent", "label": "Match the agent's language"}] + [l.__dict__ for l in LANGUAGES],
            "delays": DELAYS,
            "defaults": {"model": STREAMING_MODEL, "language": "agent", "delay": "low"},
            "deprecation": "whisper-1 is deprecated by OpenAI and shuts down on 26 Feb 2027.",
        }

    def validate_config(self, values: dict, *, agent_language: str | None = None) -> SpeechConfig:
        language = values.get("language") or "agent"
        if language == "agent":
            language = _AGENT_LANGUAGE.get(agent_language or "", (agent_language or "auto").split("-")[0] or "auto")
            if language not in {l.code for l in LANGUAGES}:
                language = "auto"
        if language not in {l.code for l in LANGUAGES}:
            raise STTConfigError(f"Whisper language must be an ISO-639-1 code; '{language}' isn't supported.")
        delay = values.get("delay") or "low"
        if delay not in DELAYS:
            raise STTConfigError(f"Unsupported delay '{delay}'.")
        try:
            silence_ms = int(values.get("silence_ms") or 600)
        except ValueError as exc:
            raise STTConfigError("End-of-speech silence must be a number of milliseconds.") from exc
        if not 300 <= silence_ms <= 2000:
            raise STTConfigError("End-of-speech silence must be between 300 and 2000 ms.")
        return SpeechConfig(self.id, STREAMING_MODEL, language, None, {"delay": delay, "silence_ms": silence_ms})

    # --- Files ---
    async def transcribe(self, api_key, audio, *, filename, content_type, config: SpeechConfig) -> TranscriptionResult:
        s = get_settings()
        data = {"model": BATCH_MODEL, "response_format": "verbose_json"}
        if config.language != "auto":
            data["language"] = config.language
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(s.stt_request_timeout_s, connect=10)) as http:
                r = await http.post(
                    f"{s.openai_base_url.rstrip('/')}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    data=data,
                    files={"file": (filename, audio, content_type)},
                )
        except httpx.TimeoutException as exc:
            raise STTTimeoutError() from exc
        except httpx.HTTPError as exc:
            raise STTConnectionError(f"Could not reach OpenAI: {sanitize(str(exc), [api_key])}") from exc
        latency = int((time.perf_counter() - started) * 1000)
        _raise_for_status(r, api_key)
        try:
            body = r.json()
            text = (body["text"] or "").strip()
        except (ValueError, KeyError, TypeError) as exc:
            raise STTBadResponseError("OpenAI returned an unexpected response.") from exc
        return TranscriptionResult(
            text=text,
            provider=self.id,
            model=BATCH_MODEL,
            status="completed" if text else "empty",
            language=body.get("language"),
            latency_ms=latency,
            audio_duration_s=body.get("duration"),
        )

    async def health_check(self, api_key: str, config: SpeechConfig) -> str:
        s = get_settings()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=10)) as http:
                r = await http.get(f"{s.openai_base_url.rstrip('/')}/models", headers={"Authorization": f"Bearer {api_key}"})
        except httpx.TimeoutException as exc:
            raise STTTimeoutError() from exc
        except httpx.HTTPError as exc:
            raise STTConnectionError(f"Could not reach OpenAI: {sanitize(str(exc), [api_key])}") from exc
        _raise_for_status(r, api_key)
        try:
            ids = {m["id"] for m in r.json().get("data", [])}
        except (ValueError, KeyError, TypeError) as exc:
            raise STTBadResponseError("OpenAI returned an unexpected model list.") from exc
        missing = [m for m in (STREAMING_MODEL, BATCH_MODEL) if m not in ids]
        if STREAMING_MODEL in missing:
            raise STTConfigError(f"This key can't use {STREAMING_MODEL}, which live calls need.")
        note = f" ({BATCH_MODEL} unavailable: file tests disabled)" if missing else ""
        return f"Connected · {STREAMING_MODEL} for calls · {BATCH_MODEL} for files{note}"

    # --- Streaming ---
    def session_update(self, config: SpeechConfig) -> dict:
        transcription = {"model": STREAMING_MODEL, "delay": config.options.get("delay", "low")}
        if config.language != "auto":
            transcription["language"] = config.language
        return {
            "type": "session.update",
            "session": {
                "type": "transcription",
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcmu"},  # Twilio's G.711 μ-law passes through unconverted
                        "transcription": transcription,
                        "turn_detection": None,  # required for gpt-realtime-whisper
                    }
                },
            },
        }

    def open_stream(self, api_key: str, config: SpeechConfig, on_event: EventHandler) -> "WhisperStream":
        return WhisperStream(self, api_key, config, on_event)


def _raise_for_status(r: httpx.Response, api_key: str) -> None:
    if r.status_code < 400:
        return
    try:
        message = (r.json().get("error") or {}).get("message") or ""
    except ValueError:
        message = r.text
    safe = sanitize(message, [api_key]) or f"HTTP {r.status_code}"
    if r.status_code in (401, 403):
        raise STTAuthError("OpenAI rejected the API key.")
    if r.status_code == 429:
        raise STTRateLimitError("OpenAI rate limit or quota exceeded.")
    if r.status_code in (400, 404, 413, 415, 422):
        raise STTConfigError(f"OpenAI rejected the request: {safe}")
    if r.status_code in (408, 504):
        raise STTTimeoutError()
    raise STTError(f"OpenAI error {r.status_code}: {safe}", retryable=r.status_code >= 500)


class WhisperStream:
    def __init__(self, provider: OpenAIWhisperProvider, api_key: str, config: SpeechConfig, on_event: EventHandler):
        self.provider = provider.id
        self._p = provider
        self._key = api_key
        self._config = config
        self._on_event = on_event
        self._ws = None
        self._reader: asyncio.Task | None = None
        self._vad = EnergyVAD(silence_ms=int(config.options.get("silence_ms", 600)))
        self._ready = asyncio.Event()
        self._closed = False
        self._has_audio = False
        self._commit_times: list[float] = []
        self._partials: dict[str, str] = {}
        self._turn = 0
        self.error: STTError | None = None

    async def start(self) -> None:
        s = get_settings()
        timeout = s.stt_connect_timeout_s
        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(
                    s.openai_realtime_url,
                    additional_headers={"Authorization": f"Bearer {self._key}"},
                    max_size=2**20,
                    open_timeout=timeout,
                ),
                timeout,
            )
        except InvalidStatus as exc:
            status = exc.response.status_code
            if status in (401, 403):
                raise STTAuthError("OpenAI rejected the API key.") from exc
            if status == 429:
                raise STTRateLimitError() from exc
            raise STTConnectionError(f"OpenAI refused the realtime connection (HTTP {status}).") from exc
        except (asyncio.TimeoutError, TimeoutError) as exc:
            raise STTTimeoutError("Timed out connecting to OpenAI realtime.") from exc
        except OSError as exc:
            raise STTConnectionError(f"Could not reach OpenAI realtime: {sanitize(str(exc), [self._key])}") from exc
        self._reader = asyncio.create_task(self._read())
        await self._ws.send(json.dumps(self._p.session_update(self._config)))
        try:
            await asyncio.wait_for(self._ready.wait(), timeout)
        except (asyncio.TimeoutError, TimeoutError):
            await self.close()
            raise self.error or STTTimeoutError("OpenAI didn't confirm the transcription session.")
        if self.error:
            await self.close()
            raise self.error

    async def send_audio(self, mulaw_8k: bytes) -> None:
        if self._closed or not self._ws or not mulaw_8k:
            return
        try:
            await self._ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": base64.b64encode(mulaw_8k).decode()}))
            self._has_audio = True
            for edge in self._vad.feed(mulaw_8k):
                if edge == "start":
                    self._turn += 1
                    await self._on_event(TranscriptEvent("speech_start", self.provider, segment_id=f"turn-{self._turn}"))
                else:
                    await self._commit()
        except ConnectionClosed as exc:
            raise STTConnectionError("OpenAI realtime connection closed.") from exc

    async def _commit(self) -> None:
        self._commit_times.append(time.perf_counter())
        await self._on_event(TranscriptEvent("speech_end", self.provider, segment_id=f"turn-{self._turn}"))
        await self._ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        self._has_audio = False

    async def _read(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except (TypeError, ValueError):
                    log.warning("Ignoring malformed OpenAI realtime message")
                    continue
                await self._handle(msg)
        except ConnectionClosed as exc:
            if not self._closed:
                code = exc.rcvd.code if exc.rcvd else None
                self.error = self.error or STTConnectionError(f"OpenAI realtime connection closed (code {code}).")
        except Exception as exc:  # noqa: BLE001
            log.exception("OpenAI realtime reader failed")
            self.error = self.error or STTConnectionError(sanitize(str(exc), [self._key]))
        finally:
            self._ready.set()
            if self.error and not self._closed:
                await self._on_event(TranscriptEvent("error", self.provider, text=str(self.error), fatal=True))

    async def _handle(self, msg: dict) -> None:
        kind = msg.get("type", "")
        if kind in ("session.created", "session.updated", "transcription_session.created", "transcription_session.updated"):
            self._ready.set()
        elif kind == "conversation.item.input_audio_transcription.delta":
            item = msg.get("item_id") or ""
            self._partials[item] = self._partials.get(item, "") + (msg.get("delta") or "")
            await self._on_event(TranscriptEvent("partial", self.provider, text=self._partials[item].strip(), segment_id=item))
        elif kind == "conversation.item.input_audio_transcription.completed":
            item = msg.get("item_id") or ""
            self._partials.pop(item, None)
            committed = self._commit_times.pop(0) if self._commit_times else None
            latency = int((time.perf_counter() - committed) * 1000) if committed else None
            await self._on_event(
                TranscriptEvent("final", self.provider, text=(msg.get("transcript") or "").strip(), segment_id=item, latency_ms=latency)
            )
        elif kind == "conversation.item.input_audio_transcription.failed":
            log.warning("Whisper failed to transcribe one utterance: %s", sanitize(json.dumps(msg.get("error") or {}), [self._key]))
        elif kind == "error":
            err = msg.get("error") or {}
            safe = sanitize(err.get("message") or err.get("code") or "error", [self._key])
            if err.get("code") == "input_audio_buffer_commit_empty":
                return  # VAD fired on noise with nothing buffered
            if not self._ready.is_set() or err.get("type") in ("invalid_request_error", "authentication_error"):
                self.error = (
                    STTAuthError("OpenAI rejected the API key.") if err.get("type") == "authentication_error"
                    else STTConfigError(f"OpenAI rejected the transcription session: {safe}")
                )
                self._ready.set()
            else:
                log.warning("OpenAI realtime error: %s", safe)

    async def close(self) -> None:
        if self._closed:
            return
        if self._ws is not None and self._has_audio and self._vad.in_speech:
            with contextlib.suppress(Exception):
                await self._ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        self._closed = True
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._ws.close(), 3)
        if self._reader and not self._reader.done():
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader
