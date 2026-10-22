import hashlib
import hmac
import json
import time

from app.call_sync import map_status
from app.conversation.brain import EndCallFilter, split_end_call
from app.retell_client import verify_webhook_signature

AGENT = {
    "name": "Maya",
    "business_name": "RecursX",
    "objective": "Book a product demo",
    "target_audience": "Restaurant owners in Indore",
    "success_condition": "Customer shares a preferred time for a demo",
    "fallback_behavior": "Thank them and close politely",
    "max_duration_minutes": 3,
    "script": "Call potential customers on behalf of RecursX. Introduce our AI automation services, "
    "understand their business requirements, explain our offering, and ask whether they would like a demo.",
    "additional_context": "AI Ordering Agent costs 2,499 rupees per month. Supports WhatsApp and voice ordering.",
    "dos_and_donts": "Don't invent discounts. Don't promise unsupported features.",
    "language": "en-US",
    "voice_id": "retell-Cimo",
    "tone": "consultative",
}


def _create_agent(client, **overrides):
    r = client.post("/api/agents", json={**AGENT, **overrides})
    assert r.status_code == 201, r.text
    return r.json()


def _sign(body: str, key="key_test"):
    ts = str(int(time.time() * 1000))
    return f"v={ts},d=" + hmac.new(key.encode(), (body + ts).encode(), hashlib.sha256).hexdigest()


def _start_call(client, agent, **extra):
    r = client.post(
        "/api/calls",
        json={"agent_id": agent["id"], "to_number": "+1 (415) 555-0123", "consent_confirmed": True, **extra},
    )
    assert r.status_code == 201, r.text
    return r.json()


# --- Auth & isolation ---
def test_auth_flow(anon_client):
    c = anon_client
    assert c.get("/api/agents").status_code == 401
    assert c.post("/api/auth/signup", json={"name": "A", "email": "a@example.com", "password": "short"}).status_code == 422
    assert c.post("/api/auth/signup", json={"name": "A", "email": "a@example.com", "password": "long-enough"}).status_code == 201
    assert c.get("/api/auth/me").json()["email"] == "a@example.com"
    assert c.post("/api/auth/signup", json={"name": "A", "email": "A@example.com", "password": "long-enough"}).status_code == 409
    c.post("/api/auth/logout")
    assert c.get("/api/auth/me").status_code == 401
    assert c.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong-pass"}).status_code == 401
    assert c.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrong-pass"}).status_code == 401
    assert c.post("/api/auth/login", json={"email": "A@example.com", "password": "long-enough"}).status_code == 200
    assert c.get("/api/auth/me").status_code == 200


def test_users_cannot_see_each_others_data(client, anon_client):
    agent = _create_agent(client)
    call = _start_call(client, agent)
    anon_client.post("/api/auth/signup", json={"name": "B", "email": "b@example.com", "password": "long-enough"})
    assert anon_client.get(f"/api/agents/{agent['id']}").status_code == 404
    assert anon_client.get(f"/api/calls/{call['id']}").status_code == 404
    assert anon_client.get("/api/calls").json() == []
    assert anon_client.post("/api/calls", json={"agent_id": agent["id"], "to_number": "+14155550123", "consent_confirmed": True}).status_code == 404


# --- Providers ---
def test_provider_credentials_are_encrypted_and_masked(client, monkeypatch):
    r = client.put("/api/providers/retell", json={"values": {"api_key": "key_user_secret_1234", "from_number": "+14155550111"}})
    assert r.status_code == 200
    fields = {f["key"]: f["value"] for f in r.json()["fields"]}
    assert fields["api_key"].endswith("1234") and "secret" not in fields["api_key"]
    assert fields["from_number"] == "+14155550111"

    from app.db import SessionLocal
    from app.models import ProviderCredential

    with SessionLocal() as db:
        raw = db.query(ProviderCredential).one().secrets_encrypted
    assert "key_user_secret" not in raw

    # Saving the masked value back keeps the stored secret.
    client.put("/api/providers/retell", json={"values": {"api_key": fields["api_key"], "from_number": "+14155550111"}})
    from app.providers import credential_values

    with SessionLocal() as db:
        assert credential_values(db.query(ProviderCredential).one())["api_key"] == "key_user_secret_1234"

    from app import providers

    monkeypatch.setitem(providers._TESTS, "retell", lambda v: f"ok {v['api_key'][-4:]}")
    tested = client.post("/api/providers/retell/test").json()
    assert tested["status"] == "connected" and tested["status_detail"] == "ok 1234"
    assert client.get("/api/options").json()["from_number"] == "+14155550111"

    monkeypatch.setitem(providers._TESTS, "twilio", lambda v: (_ for _ in ()).throw(ValueError("bad creds")))
    client.put("/api/providers/twilio", json={"values": {"account_sid": "AC1", "auth_token": "tok"}})
    assert client.post("/api/providers/twilio/test").json()["status"] == "error"
    assert client.delete("/api/providers/twilio").json()["status"] == "not_configured"


# --- Agents ---
def test_managed_agent_builds_goal_prompt_and_syncs(client, fake_retell):
    agent = _create_agent(client)
    assert agent["sync_status"] == "synced" and agent["mode"] == "managed"
    prompt = agent["generated_prompt"]
    for expected in ("Book a product demo", "Restaurant owners in Indore", "2,499 rupees", "Don't invent discounts", "AI assistant"):
        assert expected in prompt
    assert "end_call tool" in prompt

    assert [k for k, _ in fake_retell.requests] == ["create_llm", "create_agent"]
    agent_body = fake_retell.requests[1][1]
    assert agent_body["response_engine"] == {"type": "retell-llm", "llm_id": "llm_1"}
    assert agent_body["max_call_duration_ms"] == 4 * 60_000
    names = {d["name"] for d in agent_body["post_call_analysis_data"]}
    assert {"call_outcome", "primary_objection", "unanswered_questions", "next_action"} <= names
    assert "webhook_url" not in agent_body


def test_custom_brain_requires_public_url(client, fake_retell, monkeypatch):
    agent = _create_agent(client, mode="custom_brain")
    assert agent["sync_status"] == "error" and "PUBLIC_BASE_URL" in agent["sync_error"]

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://abc.ngrok.app/")
    from app.config import get_settings

    get_settings.cache_clear()
    agent = client.post(f"/api/agents/{agent['id']}/sync").json()
    assert agent["sync_status"] == "synced"
    body = fake_retell.requests[-1][1]
    assert body["response_engine"]["type"] == "custom-llm"
    assert body["response_engine"]["llm_websocket_url"].startswith("wss://abc.ngrok.app/api/llm-ws/")
    assert "transcript_updated" in body["webhook_events"]
    assert "[END_CALL]" in agent["generated_prompt"]
    assert not any(k in ("create_llm", "update_llm") for k, _ in fake_retell.requests)


def test_hinglish_agent(client, fake_retell):
    agent = _create_agent(client, language="hinglish")
    assert fake_retell.requests[1][1]["language"] == ["hi-IN", "en-IN"]
    assert "Hinglish" in agent["generated_prompt"]
    assert agent["begin_message"] is None  # greeting generated in-language


def test_playbook_generation_and_use(client, fake_model):
    fake_model.json_replies.append(
        {
            "opening": "Hello! Main Maya, RecursX ki AI assistant.",
            "qualification_questions": ["Aap orders kaise lete hain?", ""],
            "value_points": "Handles WhatsApp orders automatically",
            "objections": [{"objection": "We already have a system", "response": "Does it handle calls too?"}, {"bad": 1}],
            "follow_up_questions": [],
            "closing_strategy": "Ask for a demo time",
            "success_criteria": ["Preferred demo time collected"],
        }
    )
    r = client.post("/api/agents/playbook", json=AGENT)
    assert r.status_code == 200, r.text
    playbook = r.json()
    assert playbook["qualification_questions"] == ["Aap orders kaise lete hain?"]
    assert playbook["value_points"] == ["Handles WhatsApp orders automatically"]
    assert len(playbook["objections"]) == 1
    assert "2,499 rupees" in fake_model.seen[-1][1]["content"]

    agent = _create_agent(client, playbook=playbook)
    assert "We already have a system" in agent["generated_prompt"]
    assert agent["playbook"]["closing_strategy"] == "Ask for a demo time"


def test_simulator(client, fake_model):
    agent = _create_agent(client)
    r = client.post(f"/api/agents/{agent['id']}/simulate/turn", json={"persona": "price_sensitive", "history": []})
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["turns"][0]["role"] == "agent" and "AI assistant" in first["turns"][0]["content"]
    assert "Hello!" in first["turns"][0]["content"]  # {{greeting}} rendered

    history = first["turns"]
    fake_model.replies = ["It's 2,499 rupees a month. Shall we book a demo? Goodbye! [END_CALL]"]
    second = client.post(f"/api/agents/{agent['id']}/simulate/turn", json={"persona": "price_sensitive", "history": history}).json()
    assert second["ended"] and second["ended_by"] == "agent"
    assert "[END_CALL]" not in second["turns"][0]["content"]

    fake_model.json_replies.append({"scores": {"script_adherence": 9, "conversation_quality": "4"}, "goal_achieved": True, "improvements": ["Ask about volume"]})
    ev = client.post(f"/api/agents/{agent['id']}/simulate/evaluate", json={"persona": "price_sensitive", "history": history + second["turns"]}).json()
    assert ev["scores"]["script_adherence"] == 5 and ev["scores"]["conversation_quality"] == 4
    assert ev["scores"]["goal_achievement"] is None and ev["goal_achieved"] is True
    assert client.post(f"/api/agents/{agent['id']}/simulate/turn", json={"persona": "alien", "history": []}).status_code == 422


# --- Calls ---
def test_call_lifecycle_via_webhooks(client, fake_retell):
    agent = _create_agent(client)
    call = _start_call(client, agent, customer_name="Sam")
    assert call["status"] == "ringing" and call["to_number"] == "+14155550123"
    sent = fake_retell.requests[-1][1]
    assert sent["override_agent_id"] == "ag_1" and sent["from_number"] == "+14155550100"
    assert sent["retell_llm_dynamic_variables"]["customer_name"] == "Sam"

    def hook(event, **fields):
        body = json.dumps({"event": event, "call": {"call_id": "call_abc", **fields}})
        resp = client.post("/api/webhooks/retell", content=body, headers={"x-retell-signature": _sign(body)})
        assert resp.status_code == 204, resp.text

    hook("call_started", call_status="ongoing", start_timestamp=1_700_000_000_000)
    hook("transcript_updated", call_status="ongoing", transcript_object=[{"role": "agent", "content": "Hi Sam"}])
    live = client.get(f"/api/calls/{call['id']}").json()
    assert live["status"] == "in_progress" and live["transcript_object"] == [{"role": "agent", "content": "Hi Sam"}]

    hook(
        "call_ended", call_status="ended", disconnection_reason="agent_hangup",
        start_timestamp=1_700_000_000_000, end_timestamp=1_700_000_095_000, duration_ms=95_000,
        transcript="Agent: Hi\nUser: Hello", transcript_object=[{"role": "agent", "content": "Hi", "words": []}],
    )
    hook("call_started", call_status="ongoing")  # late duplicate must not resurrect the call
    hook(
        "call_analyzed", call_status="ended", disconnection_reason="agent_hangup",
        call_analysis={
            "call_summary": "Sam wants a demo.", "user_sentiment": "Positive", "call_successful": True,
            "custom_analysis_data": {
                "call_outcome": "goal_achieved", "customer_interest": "high", "follow_up_requested": "true",
                "appointment_preference": "Thursday 3pm", "primary_objection": "Existing software",
                "next_action": "Send integration details",
            },
        },
    )
    detail = client.get(f"/api/calls/{call['id']}").json()
    assert detail["status"] == "completed" and detail["goal_status"] == "goal_achieved"
    assert detail["duration_ms"] == 95_000 and detail["follow_up_requested"] is True
    assert detail["appointment_preference"] == "Thursday 3pm"
    assert detail["primary_objection"] == "Existing software"
    assert detail["transcript_object"] == [{"role": "agent", "content": "Hi"}]

    stats = client.get("/api/calls/stats").json()
    assert stats == {**stats, "total_calls": 1, "completed": 1, "interested": 1, "goal_achieved": 1, "avg_duration_ms": 95_000}
    assert client.get("/api/calls?goal_status=goal_achieved").json()[0]["agent_name"] == "Maya"


def test_webhook_rejects_bad_signature(client):
    agent = _create_agent(client)
    _start_call(client, agent)
    body = json.dumps({"event": "call_started", "call": {"call_id": "call_abc"}})
    r = client.post("/api/webhooks/retell", content=body, headers={"x-retell-signature": "v=1,d=bad"})
    assert r.status_code == 401


def test_polling_fallback_and_no_response_goal(client, fake_retell):
    agent = _create_agent(client)
    call = _start_call(client, agent)
    fake_retell.call_state = {"call_status": "ended", "disconnection_reason": "dial_no_answer"}
    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:  # pretend the last sync was a while ago
        db.get(models.Call, call["id"]).last_synced_at = None
        db.commit()
    detail = client.get(f"/api/calls/{call['id']}").json()
    assert detail["status"] == "failed" and detail["outcome"] == "no_answer" and detail["goal_status"] == "no_response"


def test_end_call(client, fake_retell):
    agent = _create_agent(client)
    call = _start_call(client, agent)
    r = client.post(f"/api/calls/{call['id']}/end")
    assert r.status_code == 200 and r.json()["status"] == "completed"
    assert ("stop_call", "call_abc") in fake_retell.requests
    assert client.post(f"/api/calls/{call['id']}/end").status_code == 409


def test_call_guards(client, fake_retell, monkeypatch):
    agent = _create_agent(client)
    base = {"agent_id": agent["id"], "to_number": "+14155550123", "consent_confirmed": True}
    assert client.post("/api/calls", json={**base, "consent_confirmed": False}).status_code == 422
    assert client.post("/api/calls", json={**base, "to_number": "12345"}).status_code == 422

    monkeypatch.setenv("ALLOWED_DESTINATION_NUMBERS", "+14155550199")
    from app.config import get_settings

    get_settings.cache_clear()
    assert client.post("/api/calls", json=base).status_code == 403
    monkeypatch.delenv("ALLOWED_DESTINATION_NUMBERS")
    get_settings.cache_clear()

    fake_retell.fail_calls = True
    assert client.post("/api/calls", json=base).status_code == 502
    failed = client.get("/api/calls").json()[0]
    assert failed["status"] == "failed" and failed["goal_status"] == "failed"


# --- Custom Brain WebSocket ---
def test_custom_brain_websocket(client, fake_model, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://abc.ngrok.app")
    from app.config import get_settings
    from app.db import SessionLocal
    from app.models import Agent

    get_settings.cache_clear()
    agent = _create_agent(client, mode="custom_brain")
    _start_call(client, agent, customer_name="Sam")
    with SessionLocal() as db:
        token = db.get(Agent, agent["id"]).ws_token

    with client.websocket_connect(f"/api/llm-ws/{token}/call_abc") as ws:
        assert ws.receive_json()["response_type"] == "config"
        ws.send_json({"interaction_type": "call_details", "call": {"retell_llm_dynamic_variables": {"customer_name": "Sam", "greeting": "Hi, is this Sam?"}}})
        begin = ws.receive_json()
        assert begin["response_id"] == 0 and begin["content"].startswith("Hi, is this Sam?")

        fake_model.replies = ["Great talking to you, Sam. Goodbye! [END_CALL]"]
        transcript = [{"role": "agent", "content": begin["content"]}, {"role": "user", "content": "Not interested, bye."}]
        ws.send_json({"interaction_type": "response_required", "response_id": 1, "transcript": transcript})
        spoken, final = "", None
        while final is None:
            msg = ws.receive_json()
            spoken += msg["content"]
            if msg["content_complete"]:
                final = msg
        assert final["end_call"] is True and "[END" not in spoken and "Goodbye!" in spoken
        system = fake_model.seen[-1][0]["content"]
        assert "The person you are calling is Sam" in system  # dynamic variables rendered for our model

    live = client.get("/api/calls").json()[0]
    assert live["status"] == "in_progress"

    # Bad token or unknown call is rejected.
    from starlette.websockets import WebSocketDisconnect

    import pytest

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/llm-ws/wrong/call_abc") as ws:
            ws.receive_json()


# --- Helpers ---
def test_end_call_filter_and_helpers():
    f = EndCallFilter()
    out = "".join(f.feed(c) for c in ["Bye", " now [", "END_", "CALL]", " extra"]) + f.flush()
    assert out == "Bye now " and f.ended
    f = EndCallFilter()
    assert f.feed("Price is [5]") + f.flush() == "Price is [5]" and not f.ended
    assert split_end_call("Thanks! [END_CALL]") == ("Thanks!", True)

    body = '{"a":1}'
    assert verify_webhook_signature(body, _sign(body), "key_test")
    assert not verify_webhook_signature(body, _sign(body, "other"), "key_test")
    assert not verify_webhook_signature(body, "v=1000,d=abc", "key_test")  # stale
    assert map_status("ended", "user_hangup") == "completed"
    assert map_status("ended", "dial_busy") == "failed"
    assert map_status("ended", "error_asr") == "failed"
    assert map_status("not_connected", None) == "failed"


def test_call_unknown_to_retell_is_marked_failed(client, fake_retell):
    from app.retell_client import RetellError

    agent = _create_agent(client)
    call = _start_call(client, agent)

    def gone(_):
        raise RetellError("Retell API 404: Call not found", 404)

    fake_retell.stop_call = gone
    r = client.post(f"/api/calls/{call['id']}/end")
    assert r.status_code == 200 and r.json()["status"] == "failed"
    assert "no record" in r.json()["error"]
