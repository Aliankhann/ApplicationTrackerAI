"""sync list page offset: ids of the current list page already processed

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-23 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sync_state",
        sa.Column("list_page_offset", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("sync_state", "list_page_offset")
