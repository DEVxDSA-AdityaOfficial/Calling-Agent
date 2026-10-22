import os
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

os.environ.update(
    DATABASE_URL="sqlite:///" + str(Path(__file__).parent / "test.db"),
    RETELL_API_KEY="key_test",
    RETELL_FROM_NUMBER="+14155550100",
    PUBLIC_BASE_URL="",
    ALLOWED_DESTINATION_NUMBERS="",
    OPENAI_API_KEY="sk-platform",
    ENCRYPTION_KEY=Fernet.generate_key().decode(),
    CONVERSATION_PROVIDER="openai",
    # Safety net: any provider call a test forgets to mock fails fast locally instead of reaching
    # the real API (port 9 = discard, nothing listens there).
    RETELL_BASE_URL="http://127.0.0.1:9",
    OPENAI_BASE_URL="http://127.0.0.1:9/v1",
    OPENAI_REALTIME_URL="ws://127.0.0.1:9/v1/realtime",
    SARVAM_BASE_URL="http://127.0.0.1:9",
    SARVAM_WS_URL="ws://127.0.0.1:9/ws",
    ELEVENLABS_BASE_URL="http://127.0.0.1:9",
    TWILIO_BASE_URL="http://127.0.0.1:9",
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeRetell:
    """Records requests and returns canned Retell responses."""

    def __init__(self):
        self.requests: list[tuple[str, object]] = []
        self.call_state: dict = {}
        self.fail_calls = False

    def create_llm(self, body):
        self.requests.append(("create_llm", body))
        return {"llm_id": "llm_1"}

    def update_llm(self, llm_id, body):
        self.requests.append(("update_llm", body))
        return {"llm_id": llm_id}

    def create_agent(self, body):
        self.requests.append(("create_agent", body))
        return {"agent_id": "ag_1", "version": 0}

    def update_agent(self, agent_id, body):
        self.requests.append(("update_agent", body))
        return {"agent_id": agent_id}

    def list_voices(self):
        return [{"voice_id": "retell-Cimo", "voice_name": "Cimo", "provider": "platform", "gender": "female"}]

    def create_phone_call(self, body):
        from app.retell_client import RetellError

        self.requests.append(("create_phone_call", body))
        if self.fail_calls:
            raise RetellError("Retell API 402: credit exhausted", 402)
        return {"call_id": "call_abc", "call_status": "registered", "to_number": body["to_number"]}

    def stop_call(self, call_id):
        self.requests.append(("stop_call", call_id))
        self.call_state = {"call_status": "ended", "disconnection_reason": "manual_stopped"}

    def get_call(self, call_id):
        self.requests.append(("get_call", call_id))
        return {"call_id": call_id, **self.call_state}


class FakeModel:
    """Scripted ConversationModel."""

    name = "Fake"

    def __init__(self):
        self.replies: list[str] = []
        self.json_replies: list[dict] = []
        self.seen: list[list[dict]] = []

    async def stream(self, messages):
        self.seen.append(messages)
        text = self.replies.pop(0) if self.replies else "Okay."
        for i in range(0, len(text), 4):  # stream in small chunks to exercise the END_CALL filter
            yield text[i : i + 4]

    async def complete(self, messages):
        self.seen.append(messages)
        return self.replies.pop(0) if self.replies else "Okay."

    async def complete_json(self, messages):
        self.seen.append(messages)
        return self.json_replies.pop(0)


@pytest.fixture()
def fake_retell():
    return FakeRetell()


@pytest.fixture()
def fake_model():
    return FakeModel()


@pytest.fixture()
def app_ctx(fake_retell, fake_model, monkeypatch):
    from app import deps
    from app.config import get_settings
    from app.db import Base, engine
    from app.routers import agents, calls, llm_ws, twilio_media

    from sqlalchemy import text

    from app import ratelimit

    get_settings.cache_clear()
    ratelimit.reset()
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    for module in (agents, calls, deps):
        monkeypatch.setattr(module, "retell_for_user", lambda db, user: fake_retell)
    from app.db import run_migrations

    run_migrations()
    for module in (agents, llm_ws, twilio_media):
        monkeypatch.setattr(module, "get_conversation_model", lambda db, user: fake_model)
    yield
    get_settings.cache_clear()


def _signup(client, email="owner@example.com"):
    r = client.post("/api/auth/signup", json={"name": "Owner", "email": email, "password": "correct-horse"})
    assert r.status_code == 201, r.text
    return r


@pytest.fixture()
def client(app_ctx):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        _signup(c)
        yield c


@pytest.fixture()
def anon_client(app_ctx):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
