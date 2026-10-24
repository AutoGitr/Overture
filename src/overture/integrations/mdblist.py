"""MDBList JSON lists, resolved to TMDB IDs without fetching user URLs."""

lazy import re
lazy from collections.abc import Callable
lazy from urllib.parse import urlsplit

lazy import httpx2
lazy from pydantic import BaseModel, ConfigDict, Field, ValidationError

lazy from ..config import Settings
lazy from ..domain import MediaType
lazy from ..utils.errors import PublicServiceError
lazy from .http import LazyClient, RequestLimiter, create_client, request_with_retry


def mdblist_identifier(value: str) -> str:
    """Normalize a list ID or MDBList list URL to a fixed-origin API path."""
    value = value.strip()
    if "://" in value:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.netloc not in {"mdblist.com", "www.mdblist.com"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Use an MDBList list ID or an HTTPS mdblist.com/lists/user/list URL"
            )
        value = parsed.path.removeprefix("/lists/").strip("/")
    if not re.fullmatch(r"[1-9][0-9]*|[A-Za-z0-9_-]+/[A-Za-z0-9_-]+", value):
        raise ValueError("Use an MDBList list ID or user/list identifier")
    return value


class _ListItem(BaseModel):
    model_config = ConfigDict(strict=True)

    id: int = Field(gt=0)


class _ListPage(BaseModel):
    movies: list[_ListItem] = Field(default_factory=list[_ListItem])
    shows: list[_ListItem] = Field(default_factory=list[_ListItem])


class MDBListClient:
    """Own the authenticated client and read bounded list pages in source order."""

    def __init__(
        self,
        *,
        app_config: Settings,
        client_factory: Callable[..., httpx2.AsyncClient] = create_client,
    ) -> None:
        self._config = app_config
        self._limiter = RequestLimiter()

        async def build() -> httpx2.AsyncClient:
            return client_factory(
                base_url="https://api.mdblist.com",
                params={"apikey": app_config.MDBLIST_API_KEY.get_secret_value()},
            )

        self._client = LazyClient(build, name="MDBList")

    async def close(self) -> None:
        """Close the owned HTTP client."""
        await self._client.close()

    async def tmdb_ids(self, identifier: str, media_type: MediaType) -> list[int]:
        """Return a complete list or fail before destructive membership changes."""
        if not self._config.MDBLIST_API_KEY.get_secret_value():
            raise PublicServiceError(
                400, "Set MDBLIST_API_KEY to sync MDBList collections"
            )
        identifier = mdblist_identifier(identifier)
        ids: dict[int, None] = {}
        previous: tuple[int, ...] | None = None
        for offset in range(0, 100000, 1000):
            try:
                response = await request_with_retry(
                    await self._client.get(),
                    "GET",
                    f"/lists/{identifier}/items",
                    params={
                        "limit": 1000,
                        "offset": offset,
                        "unified": "false",
                        "sort": "rank",
                        "order": "asc",
                    },
                    limiter=self._limiter,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or (
                    "movies" not in payload and "shows" not in payload
                ):
                    raise ValueError("Missing list contents")
                page = _ListPage.model_validate(payload)
            except (httpx2.HTTPError, ValueError, ValidationError) as exc:
                raise PublicServiceError(
                    502, "MDBList could not return a complete list; membership was kept"
                ) from exc
            items = page.movies if media_type is MediaType.MOVIE else page.shows
            current = tuple(item.id for item in items)
            if current and current == previous:
                raise PublicServiceError(
                    502, "MDBList repeated a page; membership was kept"
                )
            ids.update(dict.fromkeys(current))
            if len(page.movies) + len(page.shows) < 1000:
                return list(ids)
            previous = current
        raise PublicServiceError(
            502, "MDBList exceeded the supported list size; membership was kept"
        )
