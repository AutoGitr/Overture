"""What the API answers besides each route's own response model.

Every failure has an :class:`ErrorResponse` body, except a request FastAPI
refuses before the route runs, whose 422 lists each issue. The schema states
both, so a client generated from it reads every answer it can get.
"""

lazy from collections.abc import Mapping
lazy from typing import Any, cast

lazy from pydantic.json_schema import models_json_schema

lazy from ..schemas.common import ErrorResponse, ValidationErrorResponse

type Responses = dict[int | str, dict[str, Any]]

_SCHEMAS = "#/components/schemas/"


def errors(descriptions: Mapping[int, str]) -> Responses:
    """Failures with an :class:`ErrorResponse` body, each described."""
    return {
        status: {"model": ErrorResponse, "description": description}
        for status, description in descriptions.items()
    }


#: What a route that needs signing in answers, besides its own responses.
AUTH_RESPONSES = errors(
    {
        401: "Not signed in, or the API key is not valid",
        403: "An API key asked for a change, or the CSRF token is missing",
    }
)
#: What an OIDC route answers while OIDC sign-in is not configured.
OIDC_OFF = errors({404: "OIDC login is disabled"})
#: What a route that counts sign-in attempts answers past the limit.
TOO_MANY_ATTEMPTS = errors({429: "Too many sign-in attempts"})
#: What a route answers while a setting the integration it uses needs is unset.
NOT_CONFIGURED = errors({409: "A setting it needs is not set"})
#: What a route answers when a media server's API cannot do what it asks.
SERVER_CANNOT = errors({409: "A media server cannot do what it asks"})
#: What a route that saves an uploaded image answers once it is gone.
UPLOAD_GONE = errors({409: "The uploaded image is no longer kept"})
#: What a route that reads or changes a media server answers besides.
MEDIA_SERVER_RESPONSES = errors(
    {
        409: "No media server is configured",
        502: "A media server failed the request",
        503: "A media server is unavailable",
    }
)

_ERROR = {"$ref": f"{_SCHEMAS}{ErrorResponse.__name__}"}
#: What FastAPI answers, before validation, for a body it cannot decode.
_UNDECODABLE_BODY = {
    "description": "The body is not text in the declared encoding",
    "content": {"application/json": {"schema": _ERROR}},
}
#: What a route answers once a body passes its size limit. Starlette refuses
#: a body whose Content-Length is too large with plain text before the route
#: runs; one sent without a length is cut off as it is read, and its 413 is
#: an error like any other.
_TOO_LARGE = {
    "description": "The body is larger than the route accepts",
    "content": {
        "application/json": {"schema": _ERROR},
        "text/plain": {"schema": {"type": "string"}},
    },
}
#: What a route answers when what its path names does not exist.
_NOT_FOUND = {
    "description": "Nothing has the ID or key the path names",
    "content": {"application/json": {"schema": _ERROR}},
}
#: A request the schema refuses lists each issue; one a rule refuses says why.
_UNPROCESSABLE = {
    "description": "The request breaks the schema or a rule",
    "content": {
        "application/json": {
            "schema": {
                "anyOf": [
                    _ERROR,
                    {"$ref": f"{_SCHEMAS}{ValidationErrorResponse.__name__}"},
                ]
            }
        }
    },
}
#: FastAPI's own 422 body, which Overture's handler replaces.
_FASTAPI_VALIDATION = ("HTTPValidationError", "ValidationError")


def _require_tags(node: object, components: dict[str, Any]) -> None:
    """Mark each discriminator's property required on the schemas it maps.

    Pydantic reads the tag of a discriminated union even when the model gives
    it a default, which its schema then leaves optional.
    """
    if isinstance(node, list):
        for child in cast("list[object]", node):
            _require_tags(child, components)
    elif isinstance(node, dict):
        fields = cast("dict[str, object]", node)
        if isinstance(found := fields.get("discriminator"), dict):
            discriminator = cast("dict[str, Any]", found)
            tag: str = discriminator["propertyName"]
            refs: dict[str, str] = discriminator.get("mapping", {})
            for ref in refs.values():
                target: dict[str, Any] = components[ref.removeprefix(_SCHEMAS)]
                required: list[str] = target.get("required", [])
                target["required"] = sorted({*required, tag})
        for child in fields.values():
            _require_tags(child, components)


def declare_framework_answers(schema: dict[str, Any]) -> dict[str, Any]:
    """Add to *schema* what every route answers whatever it declares.

    FastAPI documents its own 422 body, not the one Overture sends, and no
    answer for a body it cannot decode or one too large, or a path that names
    nothing.
    """
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    _require_tags(schema, components)
    for name in _FASTAPI_VALIDATION:
        components.pop(name, None)
    _, definitions = models_json_schema(
        [(ValidationErrorResponse, "serialization")],
        ref_template=f"{_SCHEMAS}{{model}}",
    )
    components.update(definitions["$defs"])
    for path, operations in schema["paths"].items():
        for operation in operations.values():
            responses = operation["responses"]
            if "422" in responses:
                responses["422"] = _UNPROCESSABLE
            if "requestBody" in operation:
                responses.setdefault("400", _UNDECODABLE_BODY)
                responses.setdefault("413", _TOO_LARGE)
            if "{" in path:
                responses.setdefault("404", _NOT_FOUND)
    return schema
