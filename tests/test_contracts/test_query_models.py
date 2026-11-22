"""A query model is the only query parameter of its route.

FastAPI hands every query parameter to a query model, which forbids the ones
it does not name, so a parameter declared beside it is always refused.
"""

lazy from collections.abc import Iterator, Sequence
lazy from typing import Any

lazy from fastapi import FastAPI
lazy from fastapi.routing import APIRoute
lazy from pydantic import BaseModel


def _routes(routes: Sequence[Any]) -> Iterator[APIRoute]:
    """Every route, through the routers the app and each router include."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif (included := getattr(route, "original_router", None)) is not None:
            yield from _routes(included.routes)


def _is_model(annotation: object) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def test_a_query_model_is_its_routes_only_query_parameter(test_app: FastAPI) -> None:
    routes = list(_routes(test_app.routes))
    beside = [
        f"{sorted(route.methods or ())} {route.path}"
        for route in routes
        if len(params := route.dependant.query_params) > 1
        and any(_is_model(param.field_info.annotation) for param in params)
    ]
    assert len(routes) > 100
    assert beside == []
