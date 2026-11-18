import base64
import uuid
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import cli
from app.config import Settings
from app.models import InviteCode, User
from app.repositories import invite_codes as repo
from app.security.invite_codes import generate_code, hash_code, is_well_formed, normalize_code

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def run_cli(db: Session, *args: str) -> int:
    return cli.main(["invite", "create", *args], lambda: nullcontext(db), lambda: NOW)


def all_invites(db: Session) -> list[InviteCode]:
    return list(db.scalars(select(InviteCode)))


def make_invite(db: Session, code: str | None = None, days: int = 1) -> InviteCode:
    return repo.create(db, hash_code(code or generate_code()), NOW + timedelta(days=days))


def make_user(db: Session) -> User:
    user = User(google_sub=uuid.uuid4().hex, email="u@example.com")
    db.add(user)
    db.flush()
    return user


def set_cap(monkeypatch: pytest.MonkeyPatch, cap: int) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(max_users=cap))


def test_ac1_cli_prints_code_once_and_stores_only_hash(
    db_session: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_cli(db_session) == 0
    out = capsys.readouterr().out
    code = out.split("Invite code: ")[1].split()[0]
    assert out.count(code) == 1
    row = all_invites(db_session)[-1]
    assert row.code_hash == hash_code(code)
    assert row.code_hash != code
    assert len(row.code_hash) == 64


def test_ac2_ten_thousand_codes_distinct_and_at_least_128_bits() -> None:
    codes = [generate_code() for _ in range(10_000)]
    assert len(set(codes)) == 10_000
    for code in codes:
        assert len(code.split("-")) == 8
        raw = normalize_code(code)
        assert len(base64.b32decode(raw)) * 8 >= 128


def test_ac3_expiry_defaults_to_14_days_and_follows_days(db_session: Session) -> None:
    assert run_cli(db_session) == 0
    assert run_cli(db_session, "--days", "30") == 0
    default, custom = all_invites(db_session)[-2:]
    assert default.expires_at == NOW + timedelta(days=14)
    assert custom.expires_at == NOW + timedelta(days=30)


@pytest.mark.parametrize("days", ["0", "91", "-1", "abc"])
def test_ac3_days_outside_range_exits_nonzero(db_session: Session, days: str) -> None:
    before = len(all_invites(db_session))
    assert run_cli(db_session, "--days", days) != 0
    assert len(all_invites(db_session)) == before


def test_ac4_email_lowercased_and_validated(db_session: Session) -> None:
    assert run_cli(db_session, "--email", "Some.One@Example.COM") == 0
    assert all_invites(db_session)[-1].created_for_email == "some.one@example.com"
    before = len(all_invites(db_session))
    assert run_cli(db_session, "--email", "not-an-email") != 0
    assert len(all_invites(db_session)) == before


def test_ac5_cli_at_cap_exits_nonzero_and_writes_no_row(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_invite(db_session)
    set_cap(monkeypatch, repo.slots_in_use(db_session, NOW))
    before = len(all_invites(db_session))
    assert run_cli(db_session) != 0
    assert len(all_invites(db_session)) == before


def test_ac5_used_code_whose_user_was_deleted_still_counts(db_session: Session) -> None:
    baseline = repo.slots_in_use(db_session, NOW)
    user = make_user(db_session)
    invite = make_invite(db_session)
    assert repo.mark_used(db_session, invite.id, user.id, NOW)
    assert repo.slots_in_use(db_session, NOW) == baseline + 1
    db_session.delete(user)
    db_session.flush()
    db_session.refresh(invite)
    assert invite.used_by_user_id is None
    assert repo.slots_in_use(db_session, NOW) == baseline + 1


def test_ac5_unreferenced_users_and_pending_codes_count_expired_do_not(
    db_session: Session,
) -> None:
    baseline = repo.slots_in_use(db_session, NOW)
    make_user(db_session)
    make_invite(db_session, days=1)
    make_invite(db_session, days=-1)
    assert repo.slots_in_use(db_session, NOW) == baseline + 2


def test_ac6_find_redeemable_ignores_case_hyphens_spaces(db_session: Session) -> None:
    code = generate_code()
    invite = make_invite(db_session, code)
    messy = " " + code.lower().replace("-", " - ") + " "
    found = repo.find_redeemable(db_session, messy, NOW)
    assert found is not None
    assert found.id == invite.id
    assert repo.find_redeemable(db_session, code.replace("-", ""), NOW) is not None


def test_ac6_find_redeemable_none_for_used_expired_unknown(db_session: Session) -> None:
    used_code, expired_code = generate_code(), generate_code()
    used = make_invite(db_session, used_code)
    repo.mark_used(db_session, used.id, make_user(db_session).id, NOW)
    make_invite(db_session, expired_code, days=-1)
    assert repo.find_redeemable(db_session, used_code, NOW) is None
    assert repo.find_redeemable(db_session, expired_code, NOW) is None
    assert repo.find_redeemable(db_session, generate_code(), NOW) is None


def test_ac7_mark_used_true_first_time_false_second(db_session: Session) -> None:
    invite = make_invite(db_session)
    user = make_user(db_session)
    assert repo.mark_used(db_session, invite.id, user.id, NOW) is True
    assert repo.mark_used(db_session, invite.id, user.id, NOW) is False


@pytest.mark.parametrize("raw", ["", "--  ", "AAAA", "A" * 31 + "1", "A" * 31 + "\u00e9", "A" * 33])
def test_malformed_codes_never_match_and_cannot_be_hashed(db_session: Session, raw: str) -> None:
    assert not is_well_formed(raw)
    assert repo.find_redeemable(db_session, raw, NOW) is None
    with pytest.raises(ValueError):
        hash_code(raw)


def test_naive_now_is_rejected(db_session: Session) -> None:
    with pytest.raises(ValueError):
        repo.find_redeemable(db_session, generate_code(), datetime(2026, 1, 1))
