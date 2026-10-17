"""Check consumed operations against the bundled provider specifications."""

lazy import json
lazy import re
lazy from functools import cache
lazy from pathlib import Path
lazy from typing import Any, cast

lazy import httpx2
lazy import pytest
lazy from jsonschema import ValidationError, validate


def _nullable(value: Any) -> Any:
    if isinstance(value, list):
        return [_nullable(item) for item in cast("list[Any]", value)]
    if not isinstance(value, dict):
        return value
    result = {
        key: _nullable(item) for key, item in cast("dict[str, Any]", value).items()
    }
    if result.pop("nullable", False):
        return {"anyOf": [result, {"type": "null"}]}
    return result


@cache
def _document(provider: str) -> dict[str, Any]:
    path = Path(__file__).resolve().parents[1] / "openapi" / f"{provider}-openapi.json"
    try:
        content = path.read_text()
    except FileNotFoundError:
        pytest.fail(
            f"Missing upstream OpenAPI specification for {provider} at '{path}'. "
            "Run `uv run python -m scripts.provider_specs` to prepare "
            "provider specifications.",
            pytrace=False,
        )
    return _nullable(json.loads(content))


class ProviderSpec:
    def __init__(self, provider: str, prefix: str = "") -> None:
        self.provider = provider
        self.prefix = prefix
        self.document = _document(provider)

    def resolve(self, schema: dict[str, Any]) -> dict[str, Any]:
        while "$ref" in schema:
            result = self.document
            for key in schema["$ref"].removeprefix("#/").split("/"):
                result = result[key]
            schema = result
        return schema

    def validate(self, value: object, schema: dict[str, Any]) -> None:
        try:
            validate(value, {**schema, "components": self.document["components"]})
        except ValidationError as exc:
            raise AssertionError(f"{list(exc.absolute_path)}: {exc.message}") from None

    def _parameter(self, value: str, schema: dict[str, Any]) -> None:
        schema = self.resolve(schema)
        converted: object = value
        kind = self.resolve(schema.get("anyOf", [schema])[0]).get("type")
        match kind:
            case "integer":
                converted = int(value)
            case "boolean":
                assert value in {"true", "false"}
                converted = value == "true"
            case "array":
                converted = value.split(",")
            case _:
                pass
        self.validate(converted, schema)

    def response(
        self,
        request: httpx2.Request,
        template: str,
        payload: object = None,
        *,
        status: int = 200,
    ) -> httpx2.Response:
        path = request.url.path.removeprefix(self.prefix)
        match = re.fullmatch(re.sub(r"\{[^}]+\}", "([^/]+)", template), path)
        assert match is not None, (path, template)
        path_values = dict(
            zip(re.findall(r"\{([^}]+)\}", template), match.groups(), strict=True)
        )
        path_item = self.document["paths"][template]
        operation = path_item[request.method.lower()]
        query = dict(request.url.params)
        # Plex documents these as global parameters in API Info, not per operation.
        if self.provider == "plex":
            for name, kind in {
                "includeFields": "string",
                "includeChildren": "integer",
                "X-Plex-Container-Start": "integer",
                "X-Plex-Container-Size": "integer",
            }.items():
                if name in query:
                    assert name in self.document["info"]["description"]
                    self._parameter(query.pop(name), {"type": kind})
        objects: list[dict[str, Any]] = []
        for raw in [*path_item.get("parameters", []), *operation.get("parameters", [])]:
            parameter = self.resolve(raw)
            name, location = parameter["name"], parameter["in"]
            schema = parameter.get("schema", {})
            if location == "query" and schema.get("type") == "object":
                objects.append(schema)
                continue
            values = (
                path_values
                if location == "path"
                else query
                if location == "query"
                else request.headers
            )
            if parameter.get("required"):
                assert name in values, name
            if name in values:
                self._parameter(values[name], schema)
                if location == "query":
                    query.pop(name)
        if objects:
            for schema in objects:
                self.validate(query, schema)
        else:
            assert not query, f"Undocumented query parameters: {query}"
        response = self.resolve(operation["responses"][str(status)])
        schema = response.get("content", {}).get("application/json", {}).get("schema")
        if schema is not None:
            self.validate(payload, schema)
        return (
            httpx2.Response(status, json=payload)
            if payload is not None
            else httpx2.Response(status)
        )
