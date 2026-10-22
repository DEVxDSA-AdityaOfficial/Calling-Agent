"""Thin wrapper over the Retell REST API (https://docs.retellai.com/api-references)."""

import hashlib
import hmac
import re
import time
from typing import Any

import httpx

from .config import Settings


class RetellError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class RetellClient:
    def __init__(self, settings: Settings, api_key: str | None = None, transport: httpx.BaseTransport | None = None):
        api_key = api_key or settings.retell_api_key
        if not api_key:
            raise RetellError("Retell isn't connected. Add your API key in Settings → API & Providers.")
        self._http = httpx.Client(
            base_url=settings.retell_base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(30.0, connect=10.0),
            transport=transport,
        )

    def _request(self, method: str, path: str, json: dict | None = None) -> Any:
        try:
            resp = self._http.request(method, path, json=json)
        except httpx.HTTPError as exc:
            raise RetellError(f"Could not reach Retell: {exc}") from exc
        if resp.status_code >= 400:
            try:
                message = resp.json().get("message") or resp.text
            except ValueError:
                message = resp.text
            raise RetellError(f"Retell API {resp.status_code}: {message}", resp.status_code)
        return resp.json() if resp.content else None

    # --- Response engine (the LLM that drives the conversation) ---
    def create_llm(self, body: dict) -> dict:
        return self._request("POST", "/create-retell-llm", body)

    def update_llm(self, llm_id: str, body: dict) -> dict:
        return self._request("PATCH", f"/update-retell-llm/{llm_id}", body)

    # --- Voice agent ---
    def create_agent(self, body: dict) -> dict:
        return self._request("POST", "/create-agent", body)

    def update_agent(self, agent_id: str, body: dict) -> dict:
        return self._request("PATCH", f"/update-agent/{agent_id}", body)

    def list_voices(self) -> list[dict]:
        return self._request("GET", "/list-voices")

    # --- Calls ---
    def create_phone_call(self, body: dict) -> dict:
        return self._request("POST", "/v2/create-phone-call", body)

    def get_call(self, call_id: str) -> dict:
        return self._request("GET", f"/v2/get-call/{call_id}")

    def stop_call(self, call_id: str) -> None:
        self._request("POST", f"/v2/stop-call/{call_id}")


_SIGNATURE_RE = re.compile(r"v=(\d+),d=(.*)")
_SIGNATURE_MAX_AGE_MS = 5 * 60 * 1000


def verify_webhook_signature(raw_body: str, signature: str | None, api_key: str) -> bool:
    """Implements Retell's `x-retell-signature` scheme: v=<ts_ms>,d=hex(HMAC_SHA256(api_key, body + ts))."""
    if not signature or not api_key:
        return False
    match = _SIGNATURE_RE.fullmatch(signature.strip())
    if not match:
        return False
    timestamp, digest = match.groups()
    if abs(time.time() * 1000 - int(timestamp)) > _SIGNATURE_MAX_AGE_MS:
        return False
    expected = hmac.new(api_key.encode(), (raw_body + timestamp).encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, digest)
