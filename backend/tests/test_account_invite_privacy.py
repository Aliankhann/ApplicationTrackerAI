"""A deleted user's email must not survive in invite_codes (US-80)."""

from app.models import InviteCode
from tests.test_account import CONFIRM, _keyring, connected  # noqa: F401  (autouse keyring)
from tests.test_sessions import T0, Env, env  # noqa: F401


def test_invite_row_does_not_keep_deleted_users_email(env: Env) -> None:  # noqa: F811
    world, w = connected(env)
    invite = InviteCode(
        code_hash="h" * 32,
        expires_at=T0,
        created_for_email=world.user.email,
        used_by_user_id=world.user.id,
        used_at=T0,
    )
    env.db.add(invite)
    env.db.flush()
    assert w.client.request("DELETE", "/me", json=CONFIRM).status_code == 200
    env.db.refresh(invite)
    assert invite.created_for_email is None


def test_unused_invite_made_for_deleted_users_email_is_cleared(env: Env) -> None:  # noqa: F811
    """An unredeemed invite created for the same address must not keep it either."""
    world, w = connected(env)
    spare = InviteCode(
        code_hash="s" * 32,
        expires_at=T0,
        created_for_email=world.user.email.upper(),
    )
    env.db.add(spare)
    env.db.flush()
    assert w.client.request("DELETE", "/me", json=CONFIRM).status_code == 200
    env.db.refresh(spare)
    assert spare.created_for_email is None
