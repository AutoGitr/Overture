"""Radarr and Sonarr add exactly the title Overture asked for."""

lazy import json
lazy from typing import Literal

lazy import httpx2
lazy import pytest

lazy from overture.integrations.arr import ArrClient, ArrRequest
lazy from overture.utils.errors import PublicServiceError
lazy from tests.http_mock import mock_client_factory

_REQUEST = ArrRequest(root_folder="/media", quality_profile_id=4, search=False)


def _client(
    kind: Literal["radarr", "sonarr"], results: list[dict[str, object]]
) -> tuple[ArrClient, list[dict[str, object]]]:
    added: list[dict[str, object]] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST":
            added.append(json.loads(request.content))
            return httpx2.Response(201, json={})
        return httpx2.Response(200, json=results)

    factory, _transport = mock_client_factory(handle)
    client = ArrClient(
        kind=kind, base_url="http://arr.test", api_key="key", client_factory=factory
    )
    return client, added


@pytest.mark.parametrize(
    ("kind", "field"), [("radarr", "tmdbId"), ("sonarr", "tvdbId")]
)
async def test_add_skips_search_results_for_other_titles(
    kind: Literal["radarr", "sonarr"], field: str
) -> None:
    client, added = _client(
        kind, [{field: 999, "title": "Another"}, {field: 603, "title": "Wanted"}]
    )
    try:
        await client.add(603, _REQUEST)
    finally:
        await client.close()
    assert [(body[field], body["title"]) for body in added] == [(603, "Wanted")]
    assert added[0]["rootFolderPath"] == "/media"


async def test_add_refuses_when_no_result_has_the_id() -> None:
    client, added = _client("radarr", [{"tmdbId": 999, "title": "Another"}])
    try:
        with pytest.raises(PublicServiceError, match="does not know this title"):
            await client.add(603, _REQUEST)
    finally:
        await client.close()
    assert added == []
