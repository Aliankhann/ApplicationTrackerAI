"""digest_log and users.digest_enabled

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-18 23:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column("digest_enabled", sa.Boolean(), server_default="true", nullable=False),
    )
    op.create_table(
        "digest_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("digest_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('sending', 'sent', 'failed', 'skipped_empty')",
            name=op.f("ck_digest_log_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_digest_log_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_digest_log")),
        sa.UniqueConstraint("user_id", "digest_date", name="uq_digest_log_user_id_digest_date"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("digest_log")
    op.drop_column("users", "digest_enabled")
