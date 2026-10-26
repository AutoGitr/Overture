"""Shared HTTP plumbing for media-server API clients."""

lazy import asyncio
lazy import logging
lazy from abc import ABC, abstractmethod
lazy from collections import deque
lazy from collections.abc import AsyncGenerator, AsyncIterator, Callable, Hashable
lazy from contextlib import asynccontextmanager
lazy from dataclasses import dataclass, field
lazy from typing import Any, ClassVar

lazy import httpx2

lazy from ..config import Settings
lazy from ..db.models.media_item import MediaItem
lazy from ..domain import ArtType
lazy from ..integrations.http import (
    RETRYABLE_STATUS,
    LazyClient,
    create_client,
    request_with_retry,
)
lazy from ..schemas.art import ArtCandidate
lazy from ..utils.cache import AsyncMemoizer
lazy from .adapters import ServerTheme
lazy from .errors import MediaServerError
lazy from .wire import Page

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _ListingCheck[T]:
    """Validate the pages of one listing in order and count their rows."""

    page_size: int
    identity: Callable[[T], str] | None
    track_all_ids: bool
    require_total: bool
    count: int = 0
    seen: set[str] = field(default_factory=set[str])
    expected_total: int | None = None
    previous: list[T] | None = None

    def accept(self, page: Page[T]) -> None:
        """Reject a page that breaks the listing, then count its rows."""
        if len(page.items) > self.page_size:
            raise MediaServerError("Media server returned an oversized page")
        if self.require_total and page.total is None:
            raise MediaServerError("Media server returned no listing total")
        if page.offset is not None and page.offset != self.count:
            raise MediaServerError("Media server returned an unexpected page offset")
        if self.expected_total is not None and page.total != self.expected_total:
            raise MediaServerError(
                "Media-server listing changed during pagination; retry"
            )
        self.expected_total = page.total
        if not page.items and page.total is not None and self.count < page.total:
            raise MediaServerError("Media server returned an incomplete listing")
        if self.identity is None:
            if page.items and page.items == self.previous:
                raise MediaServerError("Media server repeated a page")
            self.previous = page.items
        else:
            if not self.track_all_ids:
                self.seen.clear()
            for item in page.items:
                key = self.identity(item)
                if not key or key in self.seen:
                    raise MediaServerError(
                        "Media server returned missing or duplicate item IDs"
                    )
                self.seen.add(key)
        self.count += len(page.items)
        if page.total is not None and self.count > page.total:
            raise MediaServerError("Media server returned an inconsistent item count")

    def complete(self, page: Page[T]) -> bool:
        """Return whether *page* ends the listing."""
        if page.total is not None:
            return self.count == page.total
        return len(page.items) < self.page_size


class MediaServerHttpClient(ABC):
    """Own one lazily built ``httpx2`` client and its GET/JSON conventions.

    Requests go to the user's own server unthrottled; transient failures
    are retried with backoff.
    """

    #: Rows per listing request, set from each server's measured cost per request.
    _PAGE_SIZE: ClassVar[int] = 100
    #: The query parameters naming a listing page's offset and size.
    _PAGE_PARAMETERS: ClassVar[tuple[str, str]]

    def __init__(
        self,
        *,
        app_config: Settings,
        client_factory: Callable[..., httpx2.AsyncClient] = create_client,
    ) -> None:
        """Initialize the lazily created client and its response memoizer."""
        self._app_config = app_config
        self._client_factory = client_factory
        self._client = LazyClient(self._create_client, name="Media-server")
        self._cache: AsyncMemoizer[tuple[Hashable, ...]] = AsyncMemoizer()

    @property
    @abstractmethod
    def auth_headers(self) -> dict[str, str]:
        """Return the headers that authenticate a request to the server."""

    @abstractmethod
    async def _create_client(self) -> httpx2.AsyncClient:
        """Build a configured client for the concrete media server."""

    @abstractmethod
    async def find_item_id(self, item: MediaItem) -> str | None:
        """Find the server's ID of a library item."""

    @abstractmethod
    async def find_season_id(self, show_id: str, season_num: int) -> str | None:
        """Find the server's ID of one season of a show."""

    @abstractmethod
    async def get_art_candidates(
        self, item_id: str, art_type: ArtType
    ) -> list[ArtCandidate]:
        """Return the artwork the server offers for one slot."""

    @abstractmethod
    async def get_theme_songs(self, item_id: str) -> list[ServerTheme]:
        """Return the item's theme songs with the file each one plays."""

    @abstractmethod
    async def test_connection(self) -> bool:
        """Return whether the server answers with its identity."""

    async def get_client(self) -> httpx2.AsyncClient:
        """Get or initialize the httpx2 client asynchronously."""
        return await self._client.get()

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._cache.close()
        await self._client.close()

    async def _get(self, path: str, **kwargs: Any) -> Any:
        """Perform a retrying GET request and return the decoded JSON body."""
        return self._json(await self._request("GET", path, **kwargs))

    @staticmethod
    def _json(response: httpx2.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise MediaServerError("Media server returned invalid JSON") from exc

    @staticmethod
    def _error(exc: httpx2.HTTPError) -> MediaServerError:
        """Return the safe failure a failed request becomes."""
        logger.warning("Media server request failed: %s", exc)
        if isinstance(exc, httpx2.HTTPStatusError):
            status = exc.response.status_code
            if status in {401, 403}:
                return MediaServerError(
                    "Media server rejected its configured credentials"
                )
            if status not in RETRYABLE_STATUS:
                return MediaServerError(
                    "Media server returned an unsuccessful response",
                    upstream_status_code=status,
                )
        return MediaServerError("Media server is unavailable", status_code=503)

    async def _request(
        self, method: str, path: str, *, allow_not_found: bool = False, **kwargs: Any
    ) -> httpx2.Response:
        client = await self.get_client()
        try:
            # Mutations may queue work or upload files; request_with_retry
            # never repeats them.
            response = await request_with_retry(client, method, path, **kwargs)
            if allow_not_found and response.status_code == 404:
                return response
            response.raise_for_status()
        except httpx2.HTTPError as exc:
            raise self._error(exc) from exc
        if method not in {"GET", "HEAD"}:
            self._cache.invalidate()
        return response

    @asynccontextmanager
    async def _stream(self, path: str) -> AsyncGenerator[httpx2.Response]:
        """Stream a GET response, failing the way :meth:`_request` does."""
        client = await self.get_client()
        try:
            async with client.stream("GET", path) as response:
                response.raise_for_status()
                yield response
        except httpx2.HTTPError as exc:
            raise self._error(exc) from exc

    async def _pages[T](
        self,
        path: str,
        *,
        params: dict[str, Any] | None,
        parse: Callable[[object], Page[T]],
        identity: Callable[[T], str] | None,
    ) -> list[T]:
        """Collect a small listing for callers that need its complete result."""
        items: list[T] = []
        async for batch in self._page_batches(
            path, params=params, parse=parse, identity=identity
        ):
            items.extend(batch)
        return items

    async def _page_batches[T](
        self,
        path: str,
        *,
        params: dict[str, Any] | None,
        parse: Callable[[object], Page[T]],
        identity: Callable[[T], str] | None,
        track_all_ids: bool = True,
        require_total: bool = False,
        prefetch: int = 0,
    ) -> AsyncIterator[list[T]]:
        """Validate page boundaries before handing each bounded batch to staging.

        With *prefetch*, up to that many later pages of a listing with a
        total are requested while earlier ones are processed. Their offsets
        follow the first page's length, so a later short page fails the
        listing; pages are still validated and yielded in order.
        """

        start_parameter, limit_parameter = self._PAGE_PARAMETERS

        async def fetch(offset: int) -> Page[T]:
            return parse(
                await self._get(
                    path,
                    params={
                        **(params or {}),
                        start_parameter: offset,
                        limit_parameter: self._PAGE_SIZE,
                    },
                )
            )

        check = _ListingCheck[T](
            self._PAGE_SIZE, identity, track_all_ids, require_total
        )
        stride = 0
        pending: deque[asyncio.Task[Page[T]]] = deque()
        try:
            while True:
                page = await (pending.popleft() if pending else fetch(check.count))
                check.accept(page)
                if prefetch and page.total is not None and check.count < page.total:
                    if not stride:
                        stride = len(page.items)
                    elif len(page.items) != stride:
                        raise MediaServerError(
                            "Media server returned an inconsistent page size"
                        )
                    offset = check.count + stride * len(pending)
                    while len(pending) < prefetch and offset < page.total:
                        pending.append(asyncio.create_task(fetch(offset)))
                        offset += stride
                if page.items:
                    yield page.items
                if check.complete(page):
                    return
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
