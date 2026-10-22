"""Shared HTTP clients: the factory, lazy ownership, rate limiting and retry."""

lazy import asyncio
lazy import logging
lazy import time
lazy from collections.abc import Awaitable, Callable
lazy from dataclasses import dataclass
lazy from typing import Any, Protocol
lazy from urllib.parse import urlsplit

lazy import httpx2

lazy from ..utils.cache import TimedRegistry
lazy from ..utils.locks import KeyedLock

logger = logging.getLogger(__name__)

_RETRY_DELAYS = (1.0, 2.0, 4.0)
_CONNECT_TIMEOUT = 10.0
_READ_TIMEOUT = 30.0


def create_client(**kwargs: Any) -> httpx2.AsyncClient:
    """Create an httpx2.AsyncClient with standard timeout config."""
    timeout = httpx2.Timeout(
        connect=_CONNECT_TIMEOUT,
        read=_READ_TIMEOUT,
        write=_READ_TIMEOUT,
        pool=_READ_TIMEOUT,
    )
    kwargs.setdefault(
        "limits", httpx2.Limits(max_connections=16, max_keepalive_connections=8)
    )
    return httpx2.AsyncClient(timeout=timeout, **kwargs)


class RequestLimiter:
    """Bounded, per-host request spacing owned by an HTTP integration."""

    def __init__(
        self,
        *,
        min_interval: float = 0.2,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_hosts: int = 1000,
        idle_seconds: float = 300.0,
    ) -> None:
        self._min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last_request: TimedRegistry[str, float] = TimedRegistry(
            maxsize=max_hosts,
            ttl_seconds=idle_seconds,
        )
        self._host_locks = KeyedLock[str]()

    async def wait(self, url: str) -> None:
        """Reserve the next request slot for this URL's host."""
        host = urlsplit(url).netloc
        if not host:
            return
        async with self._host_locks.acquire(host):
            now = self._clock()
            last = self._last_request.get(host, now)
            if last is not None and now - last < self._min_interval:
                await self._sleep(self._min_interval - (now - last))
            now = self._clock()
            self._last_request.set(host, now, now)


class RequestClient(Protocol):
    """Protocol for the subset of httpx2.AsyncClient used by retry helpers."""

    @property
    def request(self) -> Callable[..., Awaitable[httpx2.Response]]:
        """Send an HTTP request."""
        ...


class LazyClient:
    """One ``httpx2`` client, built on first use and rebuilt if it was closed.

    Owners call :meth:`close` once when they shut down; asking for the client
    afterwards is a programming error.
    """

    def __init__(
        self, build: Callable[[], Awaitable[httpx2.AsyncClient]], *, name: str
    ) -> None:
        self._build = build
        self._name = name
        self._client: httpx2.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._closed = False

    async def get(self) -> httpx2.AsyncClient:
        """Return the client, building it when there is none open."""
        async with self._lock:
            if self._closed:
                raise RuntimeError(f"{self._name} HTTP client is closed")
            if self._client is None or self._client.is_closed:
                self._client = await self._build()
            return self._client

    async def close(self) -> None:
        """Close the client for good."""
        async with self._lock:
            self._closed = True
            if self._client is not None and not self._client.is_closed:
                await self._client.aclose()


#: Network failures worth another attempt.
_RETRYABLE_ERRORS = (
    httpx2.ConnectTimeout,
    httpx2.ReadTimeout,
    httpx2.ConnectError,
    httpx2.RemoteProtocolError,
)
#: Responses worth another attempt: rate limits and transient server failures.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
#: Longest a retried operation may take in all, waits included.
_RETRY_BUDGET_SECONDS = 120
#: Longest a server's ``Retry-After`` may hold a retry back.
_MAX_RETRY_AFTER_SECONDS = 30


@dataclass(frozen=True, slots=True)
class Retry:
    """A result worth another attempt, and how long to wait before it."""

    wait: float
    reason: str


async def retrying[T](
    operation: Callable[[], Awaitable[T]],
    *,
    label: str,
    retry_delays: tuple[float, ...] = _RETRY_DELAYS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    retry_result: Callable[[T, float], Awaitable[Retry | None]] | None = None,
) -> T:
    """Run *operation*, retrying transient failures with backoff.

    Transient network errors are always retried; *retry_result* may also ask
    for another attempt after a result. Whatever the last attempt returns or
    raises is the answer.
    """
    deadline = time.monotonic() + _RETRY_BUDGET_SECONDS
    async with asyncio.timeout(_RETRY_BUDGET_SECONDS):
        for number, delay in enumerate(retry_delays, start=1):
            try:
                result = await operation()
            except _RETRYABLE_ERRORS as exc:
                retry = Retry(delay, f"failed ({str(exc) or type(exc).__name__})")
            else:
                verdict = await retry_result(result, delay) if retry_result else None
                if verdict is None:
                    return result
                retry = verdict
            logger.warning(
                "%s %s; retry %d in %.0fs", label, retry.reason, number, retry.wait
            )
            if time.monotonic() + retry.wait >= deadline:
                raise httpx2.ReadTimeout("HTTP retry deadline exceeded")
            await sleep(retry.wait)
        return await operation()


async def _retry_response(response: httpx2.Response, delay: float) -> Retry | None:
    """Ask for another attempt after a rate limit or transient server error."""
    if response.status_code not in RETRYABLE_STATUS:
        return None
    retry_after = response.headers.get("Retry-After", "")
    wait = (
        min(_MAX_RETRY_AFTER_SECONDS, max(delay, int(retry_after)))
        if retry_after.isdigit()
        else delay
    )
    await response.aclose()
    return Retry(wait, f"returned {response.status_code}")


async def request_with_retry(
    client: RequestClient,
    method: str,
    url: str,
    *,
    limiter: RequestLimiter | None = None,
    retry_delays: tuple[float, ...] = _RETRY_DELAYS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    **kwargs: Any,
) -> httpx2.Response:
    """Make an HTTP request; reads are retried with backoff, writes never."""

    async def attempt() -> httpx2.Response:
        if limiter is not None:
            await limiter.wait(url)
        return await client.request(method, url, **kwargs)

    if method.upper() not in {"GET", "HEAD"}:
        return await attempt()
    # Logged without its query string, which can carry credentials.
    endpoint = urlsplit(url)._replace(query="", fragment="").geturl()
    return await retrying(
        attempt,
        label=f"{method} {endpoint}",
        retry_delays=retry_delays,
        sleep=sleep,
        retry_result=_retry_response,
    )
