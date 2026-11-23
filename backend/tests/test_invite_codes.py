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
    before = {i.id for i in all_invites(db_session)}
    assert run_cli(db_session) == 0
    assert run_cli(db_session, "--days", "30") == 0
    created = [i for i in all_invites(db_session) if i.id not in before]
    assert sorted(i.expires_at for i in created) == [
        NOW + timedelta(days=14),
        NOW + timedelta(days=30),
    ]


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


def mark_used(db: Session, invite: InviteCode, user: User) -> None:
    invite.used_at, invite.used_by_user_id = NOW, user.id
    db.flush()


HOLD = timedelta(minutes=10)
CLAIM = timedelta(hours=24)


def test_ac5_used_code_whose_user_was_deleted_still_counts(db_session: Session) -> None:
    baseline = repo.slots_in_use(db_session, NOW)
    user = make_user(db_session)
    invite = make_invite(db_session)
    mark_used(db_session, invite, user)
    assert repo.slots_in_use(db_session, NOW) == baseline + 1
    db_session.delete(user)
    db_session.flush()
    db_session.refresh(invite)
    assert invite.used_by_user_id is None
    assert repo.slots_in_use(db_session, NOW) == baseline + 1


def test_cap_counts_claims_and_unreferenced_users_but_not_holds_or_open_codes(
    db_session: Session,
) -> None:
    baseline = repo.slots_in_use(db_session, NOW)
    make_user(db_session)  # an allowlisted-style user: +1
    make_invite(db_session, days=1)  # available: not counted
    held = make_invite(db_session, days=1)
    assert repo.try_hold(db_session, held.id, "tok", NOW, HOLD) is repo.HoldResult.HELD
    assert repo.slots_in_use(db_session, NOW) == baseline + 1  # a hold does not count
    claimed = make_invite(db_session, days=1)
    pending = make_user(db_session)
    repo.try_hold(db_session, claimed.id, "tok2", NOW, HOLD)
    assert repo.claim(db_session, claimed.id, "tok2", pending.id, NOW, CLAIM)
    assert repo.slots_in_use(db_session, NOW) == baseline + 2  # the claim counts once
    assert repo.slots_in_use(db_session, NOW + CLAIM + HOLD) == baseline + 1  # lapsed claim: freed


def test_ac6_find_by_code_ignores_case_hyphens_spaces(db_session: Session) -> None:
    code = generate_code()
    invite = make_invite(db_session, code)
    messy = " " + code.lower().replace("-", " - ") + " "
    found = repo.find_by_code(db_session, messy)
    assert found is not None
    assert found.id == invite.id
    assert repo.find_by_code(db_session, code.replace("-", "")) is not None
    assert repo.find_by_code(db_session, generate_code()) is None


def test_hold_is_exclusive_refreshable_by_its_owner_and_reopens_after_expiry(
    db_session: Session,
) -> None:
    invite = make_invite(db_session)
    assert repo.try_hold(db_session, invite.id, "a", NOW, HOLD) is repo.HoldResult.HELD
    assert repo.try_hold(db_session, invite.id, "b", NOW, HOLD) is repo.HoldResult.IN_USE
    later = NOW + timedelta(minutes=9)
    assert repo.try_hold(db_session, invite.id, "a", later, HOLD) is repo.HoldResult.HELD
    assert repo.try_hold(db_session, invite.id, "b", NOW + HOLD, HOLD) is repo.HoldResult.IN_USE
    assert repo.try_hold(db_session, invite.id, "b", later + HOLD, HOLD) is repo.HoldResult.HELD


def test_hold_refuses_used_expired_revoked_codes_as_unavailable(db_session: Session) -> None:
    used, expired, revoked = make_invite(db_session), make_invite(db_session, days=-1), None
    mark_used(db_session, used, make_user(db_session))
    revoked = make_invite(db_session)
    assert repo.revoke(db_session, revoked.id, NOW)
    for invite in (used, expired, revoked):
        result = repo.try_hold(db_session, invite.id, "a", NOW, HOLD)
        assert result is repo.HoldResult.UNAVAILABLE


def test_claim_needs_the_holders_token_and_an_unexpired_hold(db_session: Session) -> None:
    invite, user = make_invite(db_session), make_user(db_session)
    repo.try_hold(db_session, invite.id, "a", NOW, HOLD)
    assert not repo.claim(db_session, invite.id, "b", user.id, NOW, CLAIM)
    assert not repo.claim(db_session, invite.id, "a", user.id, NOW + HOLD, CLAIM)
    assert repo.claim(db_session, invite.id, "a", user.id, NOW, CLAIM)
    assert not repo.claim(db_session, invite.id, "a", user.id, NOW, CLAIM)  # one winner


def test_finalize_uses_a_claim_even_after_it_lapsed_unless_revoked(db_session: Session) -> None:
    invite, user = make_invite(db_session, days=3), make_user(db_session)
    repo.try_hold(db_session, invite.id, "a", NOW, HOLD)
    repo.claim(db_session, invite.id, "a", user.id, NOW, CLAIM)
    assert repo.finalize(db_session, user.id, NOW + timedelta(hours=30))
    db_session.refresh(invite)
    assert invite.used_by_user_id == user.id and invite.claimed_by_user_id is None
    other, other_user = make_invite(db_session), make_user(db_session)
    repo.try_hold(db_session, other.id, "a", NOW, HOLD)
    repo.claim(db_session, other.id, "a", other_user.id, NOW, CLAIM)
    repo.revoke(db_session, other.id, NOW)
    assert not repo.finalize(db_session, other_user.id, NOW)


@pytest.mark.parametrize("raw", ["", "--  ", "AAAA", "A" * 31 + "1", "A" * 31 + "\u00e9", "A" * 33])
def test_malformed_codes_never_match_and_cannot_be_hashed(db_session: Session, raw: str) -> None:
    assert not is_well_formed(raw)
    assert repo.find_by_code(db_session, raw) is None
    with pytest.raises(ValueError):
        hash_code(raw)


def test_naive_now_is_rejected(db_session: Session) -> None:
    with pytest.raises(ValueError):
        repo.try_hold(db_session, uuid.uuid4(), "a", datetime(2026, 1, 1), HOLD)


# --- CLI: list and revoke -------------------------------------------------------------------


def run_admin(db: Session, *args: str) -> int:
    return cli.main(["invite", *args], lambda: nullcontext(db), lambda: NOW)


def test_cli_list_shows_id_prefix_and_state_but_never_the_code_or_hash(
    db_session: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    code = generate_code()
    invite = make_invite(db_session, code)
    held = make_invite(db_session)
    repo.try_hold(db_session, held.id, "a", NOW, HOLD)
    used = make_invite(db_session)
    mark_used(db_session, used, make_user(db_session))
    capsys.readouterr()
    assert run_admin(db_session, "list") == 0
    out = capsys.readouterr().out
    assert str(invite.id)[:8] in out and "available" in out
    assert "held" in out and "used" in out
    assert code not in out and normalize_code(code) not in out and invite.code_hash not in out
    assert str(invite.id) not in out  # prefix only


def test_cli_revoke_marks_a_held_code_unusable_and_is_idempotent(
    db_session: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    invite = make_invite(db_session)
    repo.try_hold(db_session, invite.id, "a", NOW, HOLD)
    assert run_admin(db_session, "revoke", str(invite.id)[:8]) == 0
    db_session.refresh(invite)
    assert invite.revoked_at == NOW and invite.held_until is None
    assert repo.try_hold(db_session, invite.id, "a", NOW, HOLD) is repo.HoldResult.UNAVAILABLE
    assert run_admin(db_session, "revoke", str(invite.id)[:8]) == 0
    capsys.readouterr()
    assert run_admin(db_session, "list") == 0
    assert "revoked" in capsys.readouterr().out


def test_cli_revoke_rejects_unknown_ambiguous_and_used_codes(
    db_session: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    used = make_invite(db_session)
    mark_used(db_session, used, make_user(db_session))
    assert run_admin(db_session, "revoke", "zzzzzzzz") == 1
    assert run_admin(db_session, "revoke", str(used.id)[:8]) == 1
    assert "already used" in capsys.readouterr().err
    assert run_admin(db_session, "revoke", "") == 1
