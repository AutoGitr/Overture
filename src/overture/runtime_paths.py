"""Persistent runtime filesystem locations."""

lazy from pathlib import Path

FRONTEND_DIR = Path(__file__).parent / "frontend"


def database_path(config_dir: Path) -> Path:
    """Return the SQLite database file kept in ``config_dir``."""
    return config_dir / "overture.db"


def database_url(config_dir: Path) -> str:
    """Return the SQLAlchemy URL of the database kept in ``config_dir``."""
    return f"sqlite+aiosqlite:///{database_path(config_dir).as_posix()}"
