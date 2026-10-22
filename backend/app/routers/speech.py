import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import User
from ..providers import credential_values, get_credential, stt_api_key
from ..ratelimit import per_user
from ..speech.base import STTError, sanitize
from ..speech.router import PROVIDERS, user_settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/speech", tags=["speech"])

MAX_TEST_AUDIO_BYTES = 4 * 1024 * 1024  # REST limits: Sarvam 30 s, OpenAI 25 MB
ALLOWED_TYPES = {
    "audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/wave", "audio/mpeg", "audio/mp3",
    "audio/mp4", "audio/m4a", "audio/x-m4a", "audio/flac", "video/webm",
}


class SpeechSettingsIn(BaseModel):
    default_provider: str | None
    fallback_enabled: bool = False


class SpeechSettingsOut(SpeechSettingsIn):
    connected: dict[str, bool]


def _connected(db: Session, user: User) -> dict[str, bool]:
    out = {}
    for pid in PROVIDERS:
        cred = get_credential(db, user, pid)
        out[pid] = bool(cred and cred.status == "connected" and stt_api_key(db, user, pid))
    return out


@router.get("/providers")
def capabilities(user: User = Depends(current_user)):
    """Models, languages and options each STT provider supports (validated server-side on save)."""
    return [p.capabilities() for p in PROVIDERS.values()]


@router.get("/settings", response_model=SpeechSettingsOut)
def get_settings_(user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = user_settings(db, user)
    db.commit()
    return SpeechSettingsOut(default_provider=s.default_stt_provider, fallback_enabled=s.stt_fallback_enabled, connected=_connected(db, user))


@router.put("/settings", response_model=SpeechSettingsOut)
def put_settings(data: SpeechSettingsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if data.default_provider is not None and data.default_provider not in PROVIDERS:
        raise HTTPException(422, "Unknown speech provider.")
    s = user_settings(db, user)
    s.default_stt_provider = data.default_provider
    s.stt_fallback_enabled = data.fallback_enabled
    db.commit()
    return SpeechSettingsOut(default_provider=s.default_stt_provider, fallback_enabled=s.stt_fallback_enabled, connected=_connected(db, user))


@router.post("/test-transcription")
async def test_transcription(
    provider: str = Form(...),
    audio: UploadFile = File(...),
    user: User = Depends(per_user("stt-test", 5)),
    db: Session = Depends(get_db),
):
    """Transcribes a short clip with the provider's file API. Billed by the provider; the UI says so."""
    stt = PROVIDERS.get(provider)
    if stt is None:
        raise HTTPException(422, "Unknown speech provider.")
    content_type = (audio.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(415, f"Unsupported audio type '{content_type or 'unknown'}'.")
    data = await audio.read(MAX_TEST_AUDIO_BYTES + 1)
    if not data:
        raise HTTPException(422, "The audio file is empty.")
    if len(data) > MAX_TEST_AUDIO_BYTES:
        raise HTTPException(413, "Keep test clips under 30 seconds (4 MB).")
    values = credential_values(get_credential(db, user, provider))
    key = stt_api_key(db, user, provider, values)
    if not key:
        raise HTTPException(409, f"{stt.name} isn't connected.")
    try:
        config = stt.validate_config(values)
        result = await stt.transcribe(key, data, filename=audio.filename or "clip.webm", content_type=content_type, config=config)
    except STTError as exc:
        raise HTTPException(502 if exc.retryable else 422, sanitize(str(exc), [key]))
    return result.as_dict()
