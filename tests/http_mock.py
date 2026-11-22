"""Reusable, recording HTTP mock transport and factory for tests."""

lazy from collections.abc import Callable, Coroutine
lazy from typing import Unpack, override

lazy import httpx2

lazy from overture.integrations.http import ClientFactory, ClientOptions

type MockHandler = (
    Callable[[httpx2.Request], httpx2.Response]
    | Callable[[httpx2.Request], Coroutine[None, None, httpx2.Response]]
)


#: The longest request target a server or proxy takes: Jellyfin's Kestrel,
#: Emby and nginx's default buffers answer 414 past 8 KiB.
MAX_REQUEST_TARGET = 8192


def _within_limits(request: httpx2.Request) -> None:
    target = len(request.url.raw_path)
    assert target <= MAX_REQUEST_TARGET, (
        f"{request.method} {request.url.path} sends a {target}-byte request "
        f"target; servers refuse more than {MAX_REQUEST_TARGET}"
    )


class RecordingMockTransport(httpx2.MockTransport):
    """A MockTransport that captures all dispatched requests for test assertions.

    Like a real server, it refuses a request whose target is too long.
    """

    def __init__(self, handler: MockHandler) -> None:
        super().__init__(handler)
        self.requests: list[httpx2.Request] = []

    @override
    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        _within_limits(request)
        self.requests.append(request)
        return super().handle_request(request)

    @override
    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        _within_limits(request)
        self.requests.append(request)
        return await super().handle_async_request(request)

    @property
    def call_count(self) -> int:
        return len(self.requests)

    @property
    def called(self) -> bool:
        return bool(self.requests)

    @property
    def last_request(self) -> httpx2.Request:
        if not self.requests:
            raise AssertionError("No requests were recorded by this transport.")
        return self.requests[-1]


def mock_client_factory(
    handler: MockHandler,
) -> tuple[ClientFactory, RecordingMockTransport]:
    """Build a client_factory suitable for MediaClient dependencies.

    Includes a recording transport for request verification.
    """
    transport = RecordingMockTransport(handler)

    def factory(**options: Unpack[ClientOptions]) -> httpx2.AsyncClient:
        # The fake transport has no TLS and no pool.
        options.pop("verify", None)
        options.pop("limits", None)
        return httpx2.AsyncClient(transport=transport, **options)

    return factory, transport


async def keep_configured_plex_url(_client: object) -> None:
    """Stand in for ``PlexClient.resolve_secure_url`` so no test reaches plex.tv."""
