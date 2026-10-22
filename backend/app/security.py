"""Password hashing, session tokens and encryption of provider secrets."""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from .config import BACKEND_DIR, get_settings

log = logging.getLogger(__name__)

# --- Passwords (scrypt, stdlib) ---
_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# --- Session tokens: the cookie holds the token, the DB only its hash ---
def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# --- Secrets at rest ---
_KEY_FILE = BACKEND_DIR / ".encryption_key"
_fernet: MultiFernet | None = None


def _get_fernet() -> MultiFernet:
    """MultiFernet: the first key encrypts; every listed key decrypts (supports key rotation)."""
    global _fernet
    if _fernet is None:
        raw = get_settings().encryption_key
        if not raw:
            if _KEY_FILE.exists():
                raw = _KEY_FILE.read_text().strip()
            else:
                raw = Fernet.generate_key().decode()
                _KEY_FILE.write_text(raw)
                _KEY_FILE.chmod(0o600)
                log.warning("Generated a development encryption key at %s. Set ENCRYPTION_KEY in production.", _KEY_FILE)
        _fernet = MultiFernet([Fernet(k.strip().encode()) for k in raw.split(",") if k.strip()])
    return _fernet


def reset_fernet() -> None:
    global _fernet
    _fernet = None


def rotate_token(token: str) -> str:
    """Re-encrypt with the current primary key."""
    return _get_fernet().rotate(token.encode()).decode() if token else token


def encrypt_json(data: dict) -> str:
    return _get_fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_json(token: str) -> dict:
    if not token:
        return {}
    try:
        return json.loads(_get_fernet().decrypt(token.encode()))
    except InvalidToken:
        log.error("Could not decrypt provider secrets (was ENCRYPTION_KEY changed?)")
        return {}


def mask(secret: str | None) -> str | None:
    if not secret:
        return None
    return "•" * 12 + secret[-4:] if len(secret) > 8 else "•" * 8
