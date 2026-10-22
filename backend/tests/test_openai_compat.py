import asyncio
import json

import httpx
import pytest

from app.conversation.base import ConversationModelError
from app.conversation.openai_compat import OpenAICompatibleModel, parse_json_object


def _model(handler):
    return OpenAICompatibleModel(
        base_url="https://llm.test/v1", api_key="k", model="m", name="Test", transport=httpx.MockTransport(handler)
    )


def test_stream_parses_sse():
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        assert body["stream"] is True and body["model"] == "m"
        assert request.headers["authorization"] == "Bearer k"
        chunks = [{"choices": [{"delta": {"role": "assistant"}}]}, {"choices": [{"delta": {"content": "Hel"}}]}, {"choices": [{"delta": {"content": "lo"}}]}]
        sse = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    async def run():
        return [c async for c in _model(handler).stream([{"role": "user", "content": "hi"}])]

    assert asyncio.run(run()) == ["Hel", "lo"]


def test_errors_and_json():
    model = _model(lambda r: httpx.Response(429, text="rate limited"))
    with pytest.raises(ConversationModelError, match="429"):
        asyncio.run(model.complete([{"role": "user", "content": "hi"}]))

    def ok(request):
        assert json.loads(request.content)["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"message": {"content": '```json\n{"a": 1}\n```'}}]})

    assert asyncio.run(_model(ok).complete_json([{"role": "user", "content": "x"}])) == {"a": 1}
    with pytest.raises(ConversationModelError):
        parse_json_object("no json here")
