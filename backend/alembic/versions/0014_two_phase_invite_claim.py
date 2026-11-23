"""two-phase invite claim: holds, claims, revocation, setup completion

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-23 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ACTIONS = (
    "action in ('login', 'logout', 'gmail_connected', 'gmail_disconnected', "
    "'account_deleted', 'followups_enabled', 'data_exported')"
)
NEW_ACTIONS = (
    "action in ('login', 'logout', 'gmail_connected', 'gmail_disconnected', "
    "'account_deleted', 'followups_enabled', 'data_exported', 'account_setup_completed')"
)
CONSTRAINT = op.f("ck_audit_log_action_valid")


def upgrade() -> None:
    op.add_column("invite_codes", sa.Column("held_until", sa.DateTime(timezone=True)))
    op.add_column("invite_codes", sa.Column("hold_token_hash", sa.String(length=64)))
    op.add_column("invite_codes", sa.Column("claimed_by_user_id", sa.Uuid()))
    op.add_column("invite_codes", sa.Column("claimed_until", sa.DateTime(timezone=True)))
    op.add_column("invite_codes", sa.Column("revoked_at", sa.DateTime(timezone=True)))
    op.create_foreign_key(
        op.f("fk_invite_codes_claimed_by_user_id_users"),
        "invite_codes",
        "users",
        ["claimed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("users", sa.Column("setup_completed_at", sa.DateTime(timezone=True)))
    # Everyone who exists today already finished signing in: they are not pending.
    op.execute("UPDATE users SET setup_completed_at = created_at")
    op.drop_constraint(CONSTRAINT, "audit_log", type_="check")
    op.create_check_constraint(CONSTRAINT, "audit_log", NEW_ACTIONS)


def downgrade() -> None:
    op.execute("DELETE FROM audit_log WHERE action = 'account_setup_completed'")
    op.drop_constraint(CONSTRAINT, "audit_log", type_="check")
    op.create_check_constraint(CONSTRAINT, "audit_log", OLD_ACTIONS)
    op.drop_column("users", "setup_completed_at")
    op.drop_constraint(
        op.f("fk_invite_codes_claimed_by_user_id_users"), "invite_codes", type_="foreignkey"
    )
    op.drop_column("invite_codes", "revoked_at")
    op.drop_column("invite_codes", "claimed_until")
    op.drop_column("invite_codes", "claimed_by_user_id")
    op.drop_column("invite_codes", "hold_token_hash")
    op.drop_column("invite_codes", "held_until")
