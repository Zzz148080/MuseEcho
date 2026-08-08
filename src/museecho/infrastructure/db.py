from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, Engine, create_engine, event
from sqlalchemy.engine import Dialect, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """Persist UTC as naive SQLite values and restore aware UTC datetimes."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must be timezone-aware UTC")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def ensure_sqlite_parent(database_url: str) -> None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        return
    Path(url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def create_museecho_engine(database_url: str, **kwargs: Any) -> Engine:
    ensure_sqlite_parent(database_url)
    url = make_url(database_url)
    is_file_sqlite = (
        url.drivername.startswith("sqlite") and bool(url.database) and url.database != ":memory:"
    )
    engine = create_engine(database_url, echo=False, **kwargs)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection: Any, _: Any) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=5000")
                if is_file_sqlite:
                    cursor.execute("PRAGMA journal_mode=WAL")
            finally:
                cursor.close()

    return engine


def create_session_factory(
    database_url: str = "sqlite:///data/museecho.db",
) -> sessionmaker[Session]:
    engine = create_museecho_engine(database_url)
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
