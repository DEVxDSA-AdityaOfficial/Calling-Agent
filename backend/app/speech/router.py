"""Chooses which STT provider (and credentials) a call uses.

Policy (deterministic):
  1. The agent's provider, if set.
  2. Otherwise the user's default provider.
  3. Otherwise a clear configuration error.
A fallback provider is only offered when the user explicitly enabled it, and only before a call's
audio starts — a call never switches providers mid-conversation.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..models import Agent, User, UserSettings
from .base import SpeechConfig, STTConfigError, STTProvider
from .openai_whisper import OpenAIWhisperProvider
from .sarvam import SarvamSTTProvider

PROVIDERS: dict[str, STTProvider] = {p.id: p for p in (OpenAIWhisperProvider(), SarvamSTTProvider())}


@dataclass
class ResolvedSpeech:
    provider: STTProvider
    api_key: str
    config: SpeechConfig
    source: str  # "agent" | "default" | "fallback"

    def describe(self) -> dict:
        return {
            "provider": self.provider.id,
            "model": self.config.model,
            "language": self.config.language,
            "mode": self.config.mode,
            "source": self.source,
        }


def user_settings(db: Session, user: User) -> UserSettings:
    settings = db.get(UserSettings, user.id)
    if settings is None:
        settings = UserSettings(user_id=user.id)
        db.add(settings)
        db.flush()
    return settings


def provider_values(db: Session, user: User, provider_id: str) -> dict:
    from ..providers import credential_values, get_credential, stt_api_key

    values = credential_values(get_credential(db, user, provider_id))
    values["api_key"] = stt_api_key(db, user, provider_id, values)
    return values


def _build(db: Session, user: User, provider_id: str, agent_language: str | None, source: str) -> ResolvedSpeech:
    provider = PROVIDERS.get(provider_id)
    if provider is None:
        raise STTConfigError(f"Unknown speech provider '{provider_id}'.")
    values = provider_values(db, user, provider_id)
    if not values.get("api_key"):
        raise STTConfigError(f"{provider.name} isn't connected. Add its API key in Settings → API & Providers.")
    return ResolvedSpeech(provider, values["api_key"], provider.validate_config(values, agent_language=agent_language), source)


def resolve_speech(db: Session, user: User, agent: Agent, *, provider_id: str | None = None) -> ResolvedSpeech:
    """`provider_id` pins the provider (used when a call already started with one)."""
    if provider_id:
        return _build(db, user, provider_id, agent.language, "pinned")
    if agent.stt_provider:
        return _build(db, user, agent.stt_provider, agent.language, "agent")
    default = user_settings(db, user).default_stt_provider
    if default:
        return _build(db, user, default, agent.language, "default")
    raise STTConfigError("No speech-to-text provider selected. Choose a default in Settings → API & Providers, or set one on the agent.")


def resolve_fallback(db: Session, user: User, agent: Agent, primary: str) -> ResolvedSpeech | None:
    if not user_settings(db, user).stt_fallback_enabled:
        return None
    for provider_id in PROVIDERS:
        if provider_id != primary:
            try:
                return _build(db, user, provider_id, agent.language, "fallback")
            except STTConfigError:
                return None
    return None
