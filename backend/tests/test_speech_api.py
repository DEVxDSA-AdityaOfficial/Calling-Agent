import asyncio
import base64
import json

import pytest

from app.speech.base import STTAuthError, TranscriptionResult

AGENT = {
    "name": "Maya", "business_name": "RecursX", "objective": "Book a demo",
    "script": "Call restaurant owners on behalf of RecursX, explain AI ordering and offer a demo.",
    "language": "hinglish", "voice_id": "el-voice-1", "tone": "friendly", "max_duration_minutes": 3,
}


@pytest.fixture()
def stt_ok(monkeypatch):
    """Make speech health checks succeed without network."""
    from app.speech.router import PROVIDERS

    async def ok(self, key, cfg):
        return f"ok {cfg.model} {key[-4:]}"

    for p in PROVIDERS.values():
        monkeypatch.setattr(type(p), "health_check", ok)


@pytest.fixture()
def other_tests_ok(monkeypatch):
    from app import providers

    for pid in ("twilio", "elevenlabs", "retell"):
        monkeypatch.setitem(providers._TESTS, pid, lambda v: "ok")


def connect(client, pid, **values):
    r = client.put(f"/api/providers/{pid}", json={"values": values})
    assert r.status_code == 200, r.text
    return r.json()


def test_speech_provider_config_validation_and_masking(client, stt_ok):
    caps = client.get("/api/speech/providers").json()
    assert {c["id"] for c in caps} == {"whisper", "sarvam"}
    assert any(m["id"] == "saaras:v4" for m in next(c for c in caps if c["id"] == "sarvam")["models"])

    out = connect(client, "sarvam", api_key="sk_sarvam_live_9876", model="saaras:v4", language="hi-IN", mode="codemix")
    assert out["status"] == "connected" and out["status_detail"] == "ok saaras:v4 9876"
    fields = {f["key"]: f for f in out["fields"]}
    assert fields["api_key"]["value"].endswith("9876") and "sarvam_live" not in fields["api_key"]["value"]
    assert fields["model"]["kind"] == "select" and {"value": "saaras:v4", "label": "Saaras v4 (recommended)"} in fields["model"]["options"]

    bad = client.put("/api/providers/sarvam", json={"values": {"model": "gpt-4"}})
    assert bad.status_code == 422 and "supported option" in bad.json()["detail"]
    listing = json.dumps(client.get("/api/providers").json())
    assert "sk_sarvam_live_9876" not in listing  # secrets never returned


def test_whisper_reuses_openai_key(client, stt_ok):
    connect(client, "openai", api_key="sk-openai-shared-1111")
    out = client.post("/api/providers/whisper/test").json()
    assert out["status"] == "connected" and out["status_detail"].endswith("1111")


def test_safe_credential_replacement(client, monkeypatch):
    from app.speech.router import PROVIDERS

    async def check(self, key, cfg):
        if key != "sk_good_key_0001":
            raise STTAuthError("Sarvam rejected the API key.")
        return "ok"

    monkeypatch.setattr(type(PROVIDERS["sarvam"]), "health_check", check)
    assert connect(client, "sarvam", api_key="sk_good_key_0001")["status"] == "connected"
    r = client.put("/api/providers/sarvam", json={"values": {"api_key": "sk_bad_key_0002"}})
    assert r.status_code == 422 and "existing ones were kept" in r.json()["detail"]
    assert "sk_bad_key_0002" not in r.text
    still = next(p for p in client.get("/api/providers").json() if p["id"] == "sarvam")
    assert still["status"] == "connected" and next(f for f in still["fields"] if f["key"] == "api_key")["value"].endswith("0001")


def test_default_provider_agent_override_and_tenant_isolation(client, anon_client, stt_ok, other_tests_ok):
    from app.db import SessionLocal
    from app.models import Agent, User
    from app.speech.base import STTConfigError
    from app.speech.router import resolve_fallback, resolve_speech

    connect(client, "sarvam", api_key="sk_sarvam_aaaa1111")
    connect(client, "whisper", api_key="sk-whisper-bbbb2222")
    agent_id = client.post("/api/agents", json={**AGENT, "mode": "managed"}).json()["id"]

    with SessionLocal() as db:
        user, agent = db.query(User).one(), db.get(Agent, agent_id)
        with pytest.raises(STTConfigError, match="No speech-to-text provider"):
            resolve_speech(db, user, agent)

    assert client.put("/api/speech/settings", json={"default_provider": "whisper"}).json()["default_provider"] == "whisper"
    with SessionLocal() as db:
        user, agent = db.query(User).one(), db.get(Agent, agent_id)
        r = resolve_speech(db, user, agent)
        assert (r.provider.id, r.source, r.config.model) == ("whisper", "default", "gpt-realtime-whisper")
        agent.stt_provider = "sarvam"
        db.commit()
        r = resolve_speech(db, user, agent)
        assert (r.provider.id, r.source, r.config.mode) == ("sarvam", "agent", "codemix")  # agent wins
        assert resolve_fallback(db, user, agent, "sarvam") is None  # fallback is opt-in

    client.put("/api/speech/settings", json={"default_provider": "whisper", "fallback_enabled": True})
    with SessionLocal() as db:
        user, agent = db.query(User).one(), db.get(Agent, agent_id)
        assert resolve_fallback(db, user, agent, "sarvam").provider.id == "whisper"

    assert client.put("/api/speech/settings", json={"default_provider": "deepgram"}).status_code == 422

    anon_client.post("/api/auth/signup", json={"name": "B", "email": "b@example.com", "password": "long-enough"})
    other = anon_client.get("/api/speech/settings").json()
    assert other["default_provider"] is None and other["connected"] == {"whisper": False, "sarvam": False}
    assert all(p["status"] == "not_configured" for p in anon_client.get("/api/providers").json())


def test_connection_tests_are_rate_limited(client, stt_ok):
    connect(client, "sarvam", api_key="sk_sarvam_aaaa1111")
    codes = [client.post("/api/providers/sarvam/test").status_code for _ in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429


def test_test_transcription_endpoint(client, stt_ok, monkeypatch):
    from app.speech.router import PROVIDERS

    connect(client, "sarvam", api_key="sk_sarvam_aaaa1111")

    async def fake(self, key, audio, *, filename, content_type, config):
        assert content_type == "audio/webm" and audio == b"webmdata"
        return TranscriptionResult("नमस्ते", "sarvam", "saaras:v4", "completed", language="hi-IN", latency_ms=420)

    monkeypatch.setattr(type(PROVIDERS["sarvam"]), "transcribe", fake)
    r = client.post("/api/speech/test-transcription", data={"provider": "sarvam"}, files={"audio": ("c.webm", b"webmdata", "audio/webm")})
    assert r.status_code == 200 and r.json()["text"] == "नमस्ते" and r.json()["latency_ms"] == 420
    assert client.post("/api/speech/test-transcription", data={"provider": "sarvam"},
                       files={"audio": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 415
    from app.config import get_settings

    monkeypatch.setenv("OPENAI_API_KEY", "")  # no platform key for Whisper to fall back to
    get_settings.cache_clear()
    assert client.post("/api/speech/test-transcription", data={"provider": "whisper"},
                       files={"audio": ("c.webm", b"x", "audio/webm")}).status_code == 409


def test_encryption_key_rotation(client, stt_ok, monkeypatch):
    from cryptography.fernet import Fernet

    from app import cli, security
    from app.config import get_settings
    from app.db import SessionLocal
    from app.models import ProviderCredential
    from app.providers import credential_values

    connect(client, "sarvam", api_key="sk_sarvam_rotate_77")
    old = get_settings().encryption_key
    monkeypatch.setenv("ENCRYPTION_KEY", f"{Fernet.generate_key().decode()},{old}")
    get_settings.cache_clear()
    security.reset_fernet()
    assert cli.rotate_keys() == 1
    new_only = get_settings().encryption_key.split(",")[0]
    monkeypatch.setenv("ENCRYPTION_KEY", new_only)  # old key retired
    get_settings.cache_clear()
    security.reset_fernet()
    with SessionLocal() as db:
        cred = db.query(ProviderCredential).one()
        assert credential_values(cred)["api_key"] == "sk_sarvam_rotate_77" and cred.secrets_rotated_at
    security.reset_fernet()


def test_migrations_match_models():
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine

    from app.db import Base, run_migrations

    engine = create_engine("sqlite://")
    run_migrations(engine)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


# --- Twilio + Custom Brain calls ---
class FakeTwilio:
    calls: list = []
    hangups: list = []

    def __init__(self, sid, token):
        self.sid, self.token = sid, token

    def create_call(self, **kw):
        FakeTwilio.calls.append(kw)
        return {"sid": "CA123", "status": "queued"}

    def hangup(self, sid):
        FakeTwilio.hangups.append(sid)
        return {}


@pytest.fixture()
def direct_setup(client, stt_ok, other_tests_ok, monkeypatch):
    from app.config import get_settings
    from app.routers import calls, twilio_media

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://abc.ngrok.app")
    get_settings.cache_clear()
    FakeTwilio.calls, FakeTwilio.hangups = [], []
    monkeypatch.setattr(calls, "TwilioClient", FakeTwilio)
    monkeypatch.setattr(twilio_media, "TwilioClient", FakeTwilio)
    return client


def test_direct_agent_readiness_and_call_placement(direct_setup):
    client = direct_setup
    agent = client.post("/api/agents", json={**AGENT, "mode": "direct", "stt_provider": "sarvam"}).json()
    assert agent["sync_status"] == "error" and "Twilio" in agent["sync_error"]

    connect(client, "twilio", account_sid="AC" + "1" * 32, auth_token="twilio-token-xyz", from_number="+14155550100")
    connect(client, "elevenlabs", api_key="sk_el_key_abcd1234")
    agent = client.post(f"/api/agents/{agent['id']}/sync").json()
    assert "Sarvam AI isn't connected" in agent["sync_error"]
    connect(client, "sarvam", api_key="sk_sarvam_aaaa1111")
    agent = client.post(f"/api/agents/{agent['id']}/sync").json()
    assert agent["sync_status"] == "synced" and "[END_CALL]" in agent["generated_prompt"]

    r = client.post("/api/calls", json={"agent_id": agent["id"], "to_number": "+1 415 555 0123", "customer_name": "Rohan", "consent_confirmed": True})
    assert r.status_code == 201, r.text
    call = r.json()
    assert call["mode"] == "direct" and call["stt_provider"] == "sarvam" and call["twilio_call_sid"] == "CA123"
    assert call["diagnostics"]["stt"]["model"] == "saaras:v4" and call["diagnostics"]["stt"]["source"] == "agent"
    placed = FakeTwilio.calls[0]
    assert placed["to"] == "+14155550123" and placed["from_"] == "+14155550100"
    assert '<Stream url="wss://abc.ngrok.app/api/twilio/media/' in placed["twiml"]
    assert placed["status_callback"].startswith("https://abc.ngrok.app/api/twilio/status/")


def _place_direct_call(client):
    connect(client, "twilio", account_sid="AC" + "1" * 32, auth_token="twilio-token-xyz", from_number="+14155550100")
    connect(client, "elevenlabs", api_key="sk_el_key_abcd1234")
    connect(client, "whisper", api_key="sk-whisper-bbbb2222")
    client.put("/api/speech/settings", json={"default_provider": "whisper"})
    agent = client.post("/api/agents", json={**AGENT, "mode": "direct"}).json()
    call = client.post("/api/calls", json={"agent_id": agent["id"], "to_number": "+14155550123", "customer_name": "Rohan", "consent_confirmed": True}).json()
    token = FakeTwilio.calls[-1]["status_callback"].rsplit("/", 1)[1]
    return agent, call, token


def test_twilio_status_callback_signature(direct_setup):
    from app.telephony.twilio import compute_signature

    client = direct_setup
    _, call, token = _place_direct_call(client)
    url = f"https://abc.ngrok.app/api/twilio/status/{token}"
    params = {"CallSid": "CA123", "CallStatus": "no-answer", "CallDuration": "0"}
    assert client.post(f"/api/twilio/status/{token}", data=params, headers={"X-Twilio-Signature": "bad"}).status_code == 403
    sig = compute_signature(url, params, "twilio-token-xyz")
    assert client.post(f"/api/twilio/status/{token}", data=params, headers={"X-Twilio-Signature": sig}).status_code == 204
    detail = client.get(f"/api/calls/{call['id']}").json()
    assert detail["status"] == "failed" and detail["goal_status"] == "no_response"


def test_media_stream_end_to_end(direct_setup, fake_model, monkeypatch):
    """Twilio WS -> (fake) Whisper stream -> existing conversation engine -> (fake) ElevenLabs -> Twilio."""
    from app.routers import twilio_media
    from app.speech.base import TranscriptEvent
    from app.speech.router import PROVIDERS
    from app.telephony.twilio import compute_signature

    client = direct_setup
    agent, call, token = _place_direct_call(client)
    opened = []

    class FakeStream:
        provider = "whisper"

        def __init__(self, key, cfg, on_event):
            self.key, self.cfg, self.on_event, self.audio, self.closed = key, cfg, on_event, [], False
            opened.append(self)

        async def start(self):
            pass

        async def send_audio(self, chunk):
            self.audio.append(chunk)
            if len(self.audio) == 3:
                await self.on_event(TranscriptEvent("final", "whisper", text="Price kya hai?", segment_id="item1", latency_ms=300))
                await self.on_event(TranscriptEvent("final", "whisper", text="Price kya hai?", segment_id="item1"))  # duplicate

        async def close(self):
            self.closed = True

    monkeypatch.setattr(type(PROVIDERS["whisper"]), "open_stream", lambda self, key, cfg, cb: FakeStream(key, cfg, cb))

    class FakeTTS:
        def __init__(self, key, voice, language=None):
            assert key == "sk_el_key_abcd1234" and voice == "el-voice-1" and language == "hi"

        async def stream(self, text):
            yield b"\x7f" * 160

    monkeypatch.setattr(twilio_media, "ElevenLabsTTS", FakeTTS)
    fake_model.replies = [
        "Namaste! Main Maya, RecursX ki AI assistant. Kya abhi baat kar sakte hain?",  # generated greeting
        "Bas 2,499 rupees mahina. Dhanyavaad, goodbye! [END_CALL]",
    ]

    def read_turn(ws, n_marks):
        """Read Twilio-bound messages until `n_marks` marks (one per spoken sentence) arrive."""
        msgs, marks = [], []
        while len(marks) < n_marks:
            m = ws.receive_json()
            msgs.append(m)
            if m["event"] == "mark":
                marks.append(m["mark"]["name"])
        return msgs, marks

    with client.websocket_connect(f"/api/twilio/media/{token}") as ws:
        ws.send_json({"event": "connected", "protocol": "Call", "version": "1.0.0"})
        ws.send_json({"event": "start", "streamSid": "MZ9", "start": {"streamSid": "MZ9", "callSid": "CA123",
                      "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1}}})
        # Greeting is generated (Hinglish agents have no fixed opening) and spoken sentence by sentence.
        out, greeting_marks = read_turn(ws, 3)
        assert [m["event"] for m in out].count("media") == 3
        for name in greeting_marks:
            ws.send_json({"event": "mark", "streamSid": "MZ9", "mark": {"name": name}})
        for i in range(3):
            ws.send_json({"event": "media", "streamSid": "MZ9", "media": {"track": "inbound", "payload": base64.b64encode(b"\xff" * 160).decode()}})
        answer, marks = read_turn(ws, 2)
        out += answer
        assert all(m["streamSid"] == "MZ9" for m in out)
        for name in marks:
            ws.send_json({"event": "mark", "streamSid": "MZ9", "mark": {"name": name}})
        import time

        deadline = time.time() + 2
        while not FakeTwilio.hangups and time.time() < deadline:
            time.sleep(0.05)
        ws.send_json({"event": "stop", "streamSid": "MZ9", "stop": {"callSid": "CA123"}})

    assert FakeTwilio.hangups == ["CA123"]  # END_CALL hung up via Twilio REST after the goodbye played
    stream = opened[0]
    assert stream.key == "sk-whisper-bbbb2222" and stream.cfg.model == "gpt-realtime-whisper" and stream.closed
    assert stream.audio[0] == b"\xff" * 160
    # The STT transcript reached the existing conversation engine exactly once.
    user_turns = [m for m in fake_model.seen[-1] if m["role"] == "user" and m["content"] == "Price kya hai?"]
    assert len(user_turns) == 1

    detail = client.get(f"/api/calls/{call['id']}").json()
    assert detail["status"] == "in_progress" and detail["stt_provider"] == "whisper"
    assert [t["role"] for t in detail["transcript_object"]] == ["agent", "user", "agent"]
    assert detail["transcript_object"][2]["content"] == "Bas 2,499 rupees mahina. Dhanyavaad, goodbye!"
    assert detail["diagnostics"]["duplicates_suppressed"] == 1 and detail["diagnostics"]["avg_stt_latency_ms"] == 300
    assert detail["diagnostics"]["stt"]["source"] == "default"  # why it was chosen, not "pinned"

    # Twilio reports completion -> post-call analysis with the conversation model.
    fake_model.json_replies.append({"call_summary": "Asked price.", "user_sentiment": "Neutral", "call_successful": False,
                                    "call_outcome": "interested_follow_up", "customer_interest": "medium", "follow_up_requested": True})
    params = {"CallSid": "CA123", "CallStatus": "completed", "CallDuration": "42"}
    sig = compute_signature(f"https://abc.ngrok.app/api/twilio/status/{token}", params, "twilio-token-xyz")
    assert client.post(f"/api/twilio/status/{token}", data=params, headers={"X-Twilio-Signature": sig}).status_code == 204
    detail = client.get(f"/api/calls/{call['id']}").json()
    assert detail["status"] == "completed" and detail["duration_ms"] == 42_000
    assert detail["summary"] == "Asked price." and detail["goal_status"] == "follow_up"


def test_media_stream_rejects_unknown_token(direct_setup):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with direct_setup.websocket_connect("/api/twilio/media/not-a-token") as ws:
            ws.receive_json()


def test_managed_mode_unaffected_by_speech_settings(client, fake_retell, stt_ok):
    connect(client, "sarvam", api_key="sk_sarvam_aaaa1111")
    client.put("/api/speech/settings", json={"default_provider": "sarvam"})
    agent = client.post("/api/agents", json={**AGENT, "language": "en-US", "mode": "managed"}).json()
    assert agent["sync_status"] == "synced" and agent["stt_provider"] is None
    call = client.post("/api/calls", json={"agent_id": agent["id"], "to_number": "+14155550123", "consent_confirmed": True}).json()
    assert call["mode"] == "managed" and call["stt_provider"] is None and call["retell_call_id"] == "call_abc"


def test_direct_call_ended_before_conversation(direct_setup):
    client = direct_setup
    _, call, _ = _place_direct_call(client)
    r = client.post(f"/api/calls/{call['id']}/end").json()
    assert FakeTwilio.hangups == ["CA123"]
    assert r["status"] == "completed" and r["outcome"] == "no_meaningful_conversation" and r["goal_status"] == "no_response"


def test_select_fields_list_the_default_first():
    """The settings form pre-selects the first option, so it must be each provider's default."""
    from app.providers import PROVIDERS
    from app.speech.router import PROVIDERS as STT

    for pid in ("whisper", "sarvam"):
        defaults = STT[pid].capabilities()["defaults"]
        for f in PROVIDERS[pid].fields:
            if f.kind == "select" and f.key in defaults:
                assert f.options[0][0] == defaults[f.key], (pid, f.key)


def test_unexpected_start_error_marks_call_failed(direct_setup, monkeypatch):
    client = direct_setup
    _place_direct_call(client)  # sets up providers + agent

    def boom(self, **kw):
        raise TypeError("encoder blew up")

    monkeypatch.setattr(FakeTwilio, "create_call", boom)
    agent_id = client.get("/api/agents").json()[0]["id"]
    r = client.post("/api/calls", json={"agent_id": agent_id, "to_number": "+14155550123", "consent_confirmed": True})
    assert r.status_code == 502 and "encoder" not in r.text
    latest = client.get("/api/calls").json()[0]
    assert latest["status"] == "failed" and latest["goal_status"] == "failed"
