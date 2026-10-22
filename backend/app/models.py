from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship()


class UserSettings(Base):
    """Per-user preferences that aren't tied to one provider."""

    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    default_stt_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)  # whisper | sarvam
    # Off by default: when on, a call whose STT provider can't connect may start on the other one.
    stt_fallback_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ProviderCredential(Base):
    """A user's connection to a third-party provider. Secrets are Fernet-encrypted."""

    __tablename__ = "provider_credentials"
    __table_args__ = (UniqueConstraint("user_id", "provider"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(30))  # twilio | retell | elevenlabs | openai | whisper | sarvam
    secrets_encrypted: Mapped[str] = mapped_column(Text, default="")
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # non-secret settings, e.g. model, caller number
    status: Mapped[str] = mapped_column(String(20), default="untested")  # untested | connected | error
    status_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    secrets_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    business_name: Mapped[str] = mapped_column(String(200))
    # managed: Retell's LLM runs the conversation.
    # custom_brain: Retell telephony + voice, our engine answers every turn.
    # direct: Twilio Media Streams + our STT (Whisper/Sarvam) + our engine + ElevenLabs TTS.
    mode: Mapped[str] = mapped_column(String(20), default="managed")

    # Goal
    objective: Mapped[str] = mapped_column(Text, default="")
    target_audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    success_condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    fallback_behavior: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_duration_minutes: Mapped[int] = mapped_column(Integer, default=5)

    # Script & context
    script: Mapped[str] = mapped_column(Text)
    additional_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    dos_and_donts: Mapped[str | None] = mapped_column(Text, nullable=True)
    playbook: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Voice
    language: Mapped[str] = mapped_column(String(20), default="en-US")
    voice_provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    voice_id: Mapped[str] = mapped_column(String(100))
    # direct mode only: whisper | sarvam; None = use the user's default STT provider.
    stt_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tone: Mapped[str] = mapped_column(String(30), default="friendly")
    opening_line: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Generated from the fields above and pushed to Retell.
    generated_prompt: Mapped[str] = mapped_column(Text, default="")
    begin_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Secret path segment in the custom-brain WebSocket URL (Retell sends no auth headers).
    ws_token: Mapped[str] = mapped_column(String(64), index=True)
    retell_llm_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    retell_agent_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    sync_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | synced | error
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    calls: Mapped[list["Call"]] = relationship(back_populates="agent")


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"), index=True)
    to_number: Mapped[str] = mapped_column(String(32))
    from_number: Mapped[str] = mapped_column(String(32))
    customer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mode: Mapped[str] = mapped_column(String(20), default="managed")

    retell_call_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    # direct mode (Twilio Media Streams)
    twilio_call_sid: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    media_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    stt_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Provider usage, fallbacks, latency and error counters for diagnostics.
    diagnostics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # queued | ringing | in_progress | completed | failed
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    retell_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    disconnection_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_object: Mapped[list | None] = mapped_column(JSON, nullable=True)
    recording_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Post-call analysis
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(30), nullable=True)
    call_successful: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # goal_achieved | follow_up | not_interested | no_response | failed
    goal_status: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    customer_interest: Mapped[str | None] = mapped_column(String(20), nullable=True)
    follow_up_requested: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    appointment_preference: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_objection: Mapped[str | None] = mapped_column(Text, nullable=True)
    unanswered_questions: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    agent: Mapped[Agent] = relationship(back_populates="calls")
