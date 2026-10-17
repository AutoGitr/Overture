"""Reusable, recording HTTP mock transport and factory for tests."""

lazy from collections.abc import Callable, Coroutine
lazy from typing import Any, override

lazy import httpx2

type MockHandler = (
    Callable[[httpx2.Request], httpx2.Response]
    | Callable[[httpx2.Request], Coroutine[None, None, httpx2.Response]]
)
type ClientFactory = Callable[..., httpx2.AsyncClient]


class RecordingMockTransport(httpx2.MockTransport):
    """A MockTransport that captures all dispatched requests for test assertions."""

    def __init__(self, handler: MockHandler) -> None:
        super().__init__(handler)
        self.requests: list[httpx2.Request] = []

    @override
    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return super().handle_request(request)

    @override
    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
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

    def factory(**kwargs: Any) -> httpx2.AsyncClient:
        kwargs.pop("verify", None)
        return httpx2.AsyncClient(transport=transport, **kwargs)

    return factory, transport
