"""Provider-independent speech-to-text interface.

Provider-specific request/response formats stay inside each provider module. Everything else
(the call pipeline, settings, tests) works with `TranscriptionResult`, `TranscriptEvent` and
`SpeechConfig`.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

# --- Errors (messages are always safe to show to users: no secrets, no raw payloads) ---


class STTError(Exception):
    code = "stt_error"

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class STTConfigError(STTError):
    code = "config_error"


class STTAuthError(STTError):
    code = "auth_error"


class STTRateLimitError(STTError):
    code = "rate_limited"

    def __init__(self, message: str = "The provider is rate limiting requests. Try again shortly."):
        super().__init__(message, retryable=True)


class STTTimeoutError(STTError):
    code = "timeout"

    def __init__(self, message: str = "The provider took too long to respond."):
        super().__init__(message, retryable=True)


class STTConnectionError(STTError):
    code = "connection_error"


class STTBadResponseError(STTError):
    code = "bad_response"


_SECRET_PATTERNS = [
    re.compile(r"\b(?:sk|key|xi|api)[-_][A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bAC[a-f0-9]{32}\b"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"[A-Fa-f0-9]{32,}"),
]


def sanitize(message: str, secrets: list[str | None] | None = None, limit: int = 300) -> str:
    """Strip anything that looks like a credential from provider error text."""
    text = str(message or "")
    for secret in secrets or []:
        if secret and len(secret) >= 4:
            text = text.replace(secret, "[redacted]")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    text = " ".join(text.split())
    return text[:limit] + ("…" if len(text) > limit else "")


# --- Configuration & results ---

ProviderId = Literal["whisper", "sarvam"]


@dataclass(frozen=True)
class SpeechConfig:
    """Validated, provider-specific settings (everything except the API key)."""

    provider: str
    model: str  # streaming model used on live calls
    language: str  # provider-native code for streaming, or "auto"
    mode: str | None = None  # Sarvam output mode
    options: dict = field(default_factory=dict)


@dataclass
class TranscriptionResult:
    text: str
    provider: str
    model: str
    status: Literal["completed", "empty"]
    language: str | None = None
    language_confidence: float | None = None
    latency_ms: int | None = None
    audio_duration_s: float | None = None
    request_id: str | None = None

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class TranscriptEvent:
    """Normalized streaming event."""

    type: Literal["speech_start", "speech_end", "partial", "final", "error"]
    provider: str
    text: str = ""
    segment_id: str | None = None
    language: str | None = None
    latency_ms: int | None = None  # end of speech -> final transcript
    fatal: bool = False


EventHandler = Callable[[TranscriptEvent], Awaitable[None]]


class STTStream(Protocol):
    provider: str

    async def start(self) -> None:
        """Open the connection; raises STTError on auth/config/connection failure."""

    async def send_audio(self, mulaw_8k: bytes) -> None:
        """Feed raw G.711 μ-law 8 kHz mono audio (Twilio's native format)."""

    async def close(self) -> None:
        """Flush and close. Safe to call more than once."""


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    streaming: bool
    batch: bool
    note: str = ""


@dataclass(frozen=True)
class LanguageInfo:
    code: str  # our canonical code (BCP-47-ish, e.g. hi-IN, or "auto")
    label: str


class STTProvider(Protocol):
    id: str
    name: str

    def capabilities(self) -> dict: ...

    def validate_config(self, values: dict, *, agent_language: str | None = None) -> SpeechConfig: ...

    async def health_check(self, api_key: str, config: SpeechConfig) -> str: ...

    async def transcribe(
        self, api_key: str, audio: bytes, *, filename: str, content_type: str, config: SpeechConfig
    ) -> TranscriptionResult: ...

    def open_stream(self, api_key: str, config: SpeechConfig, on_event: EventHandler) -> STTStream: ...
