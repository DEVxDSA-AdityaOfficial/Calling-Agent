"""Third-party provider definitions, per-user credential storage and connection tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import ProviderCredential, User, utcnow
from .retell_client import RetellClient
from .security import decrypt_json, encrypt_json
from .speech.base import STTError, sanitize


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    secret: bool = True
    placeholder: str = ""
    required: bool = True
    kind: str = "text"  # text | select
    options: tuple[tuple[str, str], ...] = ()  # (value, label) for selects; validated on save
    help: str = ""


@dataclass(frozen=True)
class ProviderDef:
    id: str
    name: str
    category: str  # telephony | voice_agent | voice | speech | intelligence
    purpose: str
    fields: list[FieldDef] = field(default_factory=list)
    note: str = ""


def _speech_fields(provider_id: str) -> list[FieldDef]:
    from .speech.router import PROVIDERS as STT

    caps = STT[provider_id].capabilities()
    langs = tuple((l["code"], l["label"]) for l in caps["languages"])
    if provider_id == "whisper":
        return [
            FieldDef("api_key", "API Key (optional — reuses your OpenAI key if empty)", placeholder="sk-…", required=False),
            FieldDef("language", "Language", secret=False, required=False, kind="select", options=langs),
            # First option = what the form pre-selects, so it must be the provider default.
            FieldDef("delay", "Latency vs accuracy", secret=False, required=False, kind="select",
                     options=tuple(
                         (d, f"{d.capitalize()} (default)" if d == caps["defaults"]["delay"] else d.capitalize())
                         for d in sorted(caps["delays"], key=lambda d: d != caps["defaults"]["delay"])
                     ),
                     help="Lower delay = earlier text; higher = more accurate."),
        ]
    return [
        FieldDef("api_key", "API Subscription Key", placeholder="sk_…"),
        FieldDef("model", "Model", secret=False, required=False, kind="select",
                 options=tuple((m["id"], m["label"]) for m in caps["models"])),
        FieldDef("language", "Language", secret=False, required=False, kind="select", options=langs),
        FieldDef("mode", "Transcript style", secret=False, required=False, kind="select",
                 options=(("auto", "Automatic (code-mixed for Hinglish agents)"),) + tuple((m["code"], m["label"]) for m in caps["modes"])),
    ]


def _build_providers() -> dict[str, ProviderDef]:
    return {
        p.id: p
        for p in [
            ProviderDef(
                "twilio", "Twilio", "telephony", "Phone numbers and calling",
                [
                    FieldDef("account_sid", "Account SID", secret=False, placeholder="AC…"),
                    FieldDef("auth_token", "Auth Token"),
                    FieldDef("from_number", "Caller number (E.164, a Twilio number you own)", secret=False,
                             placeholder="+14155550100", required=False),
                ],
                note="Used by agents in “Twilio + Custom Brain” mode: Twilio carries the call audio to this backend.",
            ),
            ProviderDef(
                "retell", "Retell AI", "voice_agent", "Calling, speech recognition and voices",
                [
                    FieldDef("api_key", "API Key", placeholder="key_…"),
                    FieldDef("from_number", "Caller number (E.164, bought in or imported to Retell)", secret=False,
                             placeholder="+14155550100", required=False),
                ],
            ),
            ProviderDef(
                "elevenlabs", "ElevenLabs", "voice", "High quality voices",
                [FieldDef("api_key", "API Key", placeholder="sk_…")],
                note="Speaks the agent's replies in “Twilio + Custom Brain” mode (streamed as 8 kHz μ-law, "
                "the phone network's format). Managed/Retell agents use ElevenLabs voices through Retell.",
            ),
            ProviderDef(
                "whisper", "OpenAI Whisper", "speech", "Speech-to-text · Multilingual",
                _speech_fields("whisper"),
                note="Live calls use gpt-realtime-whisper (streaming). File tests use whisper-1, which OpenAI "
                "has deprecated (shuts down 26 Feb 2027).",
            ),
            ProviderDef(
                "sarvam", "Sarvam AI", "speech", "Speech-to-text · Indian languages",
                _speech_fields("sarvam"),
                note="Live calls stream 8 kHz μ-law audio to Saaras over WebSocket. Testing the connection opens "
                "a streaming session without sending audio, so it isn't billed.",
            ),
            ProviderDef(
                "openai", "OpenAI", "intelligence", "Conversation intelligence (Custom Brain, playbooks, simulator)",
                [
                    FieldDef("api_key", "API Key (optional — platform key used if empty)", placeholder="sk-…", required=False),
                    FieldDef("model", "Model", secret=False, placeholder="gpt-4.1-mini", required=False),
                ],
            ),
        ]
    }


PROVIDERS: dict[str, ProviderDef] = _build_providers()
SPEECH_PROVIDERS = ("whisper", "sarvam")


class CredentialValidationError(ValueError):
    pass


def get_credential(db: Session, user: User, provider: str) -> ProviderCredential | None:
    return db.scalar(
        select(ProviderCredential).where(ProviderCredential.user_id == user.id, ProviderCredential.provider == provider)
    )


def credential_values(cred: ProviderCredential | None) -> dict:
    """All field values (secrets decrypted + config) for a credential."""
    if cred is None:
        return {}
    return {**(cred.config or {}), **decrypt_json(cred.secrets_encrypted)}


def _merge(definition: ProviderDef, cred: ProviderCredential | None, values: dict) -> tuple[dict, dict, bool]:
    """Returns (secrets, config, secrets_changed) after applying `values` on top of what's stored."""
    secrets = decrypt_json(cred.secrets_encrypted) if cred else {}
    config = dict(cred.config or {}) if cred else {}
    changed = False
    for f in definition.fields:
        if f.key not in values:
            continue  # untouched field: keep existing value
        value = (values[f.key] or "").strip()
        if f.kind == "select" and value and value not in {v for v, _ in f.options}:
            raise CredentialValidationError(f"{f.label}: '{value}' isn't a supported option.")
        if len(value) > 500:
            raise CredentialValidationError(f"{f.label} is too long.")
        target = secrets if f.secret else config
        if f.secret and value != target.get(f.key, ""):
            changed = True
        if value:
            target[f.key] = value
        else:
            target.pop(f.key, None)
    return secrets, config, changed


def save_credential(db: Session, user: User, provider: str, values: dict) -> ProviderCredential:
    definition = PROVIDERS[provider]
    cred = get_credential(db, user, provider) or ProviderCredential(user_id=user.id, provider=provider, config={})
    secrets, config, changed = _merge(definition, cred if cred.id else None, values)
    cred.secrets_encrypted = encrypt_json(secrets)
    cred.config = config
    if changed:
        cred.secrets_rotated_at = utcnow()
    cred.status, cred.status_detail = "untested", None
    db.add(cred)
    db.commit()
    return cred


async def replace_credential(db: Session, user: User, provider: str, values: dict) -> ProviderCredential:
    """Safe replacement: test the new values first; only overwrite stored ones if the test passes.

    If the provider isn't connected yet, the values are saved either way (so the user can fix them).
    """
    definition = PROVIDERS[provider]
    cred = get_credential(db, user, provider)
    secrets, config, changed = _merge(definition, cred, values)
    if cred is None or cred.status != "connected" or not changed:
        save_credential(db, user, provider, values)
        return await test_connection(db, user, provider)
    candidate = {**config, **secrets}
    try:
        detail = await _run_test(db, user, provider, candidate)
    except Exception as exc:  # noqa: BLE001
        raise CredentialValidationError(
            f"The new credentials didn't work, so the existing ones were kept. {_safe_error(exc, candidate)}"
        ) from exc
    save_credential(db, user, provider, values)
    cred = get_credential(db, user, provider)
    cred.status, cred.status_detail, cred.last_tested_at = "connected", detail, utcnow()
    db.commit()
    return cred


# --- Effective settings (user's connection, else platform defaults from .env) ---
def retell_settings(db: Session, user: User) -> tuple[str, str]:
    """(api_key, from_number) for this user."""
    s = get_settings()
    values = credential_values(get_credential(db, user, "retell"))
    return values.get("api_key") or s.retell_api_key, values.get("from_number") or s.retell_from_number


def retell_for_user(db: Session, user: User) -> RetellClient:
    api_key, _ = retell_settings(db, user)
    return RetellClient(get_settings(), api_key=api_key)


def stt_api_key(db: Session, user: User, provider_id: str, values: dict | None = None) -> str:
    values = values if values is not None else credential_values(get_credential(db, user, provider_id))
    if values.get("api_key"):
        return values["api_key"]
    if provider_id == "whisper":
        # Whisper can reuse the OpenAI connection (or the platform key).
        return credential_values(get_credential(db, user, "openai")).get("api_key") or get_settings().openai_api_key
    return ""


# --- Connection tests ---
def _http() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(15.0, connect=10.0))


def _safe_error(exc: Exception, values: dict) -> str:
    return sanitize(str(exc), [v for v in values.values() if isinstance(v, str)])


async def _run_test(db: Session, user: User, provider: str, values: dict) -> str:
    if provider in SPEECH_PROVIDERS:
        from .speech.router import PROVIDERS as STT

        key = values.get("api_key") or stt_api_key(db, user, provider, values)
        if not key:
            raise ValueError("Enter an API key." if provider == "sarvam" else "Enter an API key, or connect OpenAI first.")
        stt = STT[provider]
        return await stt.health_check(key, stt.validate_config(values))
    return await asyncio.to_thread(_TESTS[provider], values)


async def test_connection(db: Session, user: User, provider: str) -> ProviderCredential:
    cred = get_credential(db, user, provider)
    if cred is None:
        cred = ProviderCredential(user_id=user.id, provider=provider, config={}, secrets_encrypted=encrypt_json({}))
        db.add(cred)
    values = credential_values(cred)
    try:
        cred.status, cred.status_detail = "connected", await _run_test(db, user, provider, values)
    except (STTError, ValueError) as exc:
        cred.status, cred.status_detail = "error", _safe_error(exc, values)
    except Exception as exc:  # noqa: BLE001 - surface any failure, sanitized
        cred.status, cred.status_detail = "error", _safe_error(exc, values) or "Connection test failed."
    cred.last_tested_at = utcnow()
    db.commit()
    return cred


def _test_twilio(v: dict) -> str:
    sid, token = v.get("account_sid"), v.get("auth_token")
    if not sid or not token:
        raise ValueError("Enter the Account SID and Auth Token.")
    base = get_settings().twilio_base_url.rstrip("/")
    with _http() as http:
        r = http.get(f"{base}/2010-04-01/Accounts/{sid}/IncomingPhoneNumbers.json?PageSize=50", auth=(sid, token))
    if r.status_code in (401, 403, 404):
        raise ValueError("Twilio rejected these credentials.")
    r.raise_for_status()
    numbers = [n["phone_number"] for n in r.json().get("incoming_phone_numbers", [])]
    if v.get("from_number") and numbers and v["from_number"] not in numbers:
        raise ValueError(f"{v['from_number']} isn't a number on this Twilio account.")
    return f"{len(numbers)} number(s): {', '.join(numbers[:5])}" if numbers else "Connected (no phone numbers yet)"


def _test_retell(v: dict) -> str:
    key = v.get("api_key") or get_settings().retell_api_key
    if not key:
        raise ValueError("Enter your Retell API key.")
    voices = RetellClient(get_settings(), api_key=key).list_voices()
    source = "your key" if v.get("api_key") else "platform key"
    return f"Connected with {source} · {len(voices)} voices available"


def _test_elevenlabs(v: dict) -> str:
    key = v.get("api_key")
    if not key:
        raise ValueError("Enter your ElevenLabs API key.")
    base = get_settings().elevenlabs_base_url.rstrip("/")
    with _http() as http:
        r = http.get(f"{base}/v2/voices?page_size=100", headers={"xi-api-key": key})
    if r.status_code in (401, 403):
        raise ValueError("ElevenLabs rejected this key (or it lacks voices_read permission).")
    r.raise_for_status()
    return f"Connected · {len(r.json().get('voices', []))} voices in your library"


def _test_openai(v: dict) -> str:
    from .conversation.factory import openai_settings

    key, base_url, model = openai_settings(v)
    if not key:
        raise ValueError("No OpenAI key: enter one, or set OPENAI_API_KEY on the server.")
    with _http() as http:
        r = http.get(f"{base_url}/models", headers={"Authorization": f"Bearer {key}"})
    if r.status_code == 401:
        raise ValueError("OpenAI rejected this key.")
    r.raise_for_status()
    ids = {m["id"] for m in r.json().get("data", [])}
    if model not in ids:
        raise ValueError(f"Key works, but model '{model}' isn't available to it.")
    source = "your key" if v.get("api_key") else "platform key"
    return f"Connected with {source} · model {model}"


_TESTS = {"twilio": _test_twilio, "retell": _test_retell, "elevenlabs": _test_elevenlabs, "openai": _test_openai}
