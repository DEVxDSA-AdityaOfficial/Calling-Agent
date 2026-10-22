"""ConversationModel for any OpenAI-compatible Chat Completions API.

Covers OpenAI itself and self-hosted models served by vLLM, Ollama, llama.cpp, TGI, LM Studio, etc.
"""

import json
import re
from collections.abc import AsyncIterator

import httpx

from .base import ConversationModelError, Message


class OpenAICompatibleModel:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        name: str,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.name = name
        self.model = model
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._timeout = httpx.Timeout(timeout, connect=10.0)
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, transport=self._transport)

    def _body(self, messages: list[Message], **extra) -> dict:
        return {"model": self.model, "messages": messages, **extra}

    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        try:
            async with self._client() as http:
                async with http.stream("POST", self._url, headers=self._headers, json=self._body(messages, stream=True)) as r:
                    if r.status_code >= 400:
                        await r.aread()
                        raise ConversationModelError(f"{self.name} {r.status_code}: {r.text[:300]}")
                    async for line in r.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            delta = json.loads(data)["choices"][0].get("delta", {}).get("content")
                        except (ValueError, KeyError, IndexError):
                            continue
                        if delta:
                            yield delta
        except httpx.HTTPError as exc:
            raise ConversationModelError(f"Could not reach {self.name}: {exc}") from exc

    async def _post(self, body: dict) -> str:
        try:
            async with self._client() as http:
                r = await http.post(self._url, headers=self._headers, json=body)
        except httpx.HTTPError as exc:
            raise ConversationModelError(f"Could not reach {self.name}: {exc}") from exc
        if r.status_code >= 400:
            raise ConversationModelError(f"{self.name} {r.status_code}: {r.text[:300]}")
        return r.json()["choices"][0]["message"]["content"] or ""

    async def complete(self, messages: list[Message]) -> str:
        return await self._post(self._body(messages))

    async def complete_json(self, messages: list[Message]) -> dict:
        text = await self._post(self._body(messages, response_format={"type": "json_object"}))
        return parse_json_object(text)


def parse_json_object(text: str) -> dict:
    try:
        return json.loads(text)
    except ValueError:
        # Some small models wrap JSON in prose or code fences.
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except ValueError:
                pass
    raise ConversationModelError("The model didn't return valid JSON.")
