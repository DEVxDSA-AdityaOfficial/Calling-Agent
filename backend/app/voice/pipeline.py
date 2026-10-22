"""Real-time voice loop for “Twilio + Custom Brain” calls.

    Twilio Media Stream (μ-law 8 kHz)
      → bounded audio queue → streaming STT (Whisper or Sarvam)
      → final transcript → existing ConversationModel (same prompt/brain as Custom Brain)
      → sentence chunks → ElevenLabs TTS (μ-law 8 kHz) → Twilio

Everything external is injected (STT stream, TTS, model, Twilio sender, hang-up, persistence),
so the loop is unit-testable without network access.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from ..conversation.base import ConversationModel, ConversationModelError
from ..conversation.brain import EndCallFilter, build_messages, render_variables
from ..speech.audio import validate_twilio_media_format
from ..speech.base import STTError, STTStream, TranscriptEvent

log = logging.getLogger(__name__)

AUDIO_QUEUE_FRAMES = 250  # ≈5 s of 20 ms Twilio frames; beyond this the oldest audio is dropped
INTERRUPT_MIN_WORDS = 2
DUPLICATE_WINDOW_S = 2.0
SILENCE_REMINDER_S = 9.0
MAX_REMINDERS = 2
FALLBACK_REPLY = "Sorry, I didn't catch that. Could you say it again?"
TECHNICAL_GOODBYE = "Sorry, I'm having technical trouble on my side. We'll call you back. Goodbye!"

_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+|\n+")


class TTS(Protocol):
    def stream(self, text: str) -> AsyncIterator[bytes]: ...


@dataclass
class Diagnostics:
    stt_provider: str = ""
    stt_model: str = ""
    stt_source: str = ""
    fallback_events: list[dict] = field(default_factory=list)
    utterances: int = 0
    stt_latencies_ms: list[int] = field(default_factory=list)
    first_audio_latencies_ms: list[int] = field(default_factory=list)
    interruptions: int = 0
    duplicates_suppressed: int = 0
    dropped_frames: int = 0
    reminders: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        def avg(xs):
            return int(sum(xs) / len(xs)) if xs else None

        return {
            "stt": {"provider": self.stt_provider, "model": self.stt_model, "source": self.stt_source},
            "fallback_events": self.fallback_events,
            "utterances": self.utterances,
            "avg_stt_latency_ms": avg(self.stt_latencies_ms),
            "avg_first_audio_ms": avg(self.first_audio_latencies_ms),
            "interruptions": self.interruptions,
            "duplicates_suppressed": self.duplicates_suppressed,
            "dropped_frames": self.dropped_frames,
            "reminders": self.reminders,
            "errors": self.errors[-10:],
        }


def split_sentences(buffer: str) -> tuple[list[str], str]:
    """Return complete sentences and the unfinished remainder."""
    parts = _SENTENCE_END.split(buffer)
    if len(parts) == 1:
        return [], buffer
    complete = [p.strip() for p in parts[:-1] if p.strip()]
    return complete, parts[-1]


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", "", text.lower()).split())


class VoicePipeline:
    def __init__(
        self,
        *,
        prompt: str,
        begin_message: str | None,
        variables: dict[str, str],
        model: ConversationModel,
        tts: TTS,
        send: Callable[[dict], Awaitable[None]],
        hangup: Callable[[], Awaitable[None]],
        persist: Callable[[list[dict]], Awaitable[None]],
        max_duration_s: float,
        diagnostics: Diagnostics | None = None,
        silence_reminder_s: float = SILENCE_REMINDER_S,
    ):
        self.prompt = prompt
        self.begin_message = begin_message
        self.variables = variables
        self.model = model
        self.tts = tts
        self._send = send
        self._hangup = hangup
        self._persist = persist
        self.max_duration_s = max_duration_s
        self.diag = diagnostics or Diagnostics()
        self.silence_reminder_s = silence_reminder_s

        self.stream_sid: str | None = None
        self.stt: STTStream | None = None
        self.transcript: list[dict] = []
        self.agent_speaking = False
        self.ended = False
        self.closed = False

        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=AUDIO_QUEUE_FRAMES)
        self._pump: asyncio.Task | None = None
        self._watchdog: asyncio.Task | None = None
        self._response: asyncio.Task | None = None
        self._pending_marks: set[str] = set()
        self._mark_seq = 0
        self._hangup_when_quiet = False
        self._hung_up = False
        self._seen_segments: set[str] = set()
        self._last_final: tuple[str, float] | None = None
        self._last_activity = time.monotonic()
        self._started_at = time.monotonic()
        self._final_received_at: float | None = None

    # --- Lifecycle -----------------------------------------------------------------------------
    async def start(self, start_msg: dict, stt: STTStream) -> None:
        """Called on Twilio's `start` event once the STT stream is open."""
        validate_twilio_media_format((start_msg.get("start") or {}).get("mediaFormat"))
        self.stream_sid = start_msg.get("streamSid") or (start_msg.get("start") or {}).get("streamSid")
        self.stt = stt
        self._started_at = time.monotonic()
        self._pump = asyncio.create_task(self._pump_audio())
        self._watchdog = asyncio.create_task(self._watch())
        self._response = asyncio.create_task(self._greet())

    async def close(self) -> None:
        """Idempotent cleanup: stop tasks, close STT, drop buffered audio, save transcript."""
        if self.closed:
            return
        self.closed = True
        for task in (self._response, self._watchdog, self._pump):
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        if self.stt is not None:
            with contextlib.suppress(Exception):
                await self.stt.close()
        while not self._queue.empty():
            self._queue.get_nowait()
        self._pending_marks.clear()
        with contextlib.suppress(Exception):
            await self._persist(self.transcript)

    # --- Twilio events -------------------------------------------------------------------------
    def on_media(self, payload_b64: str) -> None:
        if self.closed or not payload_b64:
            return
        try:
            chunk = base64.b64decode(payload_b64, validate=True)
        except (ValueError, TypeError):
            self.diag.errors.append("malformed media payload")
            return
        if self._queue.full():  # backpressure: STT is behind, drop the oldest frame
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
            self.diag.dropped_frames += 1
        self._queue.put_nowait(chunk)

    async def on_mark(self, name: str) -> None:
        if name not in self._pending_marks:
            return  # stale/duplicate mark (e.g. echoed after a `clear`)
        self._pending_marks.discard(name)
        if not self._pending_marks:
            self.agent_speaking = False
            self._last_activity = time.monotonic()
            if self._hangup_when_quiet:
                await self._do_hangup()

    # --- STT events ----------------------------------------------------------------------------
    async def on_transcript(self, event: TranscriptEvent) -> None:
        if self.closed:
            return
        if event.type == "speech_start":
            self._last_activity = time.monotonic()
            if self.agent_speaking and not self.ended:
                await self.interrupt()
        elif event.type == "partial":
            self._last_activity = time.monotonic()
            if self.agent_speaking and not self.ended and len(event.text.split()) >= INTERRUPT_MIN_WORDS:
                await self.interrupt()
        elif event.type == "final":
            await self._on_final(event)
        elif event.type == "error" and event.fatal:
            self.diag.errors.append(event.text)
            log.error("STT stream failed mid-call: %s", event.text)
            await self._end_with(TECHNICAL_GOODBYE)

    async def _on_final(self, event: TranscriptEvent) -> None:
        text = event.text.strip()
        if not text or self.ended:
            return
        now = time.monotonic()
        if event.segment_id and event.segment_id in self._seen_segments:
            self.diag.duplicates_suppressed += 1
            return
        if self._last_final and self._last_final[0] == _norm(text) and now - self._last_final[1] < DUPLICATE_WINDOW_S:
            self.diag.duplicates_suppressed += 1
            return
        if event.segment_id:
            self._seen_segments.add(event.segment_id)
        self._last_final = (_norm(text), now)
        self._last_activity = now
        self._final_received_at = now
        self.diag.utterances += 1
        if event.latency_ms is not None:
            self.diag.stt_latencies_ms.append(event.latency_ms)
        if self._response and not self._response.done():
            await self.interrupt()
        self.transcript.append({"role": "user", "content": text})
        await self._persist(self.transcript)
        self._response = asyncio.create_task(self._respond())

    # --- Speaking ------------------------------------------------------------------------------
    async def interrupt(self) -> None:
        """Caller barged in: stop generating, flush Twilio's audio buffer."""
        if self._response and not self._response.done():
            self._response.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._response
        if self.agent_speaking or self._pending_marks:
            await self._send({"event": "clear", "streamSid": self.stream_sid})
            self.diag.interruptions += 1
        self._pending_marks.clear()
        self.agent_speaking = False

    async def _speak(self, text: str) -> None:
        first = True
        async for chunk in self.tts.stream(text):
            if first and self._final_received_at is not None:
                self.diag.first_audio_latencies_ms.append(int((time.monotonic() - self._final_received_at) * 1000))
                self._final_received_at = None
            first = False
            self.agent_speaking = True
            await self._send({"event": "media", "streamSid": self.stream_sid, "media": {"payload": base64.b64encode(chunk).decode()}})
        self._mark_seq += 1
        name = f"m{self._mark_seq}"
        self._pending_marks.add(name)
        await self._send({"event": "mark", "streamSid": self.stream_sid, "mark": {"name": name}})

    async def _greet(self) -> None:
        if self.begin_message:
            text = render_variables(self.begin_message, self.variables)
            self.transcript.append({"role": "agent", "content": text})
            await self._persist(self.transcript)
            await self._speak(text)
        else:
            await self._respond()

    async def _respond(self, reminder: bool = False) -> None:
        spoken: list[str] = []
        end = EndCallFilter()
        buffer = ""
        try:
            messages = build_messages(self.prompt, self.transcript, self.variables, reminder=reminder)
            async for chunk in self.model.stream(messages):
                buffer += end.feed(chunk)
                sentences, buffer = split_sentences(buffer)
                for sentence in sentences:
                    spoken.append(sentence)
                    await self._speak(sentence)
                if end.ended:
                    break
            buffer += end.flush()
            if buffer.strip():
                spoken.append(buffer.strip())
                await self._speak(buffer.strip())
        except asyncio.CancelledError:
            if spoken:  # keep what the caller actually heard (or most of it)
                self.transcript.append({"role": "agent", "content": " ".join(spoken) + " …"})
            raise
        except ConversationModelError as exc:
            self.diag.errors.append(str(exc)[:200])
            spoken = [FALLBACK_REPLY]
            await self._speak(FALLBACK_REPLY)
        except Exception as exc:  # noqa: BLE001 - TTS/network failure: end gracefully
            log.exception("Voice response failed")
            self.diag.errors.append(type(exc).__name__)
            if not spoken:
                await self._do_hangup()
                return
        if spoken:
            self.transcript.append({"role": "agent", "content": " ".join(spoken)})
            await self._persist(self.transcript)
        if end.ended:
            await self._finish()

    async def _end_with(self, text: str) -> None:
        if self.ended:
            return
        await self.interrupt()
        self.ended = True
        with contextlib.suppress(Exception):
            self.transcript.append({"role": "agent", "content": text})
            await self._speak(text)
        await self._finish()

    async def _finish(self) -> None:
        self.ended = True
        if self._pending_marks:
            self._hangup_when_quiet = True  # hang up once Twilio confirms the goodbye was played
        else:
            await self._do_hangup()

    async def _do_hangup(self) -> None:
        if self._hung_up:
            return
        self._hung_up = True
        self.ended = True
        with contextlib.suppress(Exception):
            await self._hangup()

    # --- Background tasks ----------------------------------------------------------------------
    async def _pump_audio(self) -> None:
        while True:
            chunk = await self._queue.get()
            try:
                await self.stt.send_audio(chunk)
            except STTError as exc:
                self.diag.errors.append(str(exc))
                await self._end_with(TECHNICAL_GOODBYE)
                return

    async def _watch(self) -> None:
        while not self.ended:
            await asyncio.sleep(0.5)
            now = time.monotonic()
            if now - self._started_at > self.max_duration_s:
                log.info("Max call duration reached")
                await self._end_with("We're out of time for today. Thank you so much for speaking with me. Goodbye!")
                return
            busy = self.agent_speaking or (self._response and not self._response.done())
            if busy or now - self._last_activity < self.silence_reminder_s:
                continue
            if self.diag.reminders >= MAX_REMINDERS:
                await self._end_with("It seems this isn't a good time. Thank you, goodbye!")
                return
            self.diag.reminders += 1
            self._last_activity = now
            self._response = asyncio.create_task(self._respond(reminder=True))
