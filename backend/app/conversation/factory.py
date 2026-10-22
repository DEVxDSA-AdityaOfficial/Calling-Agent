from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import User
from .base import ConversationModel, ConversationModelError
from .openai_compat import OpenAICompatibleModel


def openai_settings(values: dict) -> tuple[str, str, str]:
    """(api_key, base_url, model) from a user's OpenAI connection, falling back to platform defaults."""
    s = get_settings()
    return values.get("api_key") or s.openai_api_key, s.openai_base_url, values.get("model") or s.openai_model


def engine_description() -> dict:
    s = get_settings()
    if s.conversation_provider == "local_slm":
        return {"provider": "local_slm", "model": s.local_slm_model, "base_url": s.local_slm_base_url}
    return {"provider": "openai", "model": s.openai_model, "platform_key": bool(s.openai_api_key)}


def get_conversation_model(db: Session, user: User) -> ConversationModel:
    from ..providers import credential_values, get_credential

    s = get_settings()
    if s.conversation_provider == "local_slm":
        if not s.local_slm_model:
            raise ConversationModelError("CONVERSATION_PROVIDER=local_slm but LOCAL_SLM_MODEL is not set.")
        return OpenAICompatibleModel(
            base_url=s.local_slm_base_url, api_key=s.local_slm_api_key, model=s.local_slm_model, name="Local SLM"
        )
    if s.conversation_provider != "openai":
        raise ConversationModelError(f"Unknown CONVERSATION_PROVIDER '{s.conversation_provider}'.")

    key, base_url, model = openai_settings(credential_values(get_credential(db, user, "openai")))
    if not key:
        raise ConversationModelError("OpenAI isn't connected. Add a key in Settings → API & Providers.")
    return OpenAICompatibleModel(base_url=base_url, api_key=key, model=model, name="OpenAI")
