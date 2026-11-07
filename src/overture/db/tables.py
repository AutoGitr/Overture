"""Every table Overture keeps, found from the models rather than listed by hand."""

lazy import importlib
lazy import inspect
lazy import pkgutil

lazy from sqlmodel import SQLModel, Table

lazy from . import models


def table_models() -> list[type[SQLModel]]:
    """Every table model, by table name; its docstring says what its rows are."""
    for module in pkgutil.iter_modules(models.__path__):
        importlib.import_module(f"{models.__name__}.{module.name}")
    found: list[type[SQLModel]] = []
    pending = list(SQLModel.__subclasses__())
    while pending:
        model = pending.pop()
        pending.extend(model.__subclasses__())
        if "__table__" in vars(model) and model.__module__.startswith(models.__name__):
            found.append(model)
    return sorted(found, key=lambda model: table_of(model).name)


def table_of(model: type[SQLModel]) -> Table:
    """The table a table model maps."""
    table: Table = vars(model)["__table__"]
    return table


def table_description(model: type[SQLModel]) -> str:
    """The first line of the model's own docstring, never one it inherits."""
    doc = vars(model).get("__doc__")
    return inspect.cleandoc(doc).split("\n", 1)[0] if isinstance(doc, str) else ""
