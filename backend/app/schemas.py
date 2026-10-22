from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .prompt_builder import LANGUAGES, MODES, TONES


# --- Auth ---
class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str


# --- Providers ---
class ProviderFieldOut(BaseModel):
    key: str
    label: str
    secret: bool
    placeholder: str
    required: bool
    kind: str = "text"
    options: list[dict[str, str]] = []
    help: str = ""
    value: str | None  # masked for secrets


class ProviderOut(BaseModel):
    id: str
    name: str
    category: str
    purpose: str
    note: str
    fields: list[ProviderFieldOut]
    configured: bool
    status: str  # not_configured | untested | connected | error
    status_detail: str | None
    last_tested_at: datetime | None
    secrets_rotated_at: datetime | None = None


class ProviderIn(BaseModel):
    values: dict[str, str | None]


# --- Agents ---
class Playbook(BaseModel):
    opening: str = ""
    qualification_questions: list[str] = []
    value_points: list[str] = []
    objections: list[dict[str, str]] = []
    follow_up_questions: list[str] = []
    closing_strategy: str = ""
    success_criteria: list[str] = []


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    business_name: str = Field(min_length=1, max_length=200)
    mode: str = "managed"
    objective: str = Field(min_length=3, max_length=500)
    target_audience: str | None = Field(default=None, max_length=500)
    success_condition: str | None = Field(default=None, max_length=500)
    fallback_behavior: str | None = Field(default=None, max_length=500)
    max_duration_minutes: int = Field(default=5, ge=1, le=30)
    script: str = Field(min_length=20, max_length=8000)
    additional_context: str | None = Field(default=None, max_length=8000)
    dos_and_donts: str | None = Field(default=None, max_length=3000)
    playbook: Playbook | None = None
    language: str = "en-US"
    voice_provider: str | None = Field(default=None, max_length=30)
    voice_id: str = Field(min_length=1, max_length=100)
    stt_provider: str | None = None
    tone: str = "friendly"
    opening_line: str | None = Field(default=None, max_length=500)

    @field_validator("stt_provider")
    @classmethod
    def _stt(cls, v: str | None) -> str | None:
        if v in (None, "", "default"):
            return None
        if v not in ("whisper", "sarvam"):
            raise ValueError("speech provider must be whisper or sarvam")
        return v

    @field_validator("name", "business_name", "script", "voice_id", "objective")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v

    @field_validator("language")
    @classmethod
    def _language(cls, v: str) -> str:
        if v not in LANGUAGES:
            raise ValueError(f"unsupported language; choose one of {', '.join(LANGUAGES)}")
        return v

    @field_validator("tone")
    @classmethod
    def _tone(cls, v: str) -> str:
        if v not in TONES:
            raise ValueError(f"unsupported tone; choose one of {', '.join(TONES)}")
        return v

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        if v not in MODES:
            raise ValueError(f"unsupported mode; choose one of {', '.join(MODES)}")
        return v


class PromptPreview(BaseModel):
    prompt: str
    begin_message: str | None


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    business_name: str
    mode: str
    objective: str
    target_audience: str | None
    success_condition: str | None
    fallback_behavior: str | None
    max_duration_minutes: int
    script: str
    additional_context: str | None
    dos_and_donts: str | None
    playbook: Playbook | None
    language: str
    voice_provider: str | None
    voice_id: str
    stt_provider: str | None
    tone: str
    opening_line: str | None
    generated_prompt: str
    begin_message: str | None
    retell_agent_id: str | None
    sync_status: str
    sync_error: str | None
    created_at: datetime
    updated_at: datetime


class SimTurnIn(BaseModel):
    persona: str
    history: list[dict[str, str]] = Field(default_factory=list, max_length=60)


class SimEvaluateIn(BaseModel):
    persona: str
    history: list[dict[str, str]] = Field(min_length=1, max_length=60)


# --- Calls ---
class CallIn(BaseModel):
    agent_id: int
    to_number: str = Field(min_length=3, max_length=32)
    customer_name: str | None = Field(default=None, max_length=200)
    consent_confirmed: bool = Field(
        description="Caller attests the recipient has consented to receive this AI call."
    )


class TranscriptTurn(BaseModel):
    role: str | None
    content: str | None


class CallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_id: int
    agent_name: str | None = None
    mode: str
    to_number: str
    from_number: str
    customer_name: str | None
    retell_call_id: str | None
    twilio_call_sid: str | None = None
    stt_provider: str | None = None
    status: str
    retell_status: str | None
    disconnection_reason: str | None
    error: str | None
    started_at: datetime | None
    ended_at: datetime | None
    duration_ms: int | None
    summary: str | None
    sentiment: str | None
    call_successful: bool | None
    outcome: str | None
    goal_status: str | None
    customer_interest: str | None
    follow_up_requested: bool | None
    appointment_preference: str | None
    primary_objection: str | None
    unanswered_questions: str | None
    next_action: str | None
    key_notes: str | None
    created_at: datetime


class CallDetailOut(CallOut):
    diagnostics: dict | None = None
    transcript: str | None
    transcript_object: list[TranscriptTurn] | None
    recording_url: str | None


class Stats(BaseModel):
    total_calls: int
    completed: int
    failed: int
    interested: int
    goal_achieved: int
    follow_ups: int
    avg_duration_ms: int | None


class Options(BaseModel):
    languages: dict[str, str]
    tones: dict[str, str]
    modes: dict[str, str]
    outcomes: list[str]
    personas: dict[str, dict[str, str]]
    from_number: str
    webhooks_enabled: bool
    custom_brain_available: bool
    direct_available: bool
    default_stt_provider: str | None
    destination_allow_list: bool
    retell_configured: bool
    conversation_engine: dict
