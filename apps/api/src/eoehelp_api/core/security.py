"""Password hashing, opaque token handling, JWT issuance, and field encryption."""

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from eoehelp_api.config import get_settings

# argon2id at library defaults, which track OWASP guidance. Deliberately not
# tuned down for test speed: a weakened KDF in the shared code path is how a
# convenience becomes a production weakness.
_password_hasher = PasswordHasher()

TOKEN_BYTES = 32


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _password_hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def generate_token() -> str:
    """Create a 256-bit URL-safe token for magic links, refresh, and share links."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> bytes:
    """Hash a bearer token for storage.

    Plain SHA-256 is correct here and argon2 is not: these are full-entropy
    random values, so there is nothing to brute-force, and storage must stay
    cheap enough to look up on every request.
    """
    return hashlib.sha256(token.encode("utf-8")).digest()


def tokens_equal(candidate_hash: bytes, stored_hash: bytes) -> bool:
    return hmac.compare_digest(candidate_hash, stored_hash)


def create_access_token(
    *, user_id: uuid.UUID, patient_id: uuid.UUID | None, role: str
) -> tuple[str, datetime]:
    settings = get_settings()
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=settings.access_token_ttl_seconds)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": secrets.token_urlsafe(16),
    }
    if patient_id is not None:
        payload["pid"] = str(patient_id)
    token = jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return token, expires_at


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify an access token, raising jwt exceptions on failure."""
    settings = get_settings()
    return jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "iat", "sub"]},
    )


class FieldCipher:
    """AES-256-GCM envelope encryption for free-text clinical columns.

    Free text is where identifiers leak — patients write their own and their
    doctor's name into notes fields — so these columns are encrypted in the
    application, with the key held outside the database. A database disclosure
    alone therefore yields no narrative PHI.

    The record id is bound as additional authenticated data, so a ciphertext
    moved between rows fails to decrypt rather than silently attributing one
    patient's note to another.
    """

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("field encryption key must be 32 bytes")
        self._aead = AESGCM(key)

    @classmethod
    def from_settings(cls) -> "FieldCipher":
        raw = get_settings().field_encryption_key.get_secret_value()
        key = base64.urlsafe_b64decode(_pad_base64(raw))
        if len(key) != 32:
            key = hashlib.sha256(raw.encode("utf-8")).digest()
        return cls(key)

    def encrypt(self, plaintext: str | None, *, aad: str) -> bytes | None:
        if plaintext is None:
            return None
        nonce = secrets.token_bytes(12)
        ciphertext = self._aead.encrypt(nonce, plaintext.encode("utf-8"), aad.encode("utf-8"))
        return nonce + ciphertext

    def decrypt(self, blob: bytes | None, *, aad: str) -> str | None:
        if blob is None:
            return None
        nonce, ciphertext = blob[:12], blob[12:]
        return self._aead.decrypt(nonce, ciphertext, aad.encode("utf-8")).decode("utf-8")


def _pad_base64(value: str) -> str:
    return value + "=" * (-len(value) % 4)
