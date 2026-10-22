"""Alembic migration scripts for the Overture database."""

lazy from pathlib import Path

lazy from alembic.script import ScriptDirectory

lazy from overture.db.session import alembic_config

_VERSIONS = Path(__file__).resolve().parent / "versions"


def versions_at_head() -> str:
    """Return the revision id of the current head.

    Read from the scripts themselves so a test asserting "the database is at
    head" keeps meaning that after the next migration is added.
    """
    revision = ScriptDirectory.from_config(alembic_config()).get_current_head()
    if revision is None:
        raise RuntimeError("no migration head found")
    return revision


__all__ = ["versions_at_head"]
