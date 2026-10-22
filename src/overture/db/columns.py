"""Enum columns shared by the persistence models.

These keep the mapping from a :mod:`overture.domain` enum to its stored form in
one place: values (not member names) are persisted, rows load back as enum
members, and the set of values a column accepts is enforced by the database
rather than only by the code that writes it.
"""

lazy import types
lazy from collections.abc import Sequence
lazy from enum import StrEnum
lazy from typing import Any, cast, get_args, get_origin

lazy from sqlalchemy import CheckConstraint, Table, event, inspect
lazy from sqlmodel import Enum as SAEnum
lazy from sqlmodel import SQLModel


def _enum_values(enum_type: type[StrEnum]) -> list[str]:
    """Return the values SQLAlchemy should persist for *enum_type*."""
    return [member.value for member in enum_type]


def enum_type(enum_cls: type[StrEnum]) -> type[Any]:
    """Return an SAEnum type storing *enum_cls* members by value.

    The database constraint comes from :func:`enum_columns`, which names it.
    """
    return cast(
        "type[Any]",
        SAEnum(
            enum_cls,
            native_enum=False,
            create_constraint=False,
            values_callable=_enum_values,
        ),
    )


def _enum_annotation(annotation: Any) -> type[StrEnum] | None:
    """Return the :class:`StrEnum` an annotation resolves to, if any."""
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        return annotation
    if get_origin(annotation) is types.UnionType:
        for arg in get_args(annotation):
            if isinstance(arg, type) and issubclass(arg, StrEnum):
                return arg
    return None


def enum_columns(model: type[SQLModel]) -> None:
    """Make a table model's enum columns hold their enums, in Python and in SQL.

    Every enum column gets a CHECK constraint, ``ck_<table>_<column>``,
    admitting its values. Table models skip Pydantic validation, so a plain
    string handed to the constructor would sit in the attribute until the
    database round-tripped it - close enough to work, different enough to
    surprise; constructor arguments are coerced to the enum instead.
    """
    table = inspect(model).local_table
    if not isinstance(table, Table):
        raise TypeError(f"{model.__name__} is not mapped to a table")
    enum_fields = {
        name: enum_cls
        for name, field in model.model_fields.items()
        if (enum_cls := _enum_annotation(field.annotation)) is not None
    }
    for name, enum_cls in enum_fields.items():
        values = ", ".join(f"'{member.value}'" for member in enum_cls)
        table.append_constraint(
            CheckConstraint(f"{name} IN ({values})", name=f"ck_{table.name}_{name}")
        )

    def _coerce(
        _target: object, _args: Sequence[object], kwargs: dict[str, Any]
    ) -> None:
        for name, enum_cls in enum_fields.items():
            value = kwargs.get(name)
            if value is not None and not isinstance(value, enum_cls):
                kwargs[name] = enum_cls(value)

    event.listen(model, "init", _coerce)
