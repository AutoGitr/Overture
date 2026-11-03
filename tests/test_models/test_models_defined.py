"""Every application module's imports resolve and its Pydantic models build."""

lazy import importlib
lazy import pkgutil
lazy import types
lazy from collections.abc import Iterator

lazy import pytest
lazy from pydantic import BaseModel

lazy import overture
lazy import scripts


def _application_modules() -> Iterator[str]:
    for package in (overture, scripts):
        prefix = f"{package.__name__}."
        for module in pkgutil.walk_packages(package.__path__, prefix):
            if not module.name.startswith("overture.migrations"):
                yield module.name


def _subclasses(cls: type[BaseModel]) -> Iterator[type[BaseModel]]:
    for subclass in cls.__subclasses__():
        yield subclass
        yield from _subclasses(subclass)


def _application_models() -> list[type[BaseModel]]:
    for name in _application_modules():
        importlib.import_module(name)
    return sorted(
        {
            model
            for model in _subclasses(BaseModel)
            if model.__module__.startswith("overture.")
            # A parametrized generic is built from its origin, checked itself.
            and not model.__pydantic_generic_metadata__["origin"]
        },
        key=lambda model: f"{model.__module__}.{model.__qualname__}",
    )


@pytest.mark.parametrize("name", list(_application_modules()))
def test_module_lazy_imports_resolve(name: str) -> None:
    """A broken lazy import fails here, not on the first request that uses it."""
    for value in vars(importlib.import_module(name)).values():
        if isinstance(value, types.LazyImportType):
            value.resolve()


@pytest.mark.parametrize(
    "model", _application_models(), ids=lambda model: model.__qualname__
)
def test_model_is_fully_defined(model: type[BaseModel]) -> None:
    """Every annotation's lazy import resolves when Pydantic builds the model."""
    model.model_rebuild(raise_errors=True)
