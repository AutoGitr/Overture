"""Every operation the API offers answers as its schema says, whatever it is asked.

Schemathesis generates requests from the OpenAPI schema itself, so a new
route is fuzzed the day it is added: no response may be a server error, and
every response must have the status, headers and body the schema declares.
Changes run against the test database and the test media servers, which no
request reaches, so a job they start fails as it would with every server
offline. ``FUZZ_EXAMPLES`` asks for more examples, as the weekly run does.
"""

# Schemathesis types its checks and schema over a ``Case`` it leaves generic,
# so their types are partly unknown to pyright.
# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
# pyright: reportUntypedFunctionDecorator=false

lazy from collections.abc import Iterator
lazy from typing import Any

lazy import pytest
lazy import schemathesis
lazy from fastapi import FastAPI
lazy from hypothesis import HealthCheck, settings
lazy from schemathesis.checks import not_a_server_error
lazy from schemathesis.core.mutations import OperatorKind
lazy from schemathesis.generation import GenerationMode
lazy from schemathesis.generation.meta import (
    CoveragePhaseData,
    CoverageScenario,
    FuzzingPhaseData,
)
lazy from schemathesis.specs.openapi.checks import (
    allow_header_conformance,
    ignored_auth,
    negative_data_rejection,
    positive_data_acceptance,
    unsupported_method,
)
lazy from starlette.testclient import TestClient

lazy from overture.utils.http_security import CSRF_COOKIE, SESSION_COOKIE

#: Checks that hold Overture to what it does not do, each with why.
NOT_CHECKED = [
    # The fuzzer is signed in with a session cookie, which the check cannot
    # take away to try a request without credentials; test_router_contracts
    # sends every operation that needs signing in without them.
    ignored_auth,
    # Authentication answers before routing, so an undeclared method sent with
    # a wrong API key is refused with 401 rather than told 405.
    unsupported_method,
    # Starlette lists in ``Allow`` the methods of the first route of a path,
    # and each method of a path is a route of its own.
    allow_header_conformance,
    # A declared 502 or 503 is a server's or integration's answer, passed on;
    # Overture's own failure is a 500, which the test checks itself.
    not_a_server_error,
    # A rule no schema can state, such as one field or another, refuses a
    # request the schema allows; the test checks that only such rules do.
    positive_data_acceptance,
]
#: The issue type of a refusal by a validator Overture writes, which states a
#: rule the schema cannot. Any other issue is a constraint the schema omits.
RULE = "value_error"

#: Operations left out, each with why.
NOT_FUZZED = {
    # Signing out would leave every later example refused as signed out;
    # tests/test_auth covers it.
    "/api/auth/logout",
}
#: The operation whose own answer to a wrong password is 401.
SIGN_IN = "/api/auth/login"

#: Every operation of the app's own schema.
schema = schemathesis.pytest.from_fixture("api_schema").exclude(path=list(NOT_FUZZED))
#: Sections fuzzed as tests of their own, so parallel workers share the run;
#: every other section is fuzzed together.
SECTIONS = {
    "collections": r"^/api/collections(/|$)",
    "library": r"^/api/(library|art|themes|media-server)(/|$)",
    "catalog_and_sync": r"^/api/(catalog|tmdb|auth|sync)(/|$)",
}


@pytest.fixture
def api_schema(test_app: FastAPI) -> Any:
    """The schema of the app the tests run."""
    return schemathesis.openapi.from_dict(test_app.openapi())


@pytest.fixture
def running_client(
    test_app: FastAPI, session_token: str, csrf_pair: tuple[str, str]
) -> Iterator[TestClient]:
    """A signed-in client of the app started as it runs, and stopped after.

    Stopping it waits for the jobs the requests started, as a restart does.
    """
    with TestClient(test_app) as client:
        client.cookies.set(SESSION_COOKIE, session_token)
        client.cookies.set(CSRF_COOKIE, csrf_pair[1])
        yield client


def _changes_types_only(case: Any) -> bool:
    """Whether a negative case only gave values another JSON type.

    Pydantic reads a value of another type where it can, such as ``0`` for
    ``false`` or ``"5"`` for ``5``, so such a request may be accepted; the
    schema names the types Overture writes and asks for.
    """
    data = case.meta.phase.data
    if isinstance(data, CoveragePhaseData) and (
        data.scenario is CoverageScenario.INCORRECT_TYPE
    ):
        return True
    mutations = data.mutations if isinstance(data, FuzzingPhaseData) else ()
    return bool(mutations) and all(
        mutation.operator is OperatorKind.CHANGE_TYPE for mutation in mutations
    )


def _answers_as_its_schema_says(
    case: Any, running_client: TestClient, auth_headers: dict[str, str]
) -> None:
    # Signed in as the web app is, with its CSRF header, so a refusal is the
    # route's own and not the CSRF check's.
    request = case.as_transport_kwargs(base_url="", headers=auth_headers)
    # A cookie the schema names is the client's to send, as a browser does,
    # except a generated session or CSRF token, which would sign it out.
    running_client.cookies.update(
        {
            name: value
            for name, value in (request.pop("cookies", None) or {}).items()
            if name not in {SESSION_COOKIE, CSRF_COOKIE}
        }
    )
    # Schemathesis passes a raw body as ``data``, which httpx2 names ``content``.
    if isinstance(request.get("data"), bytes | str):
        request["content"] = request.pop("data")
    response = running_client.request(**request)

    case.validate_response(
        response,
        excluded_checks=[
            *NOT_CHECKED,
            *([negative_data_rejection] if _changes_types_only(case) else []),
        ],
    )
    assert response.status_code != 500, response.text
    # Only a generated API key or password may be refused: any other 401
    # means an example signed the fuzzer out, and the rest prove nothing.
    if "x-api-key" not in {name.lower() for name in request["headers"]}:
        assert response.status_code != 401 or case.operation.path == SIGN_IN
    if response.status_code == 422 and case.meta.generation.mode is (
        GenerationMode.POSITIVE
    ):
        detail = response.json()["detail"]
        issues = detail if isinstance(detail, list) else []
        assert {issue["type"] for issue in issues} <= {RULE}, issues


def _fuzz(operations: Any) -> Any:
    """A test fuzzing *operations*."""

    def test(
        case: Any, running_client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        _answers_as_its_schema_says(case, running_client, auth_headers)

    return operations.parametrize()(
        settings(
            suppress_health_check=[
                # The authenticated client is set up once per test; examples
                # share it.
                HealthCheck.function_scoped_fixture,
                # A collection rule nests unions told apart by a tag, which
                # generation meets by discarding the drafts that miss it.
                HealthCheck.filter_too_much,
                HealthCheck.too_slow,
            ],
        )(test)
    )


test_collections_answer_as_their_schema_says = _fuzz(
    schema.include(path_regex=SECTIONS["collections"])
)
test_library_answers_as_its_schema_says = _fuzz(
    schema.include(path_regex=SECTIONS["library"])
)
test_catalog_and_sync_answer_as_their_schema_says = _fuzz(
    schema.include(path_regex=SECTIONS["catalog_and_sync"])
)
test_every_other_operation_answers_as_its_schema_says = _fuzz(
    schema.exclude(path_regex="|".join(SECTIONS.values()))
)
