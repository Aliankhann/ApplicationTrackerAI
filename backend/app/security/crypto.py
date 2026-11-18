"""AES-256-GCM encryption for refresh tokens, with versioned keys for rotation."""

import base64
import binascii
import os
import uuid
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

KEY_BYTES = 32
NONCE_BYTES = 12
MAX_VERSION = 999_999


class KeyringError(ValueError):
    """Invalid key configuration. Messages never contain key material."""


class DecryptionError(Exception):
    """Decryption failed; deliberately gives no detail about why."""

    def __init__(self) -> None:
        super().__init__("decryption failed")


@dataclass(frozen=True)
class Keyring:
    keys: dict[int, bytes] = field(repr=False)
    current_version: int

    @property
    def current_key(self) -> bytes:
        return self.keys[self.current_version]


@dataclass(frozen=True)
class EncryptedToken:
    ciphertext: bytes = field(repr=False)
    nonce: bytes = field(repr=False)
    key_version: int


def _parse_version(text: str) -> int:
    text = text.strip()
    if not text.isascii() or not text.isdecimal() or len(text) > len(str(MAX_VERSION)):
        raise KeyringError(f"key version must be an integer from 1 to {MAX_VERSION}")
    version = int(text)
    if not 1 <= version <= MAX_VERSION:
        raise KeyringError(f"key version must be an integer from 1 to {MAX_VERSION}")
    return version


def _parse_entry(entry: str) -> tuple[int, bytes]:
    version_text, sep, encoded = entry.strip().partition(":")
    if not sep:
        raise KeyringError("key entry must look like '<version>:<key>'")
    version = _parse_version(version_text)
    encoded = encoded.strip()
    try:
        if "+" in encoded or "/" in encoded:
            raise ValueError
        key = base64.b64decode(encoded, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError):
        raise KeyringError(f"key version {version} is not valid base64") from None
    if len(key) != KEY_BYTES:
        raise KeyringError(f"key version {version} must decode to {KEY_BYTES} bytes")
    return version, key


def _current_version(current: int | str | None, keys: dict[int, bytes]) -> int:
    if current is None or current == "":
        return max(keys)
    return _parse_version(str(current))


def parse_keyring(raw: str, current: int | str | None = None) -> Keyring:
    entries = [e for e in raw.split(",") if e.strip()]
    if not entries:
        raise KeyringError("no token encryption keys configured")
    keys: dict[int, bytes] = {}
    for entry in entries:
        version, key = _parse_entry(entry)
        if version in keys:
            raise KeyringError(f"duplicate key version {version}")
        keys[version] = key
    current_version = _current_version(current, keys)
    if current_version not in keys:
        raise KeyringError(f"current key version {current_version} is not in the keyring")
    return Keyring(keys=keys, current_version=current_version)


_cached: Keyring | None = None


def get_keyring() -> Keyring:
    global _cached
    if _cached is None:
        settings = get_settings()
        _cached = parse_keyring(
            settings.token_encryption_keys.get_secret_value(),
            settings.token_encryption_current_version,
        )
    return _cached


def clear_keyring_cache() -> None:
    global _cached
    _cached = None


def _aad(user_id: uuid.UUID) -> bytes:
    return f"oauth_token:{user_id}".encode()


def encrypt(plaintext: str, user_id: uuid.UUID, keyring: Keyring) -> EncryptedToken:
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(keyring.current_key).encrypt(nonce, plaintext.encode(), _aad(user_id))
    return EncryptedToken(ciphertext, nonce, keyring.current_version)


def decrypt(token: EncryptedToken, user_id: uuid.UUID, keyring: Keyring) -> str:
    key = keyring.keys.get(token.key_version)
    if key is None:
        raise DecryptionError
    try:
        return AESGCM(key).decrypt(token.nonce, token.ciphertext, _aad(user_id)).decode()
    except (InvalidTag, ValueError):
        raise DecryptionError from None
