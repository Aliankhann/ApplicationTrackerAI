"""application_threads link table, per-message classifications, needs-review cards

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-26 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "application_threads",
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["thread_id"], ["email_threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("thread_id"),
    )
    op.create_index(
        "ix_application_threads_user_id_application_id",
        "application_threads",
        ["user_id", "application_id"],
    )
    op.execute(
        "INSERT INTO application_threads (thread_id, application_id, user_id) "
        "SELECT source_thread_id, id, user_id FROM applications WHERE source_thread_id IS NOT NULL"
    )
    op.add_column(
        "applications",
        sa.Column("needs_review", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column("applications", sa.Column("suggested_label", sa.String(32), nullable=True))
    op.add_column(
        "applications", sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("classifications", sa.Column("gmail_message_id", sa.String(64), nullable=True))
    op.create_unique_constraint(
        "uq_classifications_thread_id_gmail_message_id",
        "classifications",
        ["thread_id", "gmail_message_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_classifications_thread_id_gmail_message_id", "classifications", type_="unique"
    )
    op.drop_column("classifications", "gmail_message_id")
    op.drop_column("applications", "dismissed_at")
    op.drop_column("applications", "suggested_label")
    op.drop_column("applications", "needs_review")
    op.drop_index("ix_application_threads_user_id_application_id", table_name="application_threads")
    op.drop_table("application_threads")
