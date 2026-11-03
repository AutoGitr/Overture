"""MDBList list resolution is bounded, authenticated, and fixed to one origin."""

lazy import httpx2
lazy import pytest
lazy from pydantic import SecretStr

lazy from overture.config import Settings
lazy from overture.domain import MediaType
lazy from overture.integrations.mdblist import MDBListClient, mdblist_identifier
lazy from overture.utils.errors import PublicServiceError
lazy from tests.http_mock import mock_client_factory


@pytest.mark.parametrize(
    "value",
    [
        "https://evil.test/lists/user/list",
        "https://mdblist.com/lists/user/list?apikey=secret",
        "user/../list",
        "/lists/1",
        "https://mdblist.com@evil.test/lists/user/list",
        "user/list%2Fsecret",
    ],
)
def test_identifiers_cannot_change_origin_or_carry_credentials(value: str) -> None:
    with pytest.raises(ValueError, match="Use an MDBList"):
        mdblist_identifier(value)


async def test_list_pages_preserve_source_rank_and_deduplicate(
    app_config: Settings,
) -> None:
    app_config.MDBLIST_API_KEY = SecretStr("private-key")
    offsets: list[str] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        assert request.url.host == "api.mdblist.com"
        assert request.url.path == "/lists/user/list/items"
        assert request.url.params["apikey"] == "private-key"
        offset = request.url.params["offset"]
        offsets.append(offset)
        movies = (
            [{"id": i} for i in range(1, 1001)]
            if offset == "0"
            else [{"id": 1000}, {"id": 1001}]
        )
        return httpx2.Response(200, json={"movies": movies, "shows": []})

    factory, _transport = mock_client_factory(handle)
    client = MDBListClient(app_config=app_config, client_factory=factory)
    try:
        assert await client.tmdb_ids(
            "https://mdblist.com/lists/user/list/", MediaType.MOVIE
        ) == list(range(1, 1002))
        assert offsets == ["0", "1000"]
    finally:
        await client.close()


@pytest.mark.parametrize(
    "payload",
    [
        {"error": "Unavailable"},
        {"movies": [{"id": -1}]},
        {"movies": [{"id": 1}] * 1000},
    ],
)
async def test_invalid_or_repeated_pages_fail_before_membership_changes(
    app_config: Settings, payload: object
) -> None:
    app_config.MDBLIST_API_KEY = SecretStr("private-key")
    factory, _transport = mock_client_factory(
        lambda _: httpx2.Response(200, json=payload)
    )
    client = MDBListClient(app_config=app_config, client_factory=factory)
    try:
        with pytest.raises(PublicServiceError):
            await client.tmdb_ids("42", MediaType.MOVIE)
    finally:
        await client.close()


async def test_missing_key_is_actionable_without_a_network_request(
    app_config: Settings,
) -> None:
    client = MDBListClient(app_config=app_config)
    with pytest.raises(PublicServiceError, match="MDBLIST_API_KEY"):
        await client.tmdb_ids("42", MediaType.SHOW)
    await client.close()
