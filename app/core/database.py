import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


def _prepare_sqlite_directory(url: str) -> None:
    """Create the parent directory for a file-backed SQLite database."""
    if not url.startswith("sqlite"):
        return

    prefix = "sqlite:///"
    if prefix not in url:
        return

    path = url.split(prefix, 1)[1]
    if path and path != ":memory:":
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)


_prepare_sqlite_directory(settings.database_url)

_connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


def _ensure_user_columns() -> None:
    """Best-effort additive migration for databases created before a column existed."""
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("users")}
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

    if statements:
        with engine.begin() as conn:
            for statement in statements:
                conn.execute(text(statement))


def init_db() -> None:
    """Create all tables that do not yet exist."""
    from app.core import models  # noqa: F401  (register models on Base)

    Base.metadata.create_all(bind=engine)
    _ensure_user_columns()
