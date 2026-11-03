"""Free text in every schema is ``PublicText``, so serialising it redacts it."""

lazy import importlib
lazy import pkgutil
lazy import re
lazy from collections.abc import Mapping
lazy from typing import Any, TypeAliasType, get_args, get_origin

lazy import overture
lazy from overture.schemas.base import PublicText, StrictBaseModel

#: Field names that hold an error, a reason or a message: text a secret can reach.
FREE_TEXT = re.compile(r"(^|_)(error|errors|message|reason|detail|msg)$")


def _models() -> set[type[StrictBaseModel]]:
    for module in pkgutil.walk_packages(overture.__path__, "overture."):
        # Revisions and the Alembic environment import only under Alembic.
        if not module.name.startswith("overture.migrations"):
            importlib.import_module(module.name)
    found: set[type[StrictBaseModel]] = set()
    pending = [StrictBaseModel]
    while pending:
        for model in pending.pop().__subclasses__():
            if model not in found:
                found.add(model)
                pending.append(model)
    return found


def _bare_str(annotation: Any) -> bool:
    if annotation is PublicText:
        return False
    if annotation is str:
        return True
    if isinstance(annotation, TypeAliasType):
        return _bare_str(annotation.__value__)
    args = get_args(annotation)
    origin = get_origin(annotation)
    # A mapping's keys name what failed; only its values are the free text.
    if isinstance(origin, type) and issubclass(origin, Mapping):
        return _bare_str(args[1])
    return any(_bare_str(arg) for arg in args)


def test_free_text_fields_are_public_text() -> None:
    bare = sorted(
        f"{model.__module__}.{model.__qualname__}.{name}"
        for model in _models()
        for name, field in model.model_fields.items()
        if FREE_TEXT.search(name) and _bare_str(field.annotation)
    )

    assert bare == []


def test_public_text_is_redacted_however_it_was_filled() -> None:
    class Result(StrictBaseModel):
        state: str
        errors: dict[str, PublicText]

    result = Result(state="token=kept", errors={})
    result.errors["A"] = "GET /?api_key=hunter2 failed"

    assert result.model_dump(mode="json") == {
        "state": "token=kept",
        "errors": {"A": "GET /?api_key=[REDACTED] failed"},
    }
