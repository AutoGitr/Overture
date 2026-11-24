"""Build the database a release writes, to test upgrading it to the current schema.

``--version X.Y.Z`` writes the database of the code checked out, as
``scripts/release.sh`` does for each release before tagging it. ``--tag
vX.Y.Z`` checks an earlier release out into a temporary worktree and runs this
script again in that release's own environment. Either writes two databases
through the release's own models, each with one row in every table: in the
``empty`` one every field a row may leave empty is left so, and in the ``full``
one each is filled where the release's constraints admit it. Required fields
take the first value a constraint admits, and the rest their defaults. So the
rows hold what that release stores, such as JSON's ``null`` for a JSON field it
left empty, rather than what a test author pictured. Both are kept as SQL under
``tests/fixtures/databases/``, which
``tests/test_database/test_release_upgrades.py`` upgrades to the current schema.

"""

lazy import argparse
lazy import shutil
lazy import sqlite3
lazy import subprocess
lazy import sys
lazy import tempfile
lazy import tomllib
lazy from datetime import UTC, date, datetime
lazy from pathlib import Path
lazy from types import UnionType
lazy from typing import Any, get_args, get_origin

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "databases"


def _plain(annotation: Any) -> Any:
    """The type an optional field holds when it holds a value."""
    if get_origin(annotation) is UnionType:
        return next(arg for arg in get_args(annotation) if arg is not type(None))
    return annotation


def _value(column: Any, annotation: Any, ordinal: int) -> object:
    """A value of the column's type, told apart from other rows' by *ordinal*."""
    enums: list[str] | None = getattr(column.type, "enums", None)
    if enums:
        return enums[0]
    # JSON columns take any value, so the field says which it holds.
    python_type: Any = column.type.python_type
    if python_type is object:
        plain = _plain(annotation)
        python_type = get_origin(plain) or plain
    # Releases before typed JSON columns kept JSON as text under a ``_json`` name.
    if python_type is str and column.name.endswith("_json"):
        return "{}"
    # A NewType, such as a URL type, is stored as the type it wraps.
    while (wrapped := getattr(python_type, "__supertype__", None)) is not None:
        python_type = wrapped
    values: dict[type, object] = {
        str: f"value {ordinal}",
        int: ordinal,
        float: float(ordinal),
        bool: ordinal % 2 == 0,
        datetime: datetime(2026, 1, ordinal, tzinfo=UTC),
        date: date(2026, 1, ordinal),
        dict: {},
        list: [],
    }
    return values[python_type]


def _table_models(base: Any) -> dict[str, Any]:
    """Each table model a release registered, by its table's name.

    Importing ``overture.db`` registers them in every release, and only later
    ones list them, so they are found the same way in each.
    """
    found: dict[str, Any] = {}
    pending: list[type] = list(base.__subclasses__())
    while pending:
        model = pending.pop()
        pending.extend(model.__subclasses__())
        table: Any = vars(model).get("__table__")
        if table is not None:
            found[str(table.name)] = model
    return found


class _Table:
    """One table of a release, and the rows its model writes to it."""

    def __init__(self, table: Any, model: Any, mapper: Any) -> None:
        self.table = table
        self.model = model
        # A column may map to an attribute of another name (``payload`` for
        # ``payload_json``), which the model is built with.
        self.attribute = {
            column.name: mapper.get_property_by_column(column).key
            for column in table.columns
        }
        self.fields = {
            name: field
            for name, field in model.model_fields.items()
            if name in self.attribute.values()
        }

    def _needs_value(self, column: Any) -> bool:
        name = self.attribute[column.name]
        return (
            not column.nullable
            and column.default is None
            and column.server_default is None
            and column is not self.table.autoincrement_column
            and name in self.fields
            and self.fields[name].is_required()
        )

    def required(self, ordinal: int) -> dict[str, object]:
        """The fields a row must be given, told apart from others by *ordinal*."""
        return {
            self.attribute[column.name]: _value(
                column, self.fields[self.attribute[column.name]].annotation, ordinal
            )
            for column in self.table.columns
            if not column.foreign_keys and self._needs_value(column)
        }

    def references(
        self, inserted: dict[str, dict[str, object]]
    ) -> tuple[dict[str, object], dict[str, object]]:
        """The rows of other tables a row refers to: those it must, and may."""
        required: dict[str, object] = {}
        optional: dict[str, object] = {}
        for column in self.table.columns:
            if foreign := next(iter(column.foreign_keys), None):
                parent = inserted.get(foreign.column.table.name, {})
                target = optional if column.nullable else required
                target[self.attribute[column.name]] = parent.get(foreign.column.name)
        return required, optional

    def optional(self) -> dict[str, object]:
        """A value for each field a row may leave empty, other than a reference."""
        return {
            self.attribute[column.name]: _value(
                column, self.fields[self.attribute[column.name]].annotation, 2
            )
            for column in self.table.columns
            if column.nullable
            and not column.foreign_keys
            and self.attribute[column.name] in self.fields
        }

    def stored(self, row: Any) -> dict[str, object]:
        """What *row* holds, by column."""
        return {
            column.name: getattr(row, self.attribute[column.name])
            for column in self.table.columns
        }


#: The databases written of each release, by what their rows' optional fields hold.
VARIANTS = ("empty", "full")


def write(stem: Path) -> None:
    """Write each of a release's databases, as ``<stem>.<variant>.sql``."""
    for variant in VARIANTS:
        _write(stem.with_name(f"{stem.name}.{variant}.sql"), filled=variant == "full")


def _write(destination: Path, *, filled: bool) -> None:
    """Write one row to every table through the installed release's models.

    With *filled*, each field a row may leave empty holds a value where the
    release's constraints admit one.
    """
    # The release's own packages, importable only in its environment.
    from sqlalchemy.exc import IntegrityError  # noqa: PLC0415
    from sqlmodel import Session, SQLModel, create_engine, inspect  # noqa: PLC0415

    from overture.db import metadata  # noqa: PLC0415
    from overture.db.session import run_migrations  # noqa: PLC0415

    refusals: tuple[type[Exception], ...] = (IntegrityError,)
    try:
        from overture.db.ledger import LedgerRefusalError  # noqa: PLC0415 -- the release's own, as above
    except ImportError:
        pass  # A release before the asset ledger refuses through constraints alone.
    else:
        refusals = (IntegrityError, LedgerRefusalError)

    models = _table_models(SQLModel)
    path = Path(tempfile.mkdtemp()) / "release.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        run_migrations(connection)
    inserted: dict[str, dict[str, object]] = {}
    with Session(engine) as session:

        def admitted(model: Any, fields: dict[str, object], *, keep: bool) -> Any:
            """Insert a row of *fields*, kept or rolled back; ``None`` if refused.

            A release refuses a row through its constraints, and from the asset
            ledger on also by refusing the flush of an asset whose stored status
            its other rows contradict.
            """
            try:
                with session.begin_nested() as savepoint:
                    row = model(**fields)
                    session.add(row)
                    session.flush()
                    if not keep:
                        savepoint.rollback()
            except refusals:
                return None
            return row

        for table in metadata.sorted_tables:
            if (model := models.get(table.name)) is None:
                continue
            rows = _Table(table, model, inspect(model))
            references, may_reference = rows.references(inserted)
            # A row may need none of its optional references, or exactly one,
            # such as artwork owned by a title, a season or a collection.
            base = next(
                (
                    fields
                    for chosen in (
                        {},
                        *({name: ref} for name, ref in may_reference.items()),
                    )
                    if admitted(
                        model,
                        fields := {**rows.required(1), **references, **chosen},
                        keep=False,
                    )
                    is not None
                ),
                None,
            )
            if base is None:
                raise RuntimeError(f"No row of {table.name} is admitted")
            # A release's own rules refuse some values, such as a date in
            # another format, or a link beside an upload; a full row takes
            # each value in turn that its row still admits.
            fields = dict(base)
            for name, value in (rows.optional() if filled else {}).items():
                if admitted(model, {**fields, name: value}, keep=False) is not None:
                    fields[name] = value
            row = admitted(model, fields, keep=True)
            if row is None:
                raise RuntimeError(f"The {table.name} row is not admitted")
            inserted[table.name] = rows.stored(row)
        session.commit()
    engine.dispose()
    with sqlite3.connect(path) as database:
        destination.write_text("\n".join(database.iterdump()) + "\n")


def fixture(version: str) -> Path:
    """The stem the databases of release *version* are kept under."""
    FIXTURES.mkdir(parents=True, exist_ok=True)
    return FIXTURES / f"v{version}"


def _tool(name: str) -> str:
    """The full path of a command this script runs."""
    if (path := shutil.which(name)) is None:
        raise SystemExit(f"{name} is not installed")
    return path


def _release_uv(uv: str, worktree: Path) -> list[str]:
    """The uv a release pins, which its lockfile is checked with."""
    with (worktree / "pyproject.toml").open("rb") as project:
        pinned = tomllib.load(project).get("tool", {}).get("uv", {})
    version = pinned.get("required-version")
    return [uv, "tool", "run", "--from", f"uv=={version}", "uv"] if version else [uv]


def build(tag: str) -> Path:
    """Write the databases *tag* writes to its fixtures, with that release's code."""
    git, uv = _tool("git"), _tool("uv")
    destination = fixture(tag.removeprefix("v"))
    worktree = Path(tempfile.mkdtemp()) / tag
    subprocess.run(
        [git, "worktree", "add", "--detach", str(worktree), tag],
        cwd=ROOT,
        check=True,
    )
    try:
        subprocess.run(
            [
                *_release_uv(uv, worktree),
                "run",
                "--locked",
                "--directory",
                str(worktree),
                "python",
                str(Path(__file__).resolve()),
                "--write",
                str(destination),
            ],
            check=True,
        )
    finally:
        subprocess.run(
            [git, "worktree", "remove", "--force", str(worktree)],
            cwd=ROOT,
            check=True,
        )
        shutil.rmtree(worktree.parent, ignore_errors=True)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the database a release writes, to test upgrading it."
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--tag", help="an earlier release to build the database of")
    action.add_argument(
        "--version", help="the release the checked-out code is, to build its database"
    )
    action.add_argument("--write", type=Path, help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    if arguments.write is not None:
        write(arguments.write)
    elif arguments.version is not None:
        destination = fixture(arguments.version)
        write(destination)
        print(destination)
    else:
        print(build(arguments.tag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
