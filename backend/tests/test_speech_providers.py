"""Contract tests for the STT providers against mocked HTTP and WebSocket servers.

These pin the request/response shapes we implemented from the providers' docs. They do NOT prove
compatibility with the live APIs; see README "Real-provider verification".
"""

import asyncio
import base64
import functools
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import websockets

from app.speech import audio
from app.speech.base import (
    STTAuthError,
    STTBadResponseError,
    STTConfigError,
    STTConnectionError,
    STTRateLimitError,
    STTTimeoutError,
    sanitize,
)
from app.speech.openai_whisper import OpenAIWhisperProvider
from app.speech.sarvam import SarvamSTTProvider

SARVAM, WHISPER = SarvamSTTProvider(), OpenAIWhisperProvider()


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def http_mock(monkeypatch):
    """Route every httpx.AsyncClient through a handler set by the test."""
    state = {"handler": None, "requests": []}
    real = httpx.AsyncClient

    def handler(request):
        state["requests"].append(request)
        return state["handler"](request)

    monkeypatch.setattr(httpx, "AsyncClient", functools.partial(real, transport=httpx.MockTransport(handler)))
    return state


@pytest.fixture()
def settings_env(monkeypatch):
    from app.config import get_settings

    def apply(**env):
        for k, v in env.items():
            monkeypatch.setenv(k, str(v))
        get_settings.cache_clear()

    yield apply
    get_settings.cache_clear()


def _multipart_fields(request: httpx.Request) -> dict[str, str]:
    body = request.content.decode("latin-1")
    fields = {}
    for part in body.split("--")[1:]:
        if 'name="' in part and "filename=" not in part:
            name = part.split('name="')[1].split('"')[0]
            fields[name] = part.split("\r\n\r\n", 1)[1].rsplit("\r\n", 1)[0] if "\r\n\r\n" in part else ""
    return fields


# --- Configuration validation ---
def test_config_validation_and_language_mapping():
    c = SARVAM.validate_config({}, agent_language="hinglish")
    assert (c.model, c.language, c.mode) == ("saaras:v4", "hi-IN", "codemix")
    c = SARVAM.validate_config({"language": "od-IN", "model": "saaras:v3-realtime", "mode": "translit"})
    url = SARVAM.stream_url(c)
    q = parse_qs(urlparse(url).query)
    assert q["language_code"] == ["or-IN"]  # streaming uses or-IN for Odia
    assert q["encoding"] == ["mulaw"] and q["sample_rate"] == ["8000"] and q["model"] == ["saaras:v3-realtime"]
    with pytest.raises(STTConfigError):
        SARVAM.validate_config({"model": "saarika:v1"})
    with pytest.raises(STTConfigError):
        SARVAM.validate_config({"language": "xx-YY"})

    w = WHISPER.validate_config({}, agent_language="hinglish")
    assert (w.model, w.language) == ("gpt-realtime-whisper", "auto")
    assert WHISPER.validate_config({}, agent_language="hi-IN").language == "hi"
    with pytest.raises(STTConfigError):
        WHISPER.validate_config({"language": "hi-IN"})  # Whisper wants ISO-639-1
    update = WHISPER.session_update(WHISPER.validate_config({"language": "en"}))
    inp = update["session"]["audio"]["input"]
    assert update["session"]["type"] == "transcription"
    assert inp["format"] == {"type": "audio/pcmu"} and inp["turn_detection"] is None
    assert inp["transcription"] == {"model": "gpt-realtime-whisper", "delay": "low", "language": "en"}


# --- Sarvam REST ---
def test_sarvam_rest_success_and_request_shape(http_mock):
    http_mock["handler"] = lambda r: httpx.Response(
        200, json={"request_id": "r1", "transcript": " Haan bolo, kya kaam hai? ", "language_code": "hi-IN", "language_probability": 0.93}
    )
    cfg = SARVAM.validate_config({"language": "auto", "model": "saaras:v3-realtime"})
    result = run(SARVAM.transcribe("sk_sarvam_secret", b"RIFF....", filename="a.wav", content_type="audio/wav", config=cfg))
    assert result.text == "Haan bolo, kya kaam hai?" and result.status == "completed"
    assert result.language == "hi-IN" and result.language_confidence == 0.93 and result.request_id == "r1"
    req = http_mock["requests"][0]
    assert req.url.path == "/speech-to-text" and req.headers["api-subscription-key"] == "sk_sarvam_secret"
    fields = _multipart_fields(req)
    assert fields["model"] == "saaras:v3"  # streaming-only model maps to its REST sibling
    assert fields["language_code"] == "unknown"  # REST spells auto-detect "unknown"


@pytest.mark.parametrize(
    "status,body,exc",
    [
        (403, {"error": {"message": "Invalid key sk_sarvam_secret", "code": "invalid_api_key_error"}}, STTAuthError),
        (429, {"error": {"message": "quota", "code": "insufficient_quota_error"}}, STTRateLimitError),
        (422, {"error": {"message": "bad audio", "code": "unprocessable_entity_error"}}, STTConfigError),
    ],
)
def test_sarvam_rest_errors(http_mock, status, body, exc):
    http_mock["handler"] = lambda r: httpx.Response(status, json=body)
    with pytest.raises(exc) as info:
        run(SARVAM.transcribe("sk_sarvam_secret", b"x", filename="a.wav", content_type="audio/wav", config=SARVAM.validate_config({})))
    assert "sk_sarvam_secret" not in str(info.value)


def test_sarvam_rest_malformed_and_timeout(http_mock):
    http_mock["handler"] = lambda r: httpx.Response(200, text="<html>oops</html>")
    with pytest.raises(STTBadResponseError):
        run(SARVAM.transcribe("k", b"x", filename="a.wav", content_type="audio/wav", config=SARVAM.validate_config({})))

    def timeout(_):
        raise httpx.ReadTimeout("slow")

    http_mock["handler"] = timeout
    with pytest.raises(STTTimeoutError):
        run(SARVAM.transcribe("k", b"x", filename="a.wav", content_type="audio/wav", config=SARVAM.validate_config({})))


# --- Whisper REST ---
def test_whisper_rest_uses_whisper_1(http_mock):
    http_mock["handler"] = lambda r: httpx.Response(200, json={"text": "Hello there", "language": "english", "duration": 1.5})
    result = run(WHISPER.transcribe("sk-openai-secret-123", b"webm", filename="c.webm", content_type="audio/webm",
                                    config=WHISPER.validate_config({"language": "en"})))
    assert (result.text, result.model, result.audio_duration_s) == ("Hello there", "whisper-1", 1.5)
    req = http_mock["requests"][0]
    fields = _multipart_fields(req)
    assert req.url.path == "/v1/audio/transcriptions" and fields["model"] == "whisper-1"
    assert fields["response_format"] == "verbose_json" and fields["language"] == "en"
    assert req.headers["authorization"] == "Bearer sk-openai-secret-123"


def test_whisper_errors_and_health(http_mock):
    http_mock["handler"] = lambda r: httpx.Response(401, json={"error": {"message": "Incorrect API key provided: sk-openai-secret-123"}})
    with pytest.raises(STTAuthError) as info:
        run(WHISPER.transcribe("sk-openai-secret-123", b"x", filename="c.webm", content_type="audio/webm", config=WHISPER.validate_config({})))
    assert "secret" not in str(info.value)

    http_mock["handler"] = lambda r: httpx.Response(200, json={"data": [{"id": "whisper-1"}]})
    with pytest.raises(STTConfigError, match="gpt-realtime-whisper"):
        run(WHISPER.health_check("k", WHISPER.validate_config({})))
    http_mock["handler"] = lambda r: httpx.Response(200, json={"data": [{"id": "whisper-1"}, {"id": "gpt-realtime-whisper"}]})
    assert "gpt-realtime-whisper" in run(WHISPER.health_check("k", WHISPER.validate_config({})))


# --- Streaming (local mock WebSocket servers) ---
class MockWS:
    """Minimal WebSocket server; `behaviour(ws, path, headers, received)` drives each connection."""

    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.received: list[dict] = []
        self.paths: list[str] = []
        self.headers: list[dict] = []

    async def handler(self, ws):
        self.paths.append(ws.request.path)
        self.headers.append(dict(ws.request.headers))
        await self.behaviour(ws, self)

    async def __aenter__(self):
        self.server = await websockets.serve(self.handler, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        self.server.close()
        await self.server.wait_closed()


async def _collect(stream_factory, feed=None, wait=0.6):
    events = []

    async def on_event(e):
        events.append(e)

    stream = stream_factory(on_event)
    await stream.start()
    if feed:
        await feed(stream)
    await asyncio.sleep(wait)
    await stream.close()
    return events


def test_sarvam_stream_events_and_auth_header(settings_env):
    async def behaviour(ws, srv):
        await ws.send(json.dumps({"event": "session.begin", "request_id": "req-1", "config": {}}))
        async for raw in ws:
            msg = json.loads(raw)
            srv.received.append(msg)
            if msg["event"] == "audio_input" and len([m for m in srv.received if m["event"] == "audio_input"]) == 2:
                for out in (
                    {"event": "vad.speech_start", "utterance_idx": 0},
                    {"event": "transcript.partial", "utterance_idx": 0, "text": "haan"},
                    {"event": "vad.speech_end", "utterance_idx": 0},
                    {"event": "transcript.final", "utterance_idx": 0, "text": "Haan bolo", "language": "hi-IN"},
                    {"event": "error", "code": "invalid_config", "is_fatal": False, "message": "ignored"},
                ):
                    await ws.send(json.dumps(out))
            if msg["event"] == "end":
                await ws.send(json.dumps({"event": "session.end", "request_id": "req-1"}))
                return

    async def main():
        async with MockWS(behaviour) as srv:
            settings_env(SARVAM_WS_URL=f"ws://127.0.0.1:{srv.port}/speech-to-text-realtime/ws")
            cfg = SARVAM.validate_config({"language": "hi-IN"})

            async def feed(stream):
                await stream.send_audio(audio.tone_ulaw(300, 20))
                await stream.send_audio(audio.tone_ulaw(300, 20))

            events = await _collect(lambda cb: SARVAM.open_stream("sk_live_key", cfg, cb), feed)
            return srv, events

    srv, events = run(main())
    assert srv.headers[0]["api-subscription-key"] == "sk_live_key"
    q = parse_qs(urlparse(srv.paths[0]).query)
    assert q["encoding"] == ["mulaw"] and q["language_code"] == ["hi-IN"]
    audio_msgs = [m for m in srv.received if m["event"] == "audio_input"]
    assert base64.b64decode(audio_msgs[0]["audio"]) == audio.tone_ulaw(300, 20)  # passed through unconverted
    assert srv.received[-1] == {"event": "end"}
    kinds = [(e.type, e.text) for e in events]
    assert kinds == [("speech_start", ""), ("partial", "haan"), ("speech_end", ""), ("final", "Haan bolo")]
    assert events[-1].language == "hi-IN" and events[-1].latency_ms is not None


def test_sarvam_health_check_sends_no_audio(settings_env):
    async def behaviour(ws, srv):
        await ws.send(json.dumps({"event": "session.begin", "request_id": "r"}))
        async for raw in ws:
            srv.received.append(json.loads(raw))

    async def main():
        async with MockWS(behaviour) as srv:
            settings_env(SARVAM_WS_URL=f"ws://127.0.0.1:{srv.port}/ws")
            detail = await SARVAM.health_check("k", SARVAM.validate_config({}))
            await asyncio.sleep(0.1)
            return srv, detail

    srv, detail = run(main())
    assert "Connected" in detail
    assert not any(m["event"] == "audio_input" for m in srv.received)


@pytest.mark.parametrize(
    "behaviour_kind,exc",
    [("close_1003", STTAuthError), ("close_4000", STTConfigError), ("fatal_403", STTAuthError), ("silent", STTTimeoutError)],
)
def test_sarvam_stream_failures(settings_env, behaviour_kind, exc):
    async def behaviour(ws, srv):
        if behaviour_kind == "close_1003":
            await ws.close(1003, "invalid key")
        elif behaviour_kind == "close_4000":
            await ws.close(4000, "bad language")
        elif behaviour_kind == "fatal_403":
            await ws.send(json.dumps({"event": "error", "code": "forbidden", "is_fatal": True, "message": "nope", "status_code": 403}))
            await ws.close(1003)
        else:
            await asyncio.sleep(5)

    async def main():
        async with MockWS(behaviour) as srv:
            settings_env(SARVAM_WS_URL=f"ws://127.0.0.1:{srv.port}/ws", STT_CONNECT_TIMEOUT_S="0.5")
            stream = SARVAM.open_stream("k", SARVAM.validate_config({}), lambda e: asyncio.sleep(0))
            with pytest.raises(exc):
                await stream.start()
            await stream.close()

    run(main())


def test_stream_connection_refused(settings_env):
    settings_env(SARVAM_WS_URL="ws://127.0.0.1:9/ws", OPENAI_REALTIME_URL="ws://127.0.0.1:9/v1/realtime")

    async def main():
        for provider in (SARVAM, WHISPER):
            stream = provider.open_stream("k", provider.validate_config({}), lambda e: asyncio.sleep(0))
            with pytest.raises(STTConnectionError):
                await stream.start()

    run(main())


def test_whisper_stream_local_vad_commit_and_final(settings_env):
    async def behaviour(ws, srv):
        async for raw in ws:
            msg = json.loads(raw)
            srv.received.append(msg)
            if msg["type"] == "session.update":
                await ws.send(json.dumps({"type": "session.updated", "session": msg["session"]}))
            elif msg["type"] == "input_audio_buffer.commit":
                await ws.send(json.dumps({"type": "conversation.item.input_audio_transcription.delta", "item_id": "it1", "delta": "Hello "}))
                await ws.send(json.dumps({"type": "conversation.item.input_audio_transcription.completed", "item_id": "it1", "transcript": "Hello there"}))

    async def main():
        async with MockWS(behaviour) as srv:
            settings_env(OPENAI_REALTIME_URL=f"ws://127.0.0.1:{srv.port}/v1/realtime")
            cfg = WHISPER.validate_config({"language": "en", "silence_ms": 400})

            async def feed(stream):
                for chunk in [audio.silence_ulaw(100), audio.tone_ulaw(300, 400), audio.silence_ulaw(500)]:
                    for i in range(0, len(chunk), 160):
                        await stream.send_audio(chunk[i : i + 160])

            events = await _collect(lambda cb: WHISPER.open_stream("sk-openai-key-1234", cfg, cb), feed)
            return srv, events

    srv, events = run(main())
    assert srv.headers[0]["authorization"] == "Bearer sk-openai-key-1234"
    assert srv.received[0]["session"]["audio"]["input"]["transcription"]["model"] == "gpt-realtime-whisper"
    assert [m["type"] for m in srv.received].count("input_audio_buffer.commit") == 1
    kinds = [e.type for e in events]
    assert kinds == ["speech_start", "speech_end", "partial", "final"]
    assert events[-1].text == "Hello there" and events[-1].segment_id == "it1" and events[-1].latency_ms is not None


def test_whisper_stream_rejected_session(settings_env):
    async def behaviour(ws, srv):
        async for raw in ws:
            if json.loads(raw)["type"] == "session.update":
                await ws.send(json.dumps({"type": "error", "error": {"type": "invalid_request_error", "message": "Model not allowed"}}))

    async def main():
        async with MockWS(behaviour) as srv:
            settings_env(OPENAI_REALTIME_URL=f"ws://127.0.0.1:{srv.port}/v1/realtime")
            stream = WHISPER.open_stream("k", WHISPER.validate_config({}), lambda e: asyncio.sleep(0))
            with pytest.raises(STTConfigError, match="Model not allowed"):
                await stream.start()

    run(main())


# --- Audio & sanitizing ---
def test_audio_helpers():
    assert audio.ULAW_TO_PCM16[0xFF] == 0 and audio.ULAW_TO_PCM16[0x80] == 32124
    pcm = audio.ulaw_to_pcm16(audio.tone_ulaw(440, 100))
    assert audio.ulaw_to_pcm16(audio.pcm16_to_ulaw(pcm)) == pcm
    assert len(audio.resample_pcm16(pcm, 8000, 16000)) == 2 * len(pcm)
    wav = audio.mulaw_to_wav16k(audio.tone_ulaw(440, 1000))
    assert wav[:4] == b"RIFF" and int.from_bytes(wav[24:28], "little") == 16000
    vad = audio.EnergyVAD(silence_ms=400)
    events = vad.feed(audio.silence_ulaw(200)) + vad.feed(audio.tone_ulaw(300, 300)) + vad.feed(audio.silence_ulaw(500))
    assert events == ["start", "end"]
    audio.validate_twilio_media_format({"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1})
    with pytest.raises(audio.TelephonyFormatError):
        audio.validate_twilio_media_format({"encoding": "audio/l16", "sampleRate": 16000})


def test_sanitize_removes_secrets():
    text = "failed for key sk-abcdefghijklmnop and sk_live_ABCDEFGH1234 Bearer abc.def.ghi and my-secret-token"
    out = sanitize(text, ["my-secret-token"])
    for secret in ("sk-abcdefghijklmnop", "sk_live_ABCDEFGH1234", "abc.def.ghi", "my-secret-token"):
        assert secret not in out
    assert len(sanitize("x" * 1000)) <= 301
