import logging
import os

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

logger = logging.getLogger("app.database")


def normalize_database_url(url: str) -> str:
    """Append the async driver for SQLite and PostgreSQL URLs.

    Accepts plain ``sqlite:///...`` and ``postgresql://...`` (or
    ``postgres://...``) URLs and rewrites them to their async equivalents
    (``sqlite+aiosqlite`` and ``postgresql+asyncpg``). URLs that already carry
    an async driver are left untouched.
    """
    if url.startswith("sqlite+aiosqlite://"):
        return url
    if url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _prepare_sqlite_directory(url: str) -> None:
    """Create the parent directory for a file-backed SQLite database."""
    if not url.startswith("sqlite"):
        return

    prefix = "sqlite+aiosqlite:///"
    if prefix not in url:
        return

    path = url.split(prefix, 1)[1]
    if path and path != ":memory:":
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)


_normalized_url = normalize_database_url(settings.database_url)
_prepare_sqlite_directory(_normalized_url)

_is_sqlite = _normalized_url.startswith("sqlite")

_engine_kwargs: dict = {
    "pool_pre_ping": True,
    "future": True,
}
if not _is_sqlite:
    # Production Postgres (often behind PgBouncer / a managed proxy):
    # - recycle connections so a DB restart doesn't leave stale handles
    # - cap the pool so 2 gunicorn workers + polling can't exhaust
    #   max_connections
    # - disable asyncpg's prepared-statement cache: it breaks under
    #   PgBouncer transaction pooling ("prepared statement already exists" /
    #   generic DBAPIError).
    _engine_kwargs.update(
        {
            "pool_size": 5,
            "max_overflow": 10,
            "pool_timeout": 30,
            "pool_recycle": 1800,
            "connect_args": {"prepared_statement_cache_size": 0},
        }
    )

engine = create_async_engine(
    _normalized_url,
    **_engine_kwargs,
)


if _is_sqlite:
    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):  # noqa: ANN001
        """Enable concurrency-safe SQLite settings for multi-worker use.

        WAL lets readers and the single writer proceed concurrently, and a busy
        timeout makes concurrent writers wait instead of failing with
        "database is locked".
        """
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def _ensure_user_columns() -> None:
    """Best-effort additive migration for databases created before a column existed."""
    async with engine.connect() as conn:
        tables = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_table_names()
        )
        if "users" not in tables:
            return

        existing = await conn.run_sync(
            lambda sync_conn: {
                column["name"] for column in inspect(sync_conn).get_columns("users")
            }
        )
        statements = []
        if "is_approved" not in existing:
            statements.append(
                "ALTER TABLE users ADD COLUMN is_approved BOOLEAN DEFAULT TRUE NOT NULL"
            )
        if "totp_secret" not in existing:
            statements.append("ALTER TABLE users ADD COLUMN totp_secret VARCHAR(64)")
        if "pending_totp_secret" not in existing:
            statements.append(
                "ALTER TABLE users ADD COLUMN pending_totp_secret VARCHAR(64)"
            )
        if "totp_enabled" not in existing:
            statements.append(
                "ALTER TABLE users ADD COLUMN totp_enabled BOOLEAN DEFAULT FALSE NOT NULL"
            )

        for statement in statements:
            await conn.execute(text(statement))
        await conn.commit()


async def _ensure_text_status_columns() -> None:
    """Widen legacy VARCHAR status columns to TEXT (Postgres only).

    ``work_items.status`` used to be ``VARCHAR(128)`` and ``audit_logs.status``
    ``VARCHAR(64)``. A full error message (e.g. the ~150-char openpyxl ``.xls``
    message) made the ``UPDATE work_items`` itself fail with
    ``StringDataRightTruncationError``, crashing the background task before it
    could mark itself done/failed — the UI then polled ``processing`` forever.
    SQLite never enforces VARCHAR lengths, so this is a Postgres-only fix.
    Each statement runs on its own connection so one failure cannot poison
    the others; concurrent workers racing the same ALTER simply no-op.
    """
    if _is_sqlite:
        return
    statements = [
        "ALTER TABLE work_items ALTER COLUMN status TYPE TEXT",
        "ALTER TABLE audit_logs ALTER COLUMN status TYPE TEXT",
    ]
    for statement in statements:
        try:
            async with engine.connect() as conn:
                await conn.execute(text(statement))
                await conn.commit()
        except Exception as exc:  # pragma: no cover - best effort at startup
            logger.warning("Status column migration skipped (%s): %r", statement, exc)


async def init_db() -> None:
    """Create all tables that do not yet exist."""
    from app.core import models  # noqa: F401  (register models on Base)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _ensure_user_columns()
    await _ensure_text_status_columns()
