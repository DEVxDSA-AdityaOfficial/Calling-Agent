"""ElevenLabs text-to-speech, streamed as 8 kHz μ-law so it can go straight onto a Twilio call.

Docs: https://elevenlabs.io/docs/api-reference/text-to-speech/stream
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from ..config import get_settings
from .base import sanitize


class TTSError(Exception):
    pass


class ElevenLabsTTS:
    def __init__(self, api_key: str, voice_id: str, model_id: str | None = None, language: str | None = None):
        self._key = api_key
        self.voice_id = voice_id
        self.model_id = model_id or get_settings().elevenlabs_tts_model
        self.language = language

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        s = get_settings()
        body = {"text": text, "model_id": self.model_id}
        if self.language:
            body["language_code"] = self.language
        url = f"{s.elevenlabs_base_url.rstrip('/')}/v1/text-to-speech/{self.voice_id}/stream"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=10)) as http:
                async with http.stream(
                    "POST", url, params={"output_format": "ulaw_8000"}, headers={"xi-api-key": self._key}, json=body
                ) as r:
                    if r.status_code >= 400:
                        await r.aread()
                        raise TTSError(f"ElevenLabs {r.status_code}: {sanitize(r.text, [self._key])}")
                    async for chunk in r.aiter_bytes():
                        if chunk:
                            yield chunk
        except httpx.HTTPError as exc:
            raise TTSError(f"Could not reach ElevenLabs: {sanitize(str(exc), [self._key])}") from exc


async def list_voices(api_key: str) -> list[dict]:
    s = get_settings()
    async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=10)) as http:
        r = await http.get(f"{s.elevenlabs_base_url.rstrip('/')}/v2/voices", params={"page_size": 100}, headers={"xi-api-key": api_key})
    if r.status_code >= 400:
        raise TTSError(f"ElevenLabs {r.status_code}: {sanitize(r.text, [api_key])}")
    voices = []
    for v in r.json().get("voices", []):
        labels = v.get("labels") or {}
        voices.append(
            {
                "voice_id": v.get("voice_id"),
                "voice_name": v.get("name"),
                "provider": "elevenlabs",
                "gender": labels.get("gender") or "",
                "accent": labels.get("accent"),
                "age": labels.get("age"),
                "preview_audio_url": v.get("preview_url"),
            }
        )
    return voices
