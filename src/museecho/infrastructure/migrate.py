from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

BASE_TABLES = frozenset(
    {
        "analysis_jobs",
        "access_grants",
        "encrypted_audio",
        "track_analyses",
        "section_events",
        "chord_events",
        "time_series",
        "evidence",
        "explanations",
    }
)
USER_MEMORY_TABLES = frozenset(
    {"users", "user_sessions", "account_tokens", "auth_attempts", "saved_analyses"}
)


def upgrade_database(database: Path, *, config_path: Path | None = None) -> None:
    """Upgrade a database, safely adopting schemas created before Alembic was active."""

    repository_root = Path(__file__).resolve().parents[3]
    if config_path is not None:
        selected_config = config_path
    else:
        configured_path = os.environ.get("MUSEECHO_ALEMBIC_CONFIG", "").strip()
        candidates = [Path(configured_path)] if configured_path else []
        candidates.extend((Path("/app/alembic.ini"), repository_root / "alembic.ini"))
        selected_config = next(
            (candidate for candidate in candidates if candidate.is_file()),
            repository_root / "alembic.ini",
        )
    config = Config(str(selected_config))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database.resolve().as_posix()}")

    tables = _tables(database)
    if "alembic_version" not in tables and tables:
        missing_base = BASE_TABLES - tables
        present_memory = USER_MEMORY_TABLES & tables
        if missing_base:
            raise RuntimeError(
                "unversioned database does not match the MuseEcho base schema; "
                f"missing tables: {', '.join(sorted(missing_base))}"
            )
        if present_memory and present_memory != USER_MEMORY_TABLES:
            missing_memory = USER_MEMORY_TABLES - tables
            raise RuntimeError(
                "unversioned database has a partial user-memory schema; "
                f"missing tables: {', '.join(sorted(missing_memory))}"
            )
        command.stamp(config, "0002" if present_memory else "0001")
    command.upgrade(config, "head")


def _tables(database: Path) -> frozenset[str]:
    if not database.exists():
        return frozenset()
    connection = sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
        return frozenset(row[0] for row in rows)
    finally:
        connection.close()


def main() -> None:
    data_root = Path(os.environ.get("MUSEECHO_DATA_ROOT", "/data"))
    upgrade_database(data_root / "museecho.db")


if __name__ == "__main__":
    main()
