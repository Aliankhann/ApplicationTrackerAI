"""Database engine, session factory, and declarative base."""

from collections.abc import Iterator
from datetime import datetime

from sqlalchemy import DateTime, MetaData, create_engine, func
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import Settings, get_settings

# Stable constraint names so Alembic autogenerate produces predictable migrations.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def build_engine(settings: Settings) -> Engine:
    """ "serverless" (Vercel): every function invocation may be a new process behind a
    transaction-mode pooler (Neon/Supabase pooled URL), so no app-side pool and no server-side
    prepared statements. The app keeps no session-level database state across transactions."""
    if settings.db_pool_mode == "serverless":
        return create_engine(
            settings.database_url, poolclass=NullPool, connect_args={"prepare_threshold": None}
        )
    return create_engine(settings.database_url, pool_pre_ping=True)


engine = build_engine(get_settings())
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
