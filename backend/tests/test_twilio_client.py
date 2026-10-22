"""Contract tests for the real TwilioClient (HTTP mocked) and TwiML/signature helpers."""

import functools
from urllib.parse import parse_qs

import httpx
import pytest

from app.telephony import twilio as tw


@pytest.fixture()
def http_mock(monkeypatch):
    state = {"requests": [], "handler": None}
    real = httpx.Client

    def handler(request):
        state["requests"].append(request)
        return state["handler"](request)

    monkeypatch.setattr(httpx, "Client", functools.partial(real, transport=httpx.MockTransport(handler)))
    return state


def test_create_call_form_encoding(http_mock):
    http_mock["handler"] = lambda r: httpx.Response(201, json={"sid": "CA1", "status": "queued"})
    client = tw.TwilioClient("AC123", "secret-token")
    result = client.create_call(to="+14155550123", from_="+14155550100",
                                twiml=tw.stream_twiml("wss://x.test/api/twilio/media/tok?a=1&b=2", {"call_id": "7"}),
                                status_callback="https://x.test/api/twilio/status/tok")
    assert result["sid"] == "CA1"
    req = http_mock["requests"][0]
    assert req.url.path.endswith("/2010-04-01/Accounts/AC123/Calls.json")
    assert req.headers["authorization"].startswith("Basic ")
    form = parse_qs(req.content.decode())
    assert form["To"] == ["+14155550123"] and form["From"] == ["+14155550100"]
    assert form["StatusCallbackEvent"] == ["initiated", "ringing", "answered", "completed"]
    assert '<Stream url="wss://x.test/api/twilio/media/tok?a=1&amp;b=2">' in form["Twiml"][0]
    assert '<Parameter name="call_id" value="7"/>' in form["Twiml"][0]


def test_errors_are_sanitized(http_mock):
    http_mock["handler"] = lambda r: httpx.Response(401, json={"message": "Authenticate with secret-token please", "code": 20003})
    with pytest.raises(tw.TwilioError) as info:
        tw.TwilioClient("AC123", "secret-token").hangup("CA1")
    assert info.value.status_code == 401 and "secret-token" not in str(info.value)


def test_signature_roundtrip():
    params = {"CallSid": "CA1", "CallStatus": "completed"}
    sig = tw.compute_signature("https://x.test/cb", params, "tok")
    assert tw.validate_signature("https://x.test/cb", params, sig, "tok")
    assert not tw.validate_signature("https://x.test/cb", {**params, "CallStatus": "busy"}, sig, "tok")
    assert not tw.validate_signature("https://x.test/cb", params, sig, "other")
