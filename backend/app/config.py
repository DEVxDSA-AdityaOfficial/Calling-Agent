from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    # --- Platform defaults (users can override Retell/OpenAI in Settings -> API & Providers) ---
    retell_api_key: str = ""
    retell_base_url: str = "https://api.retellai.com"
    retell_from_number: str = ""

    # Conversation engine used by Custom Brain mode, the playbook generator and the simulator.
    conversation_provider: str = "openai"  # openai | local_slm
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4.1-mini"
    # Any OpenAI-compatible server (vLLM, Ollama, llama.cpp, TGI...) hosting your own model.
    local_slm_base_url: str = "http://localhost:11434/v1"
    local_slm_model: str = ""
    local_slm_api_key: str = ""

    # --- Speech / voice pipeline endpoints (overridable for mocks and regional deployments) ---
    sarvam_base_url: str = "https://api.sarvam.ai"
    sarvam_ws_url: str = "wss://api.sarvam.ai/speech-to-text-realtime/ws"
    openai_realtime_url: str = "wss://api.openai.com/v1/realtime"
    elevenlabs_base_url: str = "https://api.elevenlabs.io"
    elevenlabs_tts_model: str = "eleven_flash_v2_5"
    twilio_base_url: str = "https://api.twilio.com"
    stt_connect_timeout_s: float = 10.0
    stt_request_timeout_s: float = 30.0

    database_url: str = "postgresql+psycopg://calling_agent:calling_agent@localhost:5432/calling_agent"

    frontend_origin: str = "http://localhost:3000"
    public_base_url: str = ""

    # Fernet key(s) that encrypt provider credentials at rest. Comma-separated: the first key
    # encrypts, all keys decrypt (rotation). Generated into backend/.encryption_key on first run
    # if unset (development only; use a KMS/secret manager in production).
    encryption_key: str = ""
    auto_migrate: bool = True
    session_days: int = 14
    cookie_secure: bool = False
    allow_signup: bool = True

    allowed_destination_numbers: str = ""
    default_phone_region: str = "US"
    verify_webhook_signature: bool = True

    end_call_after_silence_ms: int = 30 * 1000

    @field_validator("public_base_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def allowed_numbers(self) -> set[str]:
        return {n.strip() for n in self.allowed_destination_numbers.split(",") if n.strip()}

    @property
    def webhook_url(self) -> str | None:
        return f"{self.public_base_url}/api/webhooks/retell" if self.public_base_url else None

    @property
    def websocket_base_url(self) -> str | None:
        if not self.public_base_url:
            return None
        return self.public_base_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
