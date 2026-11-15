"""Type guards for parsed JSON, which the scripts read without a schema."""

lazy from typing import Any, TypeIs


def is_object(value: object) -> TypeIs[dict[str, Any]]:
    """Return whether a parsed JSON value is an object."""
    return isinstance(value, dict)


def is_array(value: object) -> TypeIs[list[Any]]:
    """Return whether a parsed JSON value is an array."""
    return isinstance(value, list)
