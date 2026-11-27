# ruff: noqa: E501
"""0017 backfills application_threads from applications.source_thread_id and downgrades cleanly."""

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError

from alembic import command
from app.config import get_settings
from tests.test_applications import _alembic_config


def test_ac_backfills_one_link_row_per_source_thread_and_downgrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = make_url(get_settings().database_url)
    name = f"tracker_migtest_{uuid.uuid4().hex[:12]}"
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except ProgrammingError:
        admin.dispose()
        pytest.skip("CREATE DATABASE not permitted: run ALTER USER tracker CREATEDB")
    try:
        url = base.set(database=name).render_as_string(False)
        monkeypatch.setenv("DATABASE_URL", url)
        get_settings.cache_clear()
        cfg = _alembic_config()
        command.upgrade(cfg, "0016")
        engine = create_engine(url)
        user, with_thread, orphan = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        thread = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                text(
                    "insert into users (id, google_sub, email) values (:i, 'sub', 'u@example.test')"
                ),
                {"i": user},
            )
            conn.execute(
                text(
                    "insert into email_threads (id, user_id, gmail_thread_id, subject, from_domain,"
                    " snippet, first_message_at, last_message_at, last_sender_is_user, message_count)"
                    " values (:t, :u, 'g1', 's', 'd', 'x', now(), now(), false, 1)"
                ),
                {"t": thread, "u": user},
            )
            for app_id, source in ((with_thread, thread), (orphan, None)):
                conn.execute(
                    text(
                        "insert into applications (id, user_id, status, source_thread_id,"
                        " last_activity_at, status_locked) values"
                        " (:a, :u, 'applied', :s, now(), false)"
                    ),
                    {"a": app_id, "u": user, "s": source},
                )
        command.upgrade(cfg, "0017")
        with engine.connect() as conn:
            links = conn.execute(
                text("select application_id, thread_id, user_id from application_threads")
            ).all()
            flags = conn.execute(
                text("select needs_review, suggested_label, dismissed_at from applications limit 1")
            ).one()
        assert links == [(with_thread, thread, user)]
        assert tuple(flags) == (False, None, None)
        command.downgrade(cfg, "0016")
        with engine.connect() as conn:
            tables = (
                conn.execute(
                    text(
                        "select table_name from information_schema.tables where table_schema='public'"
                    )
                )
                .scalars()
                .all()
            )
        assert "application_threads" not in tables
        engine.dispose()
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
        get_settings.cache_clear()
