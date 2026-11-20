"""Every release's database upgrades to the current schema, keeping every row valid.

The databases under ``tests/fixtures/databases/`` were written by each release's
own code (``scripts/release_database.py``), so they hold what Overture stores
rather than what a test author pictured.
"""

lazy import sqlite3
lazy from contextlib import closing
lazy from pathlib import Path

lazy import pytest
lazy from sqlmodel import CheckConstraint, select

lazy from overture.db import metadata
lazy from overture.db.session import Database
lazy from overture.db.tables import table_models
lazy from overture.utils.threads import owned_thread
lazy from scripts.release_database import VARIANTS
lazy from scripts.release_metadata import project_version


def _release(path: Path) -> tuple[tuple[int, ...], str]:
    """A database's release, as numbers to order by, and its variant."""
    version, variant = path.name.removesuffix(".sql").rsplit(".", 1)
    return tuple(int(part) for part in version[1:].split(".")), variant


RELEASES = sorted(
    (Path(__file__).parents[1] / "fixtures" / "databases").glob("v*.sql"),
    key=_release,
)


def test_every_release_has_each_database_and_the_current_one_too() -> None:
    written = {_release(path) for path in RELEASES}
    versions = {version for version, _ in written}
    current = tuple(int(part) for part in project_version().split("."))
    assert current in versions, (
        "Run `uv run python -m scripts.release_database --version "
        f"{project_version()}`; scripts/release.sh does it for each release"
    )
    assert written == {
        (version, variant) for version in versions for variant in VARIANTS
    }


def _restore(release: Path, path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(release.read_text())


def _broken_checks(path: Path) -> list[str]:
    """Name each CHECK constraint a stored row breaks, as the models declare them."""
    with closing(sqlite3.connect(path)) as connection:
        return [
            f"{table.name}.{constraint.name}"
            for table in metadata.sorted_tables
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
            and connection.execute(
                f"SELECT count(*) FROM {table.name} "  # noqa: S608 -- the metadata's own table and constraint
                f"WHERE NOT ({constraint.sqltext})"
            ).fetchone()
            != (0,)
        ]


@pytest.mark.parametrize(
    "release", RELEASES, ids=lambda path: path.name.removesuffix(".sql")
)
async def test_a_release_database_upgrades_and_every_row_stays_valid(
    release: Path, tmp_path: Path
) -> None:
    path = tmp_path / "overture.db"
    await owned_thread(_restore, release, path)
    database = Database(f"sqlite+aiosqlite:///{path}")
    try:
        # Starting migrates the database to the current schema, as it does
        # for anyone upgrading; the release being made is already there.
        await database.initialize()
        async with database.read_session() as session:
            for model in table_models():
                # Loading builds every row as the current models read it.
                (await session.exec(select(model))).all()
    finally:
        await database.close()
    assert await owned_thread(_broken_checks, path) == []
