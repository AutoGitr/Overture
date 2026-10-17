"""Typed wrappers for the SQL types migrations share with the models.

``sqlmodel.sql.sqltypes.AutoString`` derives from ``TypeDecorator`` without a
type argument, so every column built from it reads as ``Column[Unknown]``. The
stored value is a string, and saying so here keeps that one third-party gap in
a single place instead of in every revision that mentions a text column.
"""

lazy from typing import cast

lazy from sqlalchemy.types import TypeEngine
lazy from sqlmodel.sql.sqltypes import AutoString


def auto_string(length: int | None = None) -> TypeEngine[str]:
    """Return SQLModel's ``AutoString``, typed as the string column it is."""
    return cast("TypeEngine[str]", AutoString(length=length))
