"""sync pause on rate limits: paused status, consecutive_rate_limits counter

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-23 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STATUSES = "status in ('idle', 'running', 'error', 'revoked')"
NEW_STATUSES = "status in ('idle', 'running', 'error', 'revoked', 'paused')"


def _set_status_check(expression: str) -> None:
    name = op.f("ck_sync_state_status_valid")
    op.drop_constraint(name, "sync_state", type_="check")
    op.create_check_constraint(name, "sync_state", expression)


def upgrade() -> None:
    op.add_column(
        "sync_state",
        sa.Column("consecutive_rate_limits", sa.Integer(), server_default="0", nullable=False),
    )
    _set_status_check(NEW_STATUSES)


def downgrade() -> None:
    op.execute("UPDATE sync_state SET status = 'idle' WHERE status = 'paused'")
    _set_status_check(OLD_STATUSES)
    op.drop_column("sync_state", "consecutive_rate_limits")
