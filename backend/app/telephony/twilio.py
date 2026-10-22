"""Twilio REST (calls) and webhook signature validation.

Docs: https://www.twilio.com/docs/voice/api/call-resource
      https://www.twilio.com/docs/usage/security#validating-requests
      https://www.twilio.com/docs/voice/media-streams/websocket-messages
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from xml.sax.saxutils import quoteattr

import httpx

from ..config import get_settings
from ..speech.base import sanitize


class TwilioError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class TwilioClient:
    def __init__(self, account_sid: str, auth_token: str):
        if not account_sid or not auth_token:
            raise TwilioError("Twilio isn't connected. Add your Account SID and Auth Token in Settings → API & Providers.")
        self.account_sid = account_sid
        self._token = auth_token
        self._base = f"{get_settings().twilio_base_url.rstrip('/')}/2010-04-01/Accounts/{account_sid}"

    def _request(self, method: str, path: str, data: dict | None = None) -> dict:
        try:
            with httpx.Client(timeout=httpx.Timeout(20, connect=10)) as http:
                r = http.request(method, f"{self._base}{path}", data=data, auth=(self.account_sid, self._token))
        except httpx.HTTPError as exc:
            raise TwilioError(f"Could not reach Twilio: {sanitize(str(exc), [self._token])}") from exc
        if r.status_code >= 400:
            try:
                message = r.json().get("message") or r.text
            except ValueError:
                message = r.text
            raise TwilioError(f"Twilio {r.status_code}: {sanitize(message, [self._token])}", r.status_code)
        return r.json() if r.content else {}

    def create_call(self, *, to: str, from_: str, twiml: str, status_callback: str) -> dict:
        data = {
            "To": to,
            "From": from_,
            "Twiml": twiml,
            "StatusCallback": status_callback,
            "StatusCallbackMethod": "POST",
        }
        # A list value makes httpx repeat the key (StatusCallbackEvent=initiated&StatusCallbackEvent=…).
        data["StatusCallbackEvent"] = ["initiated", "ringing", "answered", "completed"]
        return self._request("POST", "/Calls.json", data)

    def hangup(self, call_sid: str) -> dict:
        return self._request("POST", f"/Calls/{call_sid}.json", {"Status": "completed"})

    def get_call(self, call_sid: str) -> dict:
        return self._request("GET", f"/Calls/{call_sid}.json")


def stream_twiml(ws_url: str, parameters: dict[str, str]) -> str:
    params = "".join(f"<Parameter name={quoteattr(k)} value={quoteattr(v)}/>" for k, v in parameters.items())
    return f"<Response><Connect><Stream url={quoteattr(ws_url)}>{params}</Stream></Connect></Response>"


def compute_signature(url: str, params: dict[str, str], auth_token: str) -> str:
    payload = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    return base64.b64encode(hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()).decode()


def validate_signature(url: str, params: dict[str, str], signature: str | None, auth_token: str) -> bool:
    if not signature or not auth_token:
        return False
    return hmac.compare_digest(compute_signature(url, params, auth_token), signature)


# Twilio CallStatus -> our call status.
STATUS_MAP = {
    "queued": "queued",
    "initiated": "queued",
    "ringing": "ringing",
    "in-progress": "in_progress",
    "answered": "in_progress",
    "completed": "completed",
    "busy": "failed",
    "no-answer": "failed",
    "failed": "failed",
    "canceled": "failed",
}
# Twilio CallStatus -> the Retell-style disconnection_reason our analytics understand.
REASON_MAP = {"busy": "dial_busy", "no-answer": "dial_no_answer", "failed": "dial_failed", "canceled": "manual_stopped"}
