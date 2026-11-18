import base64
import os
import uuid
from collections.abc import Callable
from contextlib import nullcontext

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy.orm import Session

from app import cli
from app.config import Settings, get_settings
from app.models import OAuthToken, TokenStatus, User
from app.repositories import oauth_tokens
from app.security.crypto import (
    DecryptionError,
    EncryptedToken,
    Keyring,
    KeyringError,
    decrypt,
    encrypt,
    get_keyring,
    parse_keyring,
)


def _key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def _ring(*versions: int, current: int | None = None) -> Keyring:
    return parse_keyring(",".join(f"{v}:{_key()}" for v in versions), current)


USER = uuid.uuid4()


def _user(session: Session) -> uuid.UUID:
    user = User(google_sub=f"sub-{uuid.uuid4()}", email="u@example.test")
    session.add(user)
    session.flush()
    return user.id


def test_us20_ac1_round_trip() -> None:
    ring = _ring(1)
    assert decrypt(encrypt("tok-123", USER, ring), USER, ring) == "tok-123"


def test_us20_ac2_wrong_key_fails() -> None:
    enc = encrypt("tok", USER, _ring(1))
    with pytest.raises(DecryptionError):
        decrypt(enc, USER, _ring(1))


def test_us20_ac3_tampering_and_wrong_user_fail() -> None:
    ring = _ring(1)
    enc = encrypt("tok", USER, ring)
    bad_ct = EncryptedToken(bytes([enc.ciphertext[0] ^ 1]) + enc.ciphertext[1:], enc.nonce, 1)
    bad_nonce = EncryptedToken(enc.ciphertext, bytes([enc.nonce[0] ^ 1]) + enc.nonce[1:], 1)
    for bad in (bad_ct, bad_nonce):
        with pytest.raises(DecryptionError):
            decrypt(bad, USER, ring)
    with pytest.raises(DecryptionError):
        decrypt(enc, uuid.uuid4(), ring)
    with pytest.raises(DecryptionError):
        decrypt(EncryptedToken(enc.ciphertext, enc.nonce, 99), USER, ring)


def test_us20_ac4_encryptions_differ() -> None:
    ring = _ring(1)
    a, b = encrypt("tok", USER, ring), encrypt("tok", USER, ring)
    assert a.ciphertext != b.ciphertext
    assert a.nonce != b.nonce


@given(st.text())
def test_us20_ac5_round_trip_property(token: str) -> None:
    ring = parse_keyring(f"1:{base64.urlsafe_b64encode(bytes(32)).decode()}")
    assert decrypt(encrypt(token, USER, ring), USER, ring) == token


def test_us20_ac6_row_has_no_plaintext(db_session: Session) -> None:
    user_id = _user(db_session)
    ring = _ring(1, 2)
    token = "refresh-token-plaintext-value"  # noqa: S105
    oauth_tokens.save_refresh_token(db_session, user_id, token, "gmail.readonly", ring)
    row = db_session.get(OAuthToken, user_id)
    assert row is not None
    assert token.encode() not in row.refresh_token_enc
    assert row.key_version == 2
    assert oauth_tokens.load_refresh_token(db_session, user_id, ring) == token
    oauth_tokens.save_refresh_token(db_session, user_id, "second", "s", ring)
    assert oauth_tokens.load_refresh_token(db_session, user_id, ring) == "second"


@pytest.mark.parametrize(
    "raw,current",
    [
        ("1:" + base64.urlsafe_b64encode(b"short-secret-material").decode(), None),
        ("1:not*base64*secret!!", None),
        (f"1:{_key()},1:{_key()}", None),
        (f"1:{_key()}", 2),
        ("", None),
        (f"0:{_key()}", None),
    ],
)
def test_us20_ac7_bad_config_is_clear_and_leak_free(raw: str, current: int | None) -> None:
    with pytest.raises(KeyringError) as exc:
        parse_keyring(raw, current)
    for entry in raw.split(","):
        _, _, material = entry.partition(":")
        assert not material or material not in str(exc.value)
    assert exc.value.__cause__ is None


def test_us20_ac7_keyring_repr_hides_keys() -> None:
    key = _key()
    assert key not in repr(parse_keyring(f"1:{key}"))


def test_us20_ac8_revoked_token_loads_none(db_session: Session) -> None:
    user_id = _user(db_session)
    ring = _ring(1)
    row = oauth_tokens.save_refresh_token(db_session, user_id, "tok", "s", ring)
    row.status = TokenStatus.REVOKED
    db_session.flush()
    assert oauth_tokens.load_refresh_token(db_session, user_id, ring) is None
    assert oauth_tokens.load_refresh_token(db_session, uuid.uuid4(), ring) is None


def test_us21_ac9_old_version_still_decrypts() -> None:
    k1, k2 = _key(), _key()
    enc = encrypt("tok", USER, parse_keyring(f"1:{k1}"))
    both = parse_keyring(f"1:{k1},2:{k2}")
    assert both.current_version == 2
    assert decrypt(enc, USER, both) == "tok"


def _rotation_setup(session: Session) -> tuple[Keyring, Keyring, list[uuid.UUID]]:
    k1, k2 = _key(), _key()
    old, new = parse_keyring(f"1:{k1}"), parse_keyring(f"1:{k1},2:{k2}")
    ids = [_user(session) for _ in range(2)]
    for i, uid in enumerate(ids):
        oauth_tokens.save_refresh_token(session, uid, f"tok-{i}", "s", old)
    return old, new, ids


def test_us21_ac10_rotate_all(db_session: Session) -> None:
    _, new, ids = _rotation_setup(db_session)
    assert oauth_tokens.rotate_all(db_session, new).rotated == 2
    assert oauth_tokens.rotate_all(db_session, new).rotated == 0
    only_v2 = Keyring({2: new.keys[2]}, 2)
    assert oauth_tokens.load_refresh_token(db_session, ids[0], only_v2) == "tok-0"
    assert oauth_tokens.load_refresh_token(db_session, ids[1], only_v2) == "tok-1"


def test_us21_ac11_cli_rotate_prints_count(
    db_session: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    _, new, _ = _rotation_setup(db_session)
    factory: Callable[[], Keyring] = lambda: new  # noqa: E731
    code = cli.main(["tokens", "rotate"], lambda: nullcontext(db_session), keyring_factory=factory)
    assert code == 0
    assert capsys.readouterr().out.strip() == "rotated=2 failed=0"


@pytest.mark.parametrize("version", ["1000000", "9" * 5000, "abc", "-1", "0"])
def test_us20_ac7_version_out_of_range_rejected(version: str) -> None:
    with pytest.raises(KeyringError):
        parse_keyring(f"{version}:{_key()}")
    with pytest.raises(KeyringError):
        parse_keyring(f"1:{_key()}", version)


def test_us20_ac7_base64_junk_rejected() -> None:
    with pytest.raises(KeyringError):
        parse_keyring("1:" + _key()[:-1] + "!" + "\n")


def test_us20_ac7_settings_repr_hides_keys() -> None:
    key = _key()
    settings = Settings(token_encryption_keys=f"1:{key}")
    assert key not in repr(settings)
    assert key not in str(settings)


def test_us20_get_keyring_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEYS", f"1:{_key()},2:{_key()}")
    monkeypatch.setenv("TOKEN_ENCRYPTION_CURRENT_VERSION", "1")
    ring = get_keyring()
    assert ring.current_version == 1
    assert set(ring.keys) == {1, 2}


def test_us20_bad_current_version_env_does_not_break_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOKEN_ENCRYPTION_CURRENT_VERSION", "abc")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEYS", f"1:{_key()}")
    get_settings()
    with pytest.raises(KeyringError):
        get_keyring()


def test_us20_resave_revoked_token_becomes_active(db_session: Session) -> None:
    user_id = _user(db_session)
    ring = _ring(1)
    row = oauth_tokens.save_refresh_token(db_session, user_id, "old", "s", ring)
    row.status = TokenStatus.REVOKED
    db_session.flush()
    oauth_tokens.save_refresh_token(db_session, user_id, "new", "s", ring)
    assert oauth_tokens.load_refresh_token(db_session, user_id, ring) == "new"


def test_us21_rotate_all_skips_bad_row(db_session: Session) -> None:
    _, new, ids = _rotation_setup(db_session)
    bad = db_session.get(OAuthToken, ids[0])
    assert bad is not None
    bad.refresh_token_enc = b"\x00" * len(bad.refresh_token_enc)
    db_session.flush()
    result = oauth_tokens.rotate_all(db_session, new)
    assert (result.rotated, result.failed, result.failed_user_ids) == (1, 1, (ids[0],))
    assert oauth_tokens.load_refresh_token(db_session, ids[1], new) == "tok-1"


def test_us21_cli_reports_failed_rows(
    db_session: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    _, new, ids = _rotation_setup(db_session)
    bad = db_session.get(OAuthToken, ids[0])
    assert bad is not None
    bad.nonce = bytes(12)
    db_session.flush()
    code = cli.main(
        ["tokens", "rotate"], lambda: nullcontext(db_session), keyring_factory=lambda: new
    )
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out.strip() == "rotated=1 failed=1"
    assert str(ids[0]) in captured.err


def test_us21_cli_keyring_error(capsys: pytest.CaptureFixture[str]) -> None:
    key = _key()

    def bad_ring() -> Keyring:
        return parse_keyring(f"1:{key},1:{key}")

    code = cli.main(["tokens", "rotate"], lambda: nullcontext(None), keyring_factory=bad_ring)  # type: ignore[arg-type]
    captured = capsys.readouterr()
    assert code == 1
    assert key not in captured.err + captured.out
    assert "duplicate" in captured.err
