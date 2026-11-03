"""Transient HTTP failures and retry exhaustion."""

lazy from typing import Any

lazy import httpx2
lazy import pytest

lazy from overture.integrations.http import request_with_retry


class TestClientRetry:
    async def test_retries_transient_server_status_then_returns_success(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.calls = 0

            async def request(
                self, method: str, url: str, **kwargs: Any
            ) -> httpx2.Response:
                self.calls += 1
                request = httpx2.Request(method, url)
                status = 503 if self.calls == 1 else 200
                return httpx2.Response(status, request=request)

        client = FakeClient()
        response = await request_with_retry(
            client,
            "GET",
            "https://example.test/resource",
            rate_limit=False,
            retry_delays=(0,),
        )

        assert response.status_code == 200
        assert client.calls == 2

    async def test_raises_last_exception_after_retry_exhaustion(self) -> None:
        class FakeClient:
            async def request(
                self, method: str, url: str, **kwargs: Any
            ) -> httpx2.Response:
                raise httpx2.ConnectTimeout("timed out")

        with pytest.raises(httpx2.ConnectTimeout):
            await request_with_retry(
                FakeClient(),
                "GET",
                "https://example.test/resource",
                rate_limit=False,
                retry_delays=(0,),
            )


@pytest.mark.parametrize(("idempotent", "attempts"), [(False, 1), (True, 2)])
async def test_writes_are_retried_only_when_idempotent(
    idempotent: bool, attempts: int
) -> None:
    calls = 0

    def handler(_request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(503 if calls == 1 else 200)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        response = await request_with_retry(
            client,
            "PUT",
            "https://server.test/refresh",
            retry_delays=(0,),
            idempotent=idempotent,
        )

    assert calls == attempts
    assert response.status_code == (503 if attempts == 1 else 200)
