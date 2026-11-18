"""Encrypted refresh token persistence, one row per user."""

import uuid
from dataclasses import dataclass

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OAuthToken, TokenStatus
from app.security.crypto import DecryptionError, EncryptedToken, Keyring, decrypt, encrypt


def save_refresh_token(
    session: Session, user_id: uuid.UUID, refresh_token: str, scopes: str, keyring: Keyring
) -> OAuthToken:
    """Upsert the user's token. Re-saving a revoked token makes it active again."""
    encrypted = encrypt(refresh_token, user_id, keyring)
    row = session.get(OAuthToken, user_id)
    if row is None:
        row = OAuthToken(user_id=user_id)
        session.add(row)
    row.refresh_token_enc = encrypted.ciphertext
    row.nonce = encrypted.nonce
    row.key_version = encrypted.key_version
    row.scopes = scopes
    row.status = TokenStatus.ACTIVE
    session.flush()
    return row


def load_refresh_token(session: Session, user_id: uuid.UUID, keyring: Keyring) -> str | None:
    row = session.get(OAuthToken, user_id)
    if row is None or row.status == TokenStatus.REVOKED:
        return None
    return decrypt(
        EncryptedToken(row.refresh_token_enc, row.nonce, row.key_version), user_id, keyring
    )


@dataclass(frozen=True)
class RotationResult:
    rotated: int
    failed_user_ids: tuple[uuid.UUID, ...]

    @property
    def failed(self) -> int:
        return len(self.failed_user_ids)


def rotate_all(session: Session, keyring: Keyring) -> RotationResult:
    """Re-encrypt every row not under the current key version; undecryptable rows are skipped."""
    stmt = (
        select(OAuthToken)
        .where(OAuthToken.key_version != keyring.current_version)
        .with_for_update()
    )
    rotated = 0
    failed: list[uuid.UUID] = []
    for row in session.scalars(stmt).all():
        old = EncryptedToken(row.refresh_token_enc, row.nonce, row.key_version)
        try:
            plaintext = decrypt(old, row.user_id, keyring)
        except DecryptionError:
            failed.append(row.user_id)
            continue
        new = encrypt(plaintext, row.user_id, keyring)
        row.refresh_token_enc = new.ciphertext
        row.nonce = new.nonce
        row.key_version = new.key_version
        rotated += 1
    session.flush()
    return RotationResult(rotated, tuple(failed))


def mark_revoked(session: Session, user_id: uuid.UUID) -> None:
    """Flag the user's token revoked; a no-op when the user has no token."""
    row = session.get(OAuthToken, user_id)
    if row is not None:
        row.status = TokenStatus.REVOKED
        session.flush()


def get_row(session: Session, user_id: uuid.UUID) -> OAuthToken | None:
    return session.get(OAuthToken, user_id)


def delete_token(session: Session, user_id: uuid.UUID) -> None:
    """Remove the encrypted token for good (disconnect)."""
    session.execute(sa_delete(OAuthToken).where(OAuthToken.user_id == user_id))
