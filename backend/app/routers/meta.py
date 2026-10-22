import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import current_user
from ..config import get_settings
from ..conversation.factory import engine_description
from ..conversation.simulator import PERSONAS
from ..db import get_db
from ..deps import get_retell
from ..models import User
from ..prompt_builder import CALL_OUTCOMES, LANGUAGES, MODES, TONES
from ..providers import credential_values, get_credential, retell_settings
from ..speech.router import user_settings
from ..speech.tts import TTSError, list_voices
from ..retell_client import RetellClient, RetellError
from ..schemas import Options

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/options", response_model=Options)
def options(user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = get_settings()
    api_key, from_number = retell_settings(db, user)
    return Options(
        languages=LANGUAGES,
        tones=TONES,
        modes=MODES,
        outcomes=CALL_OUTCOMES,
        personas=PERSONAS,
        from_number=from_number,
        webhooks_enabled=bool(s.webhook_url),
        custom_brain_available=bool(s.websocket_base_url),
        direct_available=bool(s.websocket_base_url),
        default_stt_provider=user_settings(db, user).default_stt_provider,
        destination_allow_list=bool(s.allowed_numbers),
        retell_configured=bool(api_key),
        conversation_engine=engine_description(),
    )


@router.get("/voices")
async def voices(
    source: str = Query("retell", pattern="^(retell|elevenlabs)$"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """Retell's voice catalogue, or the user's own ElevenLabs library (for Twilio + Custom Brain)."""
    if source == "elevenlabs":
        key = credential_values(get_credential(db, user, "elevenlabs")).get("api_key")
        if not key:
            raise HTTPException(409, "Connect ElevenLabs in Settings to choose a voice.")
        try:
            return await list_voices(key)
        except TTSError as exc:
            raise HTTPException(502, str(exc))
    return await asyncio.to_thread(_retell_voices, get_retell(user, db))


def _retell_voices(retell: RetellClient):
    try:
        items = retell.list_voices()
    except RetellError as exc:
        raise HTTPException(502, str(exc))
    keys = ("voice_id", "voice_name", "provider", "gender", "accent", "age", "preview_audio_url")
    return [{k: v.get(k) for k in keys} for v in items]
