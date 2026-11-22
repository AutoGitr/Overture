"""Whatever a media server replies, Overture reads it or says the server failed.

A reply is input Overture does not control. Every parser of one returns a
value or raises :class:`MediaServerError`, and a provider whose server replies
with anything shaped like the wire types lists what the replies hold or raises
that error: never another exception, never a hang.
"""

lazy import contextlib
lazy import inspect
lazy import json
lazy from collections.abc import Callable
lazy from functools import partial
lazy from typing import Any

lazy import httpx2
lazy import pytest
lazy from hypothesis import HealthCheck, given, settings
lazy from hypothesis import strategies as st
lazy from pydantic import SecretStr

lazy from overture.config import Settings
lazy from overture.domain import ServerType
lazy from overture.integrations.http import request_with_retry
lazy from overture.media_servers import wire
lazy from overture.media_servers.emby.client import EmbyClient
lazy from overture.media_servers.emby.provider import EmbyProvider
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.media_servers.jellyfin.client import JellyfinClient
lazy from overture.media_servers.jellyfin.provider import JellyfinProvider
lazy from overture.media_servers.plex.client import PlexClient
lazy from overture.media_servers.plex.provider import PlexProvider
lazy from tests.http_mock import keep_configured_plex_url, mock_client_factory
lazy from tests.media_servers import TEST_SERVER_ID, configure, server_of

#: Every parser of a whole reply: each public function of ``wire`` that takes
#: the decoded payload alone.
PARSERS: dict[str, Callable[[object], object]] = {
    name: function
    for name, function in vars(wire).items()
    if inspect.isfunction(function)
    and not name.startswith("_")
    and list(inspect.signature(function).parameters) == ["payload"]
}
#: Requests one listing may send before the server stops answering, so a
#: listing that never ends fails instead of hanging.
MAX_REQUESTS = 40

_JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats() | st.text(),
    lambda children: st.lists(children) | st.dictionaries(st.text(), children),
    max_leaves=25,
)
_PLEX = st.one_of(
    st.fixed_dictionaries({"MediaContainer": st.from_type(wire.PlexContainer)}),
    st.fixed_dictionaries({"MediaContainer": st.from_type(wire.PlexSectionsContainer)}),
)
_MEDIA_BROWSER = st.one_of(
    st.from_type(wire.MediaBrowserResponse),
    st.from_type(wire.MediaBrowserSections),
    st.lists(st.from_type(wire.MediaBrowserSection), max_size=5),
)


def _json(reply: object) -> bool:
    """Whether JSON can carry *reply*: no server sends an infinite number."""
    try:
        json.dumps(reply, allow_nan=False)
    except ValueError:
        return False
    return True


#: Replies shaped like what each kind of server sends, field types included.
REPLIES = {
    ServerType.PLEX: _PLEX.filter(_json),
    ServerType.JELLYFIN: _MEDIA_BROWSER.filter(_json),
    ServerType.EMBY: _MEDIA_BROWSER.filter(_json),
}
_FUZZ = settings(
    # The configuration and patches are set up once per test; examples
    # share them, and each builds its own provider.
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)


def test_every_parser_is_fuzzed() -> None:
    assert {"plex_page", "media_browser_page", "plex_resources"} <= set(PARSERS)


@pytest.mark.parametrize("name", sorted(PARSERS))
@_FUZZ
@given(payload=st.one_of(_JSON, _PLEX, _MEDIA_BROWSER))
def test_a_reply_is_read_or_refused_as_a_server_failure(
    name: str, payload: object
) -> None:
    with contextlib.suppress(MediaServerError):
        PARSERS[name](payload)


def _provider(
    kind: ServerType, app_config: Settings, handler: Callable[..., httpx2.Response]
) -> PlexProvider | JellyfinProvider | EmbyProvider:
    factory, _transport = mock_client_factory(handler)
    server = server_of(app_config, kind)
    common: dict[str, Any] = {
        "server": server,
        "server_id": TEST_SERVER_ID,
        "app_config": app_config,
    }
    if kind is ServerType.PLEX:
        client = PlexClient(
            server=server, app_config=app_config, client_factory=factory
        )
        return PlexProvider(**common, client=client)
    if kind is ServerType.JELLYFIN:
        return JellyfinProvider(
            **common, client=JellyfinClient(server=server, client_factory=factory)
        )
    return EmbyProvider(
        **common, client=EmbyClient(server=server, client_factory=factory)
    )


@pytest.fixture
def offline_retries(monkeypatch: pytest.MonkeyPatch, app_config: Settings) -> None:
    """Retry at once, and keep Plex from asking plex.tv for a better address."""
    configure(app_config, url="https://server.test")
    configure(app_config, api_key=SecretStr("test-secret"))
    monkeypatch.setattr(
        "overture.media_servers.http_client.request_with_retry",
        partial(request_with_retry, retry_delays=(0, 0)),
    )
    monkeypatch.setattr(PlexClient, "resolve_secure_url", keep_configured_plex_url)


@pytest.mark.usefixtures("offline_retries")
@pytest.mark.parametrize("kind", list(REPLIES))
@_FUZZ
@given(data=st.data())
async def test_a_provider_lists_what_replies_hold_or_says_the_server_failed(
    kind: ServerType, app_config: Settings, data: st.DataObject
) -> None:
    sent = 0

    def reply(_request: httpx2.Request) -> httpx2.Response:
        nonlocal sent
        sent += 1
        if sent > MAX_REQUESTS:
            return httpx2.Response(503)
        return httpx2.Response(200, json=data.draw(REPLIES[kind]))

    configure(app_config, type=kind)
    provider = _provider(kind, app_config, reply)
    try:
        for listing in (
            provider.get_sections,
            provider.list_collections,
            lambda: _pages(provider),
        ):
            sent = 0
            with contextlib.suppress(MediaServerError):
                await listing()
    finally:
        await provider.close()


async def _pages(provider: PlexProvider | JellyfinProvider | EmbyProvider) -> None:
    async for _page in provider.iter_items():
        pass
