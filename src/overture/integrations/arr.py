"""Radarr and Sonarr v3 API client: tags, libraries and requested titles."""

lazy from collections.abc import Callable, Sequence
lazy from dataclasses import dataclass
lazy from typing import Any, Literal

lazy import httpx2
lazy from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

lazy from ..utils.errors import PublicServiceError
lazy from .http import LazyClient, RequestLimiter, create_client, request_with_retry


@dataclass(frozen=True, slots=True)
class ArrTag:
    """One tag configured in Radarr or Sonarr."""

    id: int
    label: str


@dataclass(frozen=True, slots=True)
class ArrTagMatches:
    """External IDs of items carrying one or more Radarr or Sonarr tags."""

    tmdb_ids: tuple[int, ...] = ()
    tvdb_ids: tuple[int, ...] = ()
    imdb_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ArrTitle:
    """A movie or series the Arr server holds, by its own and external IDs."""

    id: int
    tmdb_id: int | None
    tvdb_id: int | None
    tags: frozenset[int]


@dataclass(frozen=True, slots=True)
class ArrOptions:
    """Where a requested title goes and how it is downloaded."""

    root_folders: tuple[str, ...]
    quality_profiles: tuple[ArrTag, ...]


@dataclass(frozen=True, slots=True)
class ArrRequest:
    """How titles are added."""

    root_folder: str
    quality_profile_id: int
    search: bool


class _TagRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = Field(gt=0)
    label: str = Field(min_length=1)


class _MediaRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = 0
    tmdb_id: int | None = Field(default=None, validation_alias="tmdbId")
    tvdb_id: int | None = Field(default=None, validation_alias="tvdbId")
    imdb_id: str | None = Field(default=None, validation_alias="imdbId")
    tags: list[int] = Field(default_factory=list[int])


_TAG_LIST = TypeAdapter(list[_TagRecord])
_MEDIA_LIST = TypeAdapter(list[_MediaRecord])


class _FolderRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str = Field(min_length=1)


class _ProfileRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = Field(gt=0)
    name: str = Field(min_length=1)


_FOLDER_LIST = TypeAdapter(list[_FolderRecord])
_PROFILE_LIST = TypeAdapter(list[_ProfileRecord])


class ArrClient:
    """Client for a Radarr or Sonarr v3 instance."""

    def __init__(
        self,
        *,
        kind: Literal["radarr", "sonarr"],
        base_url: str,
        api_key: str,
        verify_tls: bool = True,
        client_factory: Callable[..., httpx2.AsyncClient] = create_client,
    ) -> None:
        self._kind = kind
        self._label = "Radarr" if kind == "radarr" else "Sonarr"
        self._endpoint = "/api/v3/movie" if kind == "radarr" else "/api/v3/series"
        self._configured = bool(base_url and api_key)
        self._limiter = RequestLimiter()

        async def build() -> httpx2.AsyncClient:
            return client_factory(
                base_url=base_url,
                headers={"X-Api-Key": api_key},
                verify=verify_tls,
            )

        self._client = LazyClient(build, name=self._label)

    @property
    def configured(self) -> bool:
        """Return whether this Arr instance has a URL and API key."""
        return self._configured

    async def close(self) -> None:
        """Close the owned HTTP client."""
        await self._client.close()

    def _require_configured(self) -> None:
        if not self._configured:
            setting = "RADARR" if self._kind == "radarr" else "SONARR"
            raise PublicServiceError(
                400,
                f"Set {setting}_URL and {setting}_API_KEY to use {self._label} tags",
            )

    async def list_tags(self) -> list[ArrTag]:
        """Return all tags configured on the Arr server, sorted by label."""
        self._require_configured()
        try:
            response = await request_with_retry(
                await self._client.get(),
                "GET",
                "/api/v3/tag",
                limiter=self._limiter,
            )
            response.raise_for_status()
            records = _TAG_LIST.validate_python(response.json())
        except (httpx2.HTTPError, ValueError, ValidationError) as exc:
            raise PublicServiceError(
                502, f"{self._label} could not return its tag list"
            ) from exc
        return sorted(
            (ArrTag(id=record.id, label=record.label.strip()) for record in records),
            key=lambda tag: tag.label.casefold(),
        )

    async def external_ids_for_tags(self, tag_names: Sequence[str]) -> ArrTagMatches:
        """Return external IDs of movies or series matching any of *tag_names*."""
        self._require_configured()
        wanted = {name.strip().casefold() for name in tag_names if name.strip()}
        if not wanted:
            return ArrTagMatches()
        tags = await self.list_tags()
        tag_ids = {tag.id for tag in tags if tag.label.casefold() in wanted}
        if not tag_ids:
            return ArrTagMatches()
        try:
            response = await request_with_retry(
                await self._client.get(),
                "GET",
                self._endpoint,
                limiter=self._limiter,
            )
            response.raise_for_status()
            records = _MEDIA_LIST.validate_python(response.json())
        except (httpx2.HTTPError, ValueError, ValidationError) as exc:
            raise PublicServiceError(
                502,
                f"{self._label} could not return its library; membership was kept",
            ) from exc

        tmdb_ids: dict[int, None] = {}
        tvdb_ids: dict[int, None] = {}
        imdb_ids: dict[str, None] = {}
        for record in records:
            if not tag_ids.intersection(record.tags):
                continue
            if isinstance(record.tmdb_id, int) and record.tmdb_id > 0:
                tmdb_ids[record.tmdb_id] = None
            if isinstance(record.tvdb_id, int) and record.tvdb_id > 0:
                tvdb_ids[record.tvdb_id] = None
            if isinstance(record.imdb_id, str) and record.imdb_id.strip():
                imdb_ids[record.imdb_id.strip()] = None
        return ArrTagMatches(
            tmdb_ids=tuple(tmdb_ids),
            tvdb_ids=tuple(tvdb_ids),
            imdb_ids=tuple(imdb_ids),
        )

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Send one request, raising a public error naming the server."""
        self._require_configured()
        try:
            response = await request_with_retry(
                await self._client.get(), method, path, limiter=self._limiter, **kwargs
            )
            response.raise_for_status()
        except httpx2.HTTPError as exc:
            raise PublicServiceError(502, f"{self._label} refused the request") from exc
        return response.json() if response.content else None

    async def options(self) -> ArrOptions:
        """The root folders and quality profiles titles can be requested with."""
        try:
            folders = _FOLDER_LIST.validate_python(
                await self._request("GET", "/api/v3/rootfolder")
            )
            profiles = _PROFILE_LIST.validate_python(
                await self._request("GET", "/api/v3/qualityprofile")
            )
        except ValidationError as exc:
            raise PublicServiceError(
                502, f"{self._label} returned unreadable options"
            ) from exc
        return ArrOptions(
            root_folders=tuple(folder.path for folder in folders),
            quality_profiles=tuple(
                ArrTag(id=profile.id, label=profile.name) for profile in profiles
            ),
        )

    async def titles(self) -> list[ArrTitle]:
        """Every movie or series the server holds."""
        try:
            records = _MEDIA_LIST.validate_python(
                await self._request("GET", self._endpoint)
            )
        except ValidationError as exc:
            raise PublicServiceError(
                502, f"{self._label} returned an unreadable library"
            ) from exc
        return [
            ArrTitle(
                id=record.id,
                tmdb_id=record.tmdb_id,
                tvdb_id=record.tvdb_id,
                tags=frozenset(record.tags),
            )
            for record in records
            if record.id > 0
        ]

    async def add(self, external_id: int, request: ArrRequest) -> None:
        """Add a movie by TMDB ID, or a series by TVDB ID, and maybe search for it.

        Only a lookup result with exactly that ID is added: a search can rank
        another title first, and adding it would request the wrong one.
        """
        if self._kind == "radarr":
            id_field = "tmdbId"
            options: dict[str, Any] = {"searchForMovie": request.search}
        else:
            id_field = "tvdbId"
            options = {"monitor": "all", "searchForMissingEpisodes": request.search}
        prefix = "tmdb" if self._kind == "radarr" else "tvdb"
        results: list[dict[str, Any]] = (
            await self._request(
                "GET",
                f"{self._endpoint}/lookup",
                params={"term": f"{prefix}:{external_id}"},
            )
            or []
        )
        found = next(
            (result for result in results if result.get(id_field) == external_id),
            None,
        )
        if found is None:
            raise PublicServiceError(404, f"{self._label} does not know this title")
        body: dict[str, Any] = {
            **found,
            "qualityProfileId": request.quality_profile_id,
            "rootFolderPath": request.root_folder,
            "monitored": True,
            "addOptions": options,
        }
        if self._kind == "sonarr":
            body["seasonFolder"] = True
        await self._request("POST", self._endpoint, json=body)

    async def tag_id(self, label: str) -> int:
        """The ID of a tag, created when the server lacks it."""
        for tag in await self.list_tags():
            if tag.label.casefold() == label.casefold():
                return tag.id
        created = _TagRecord.model_validate(
            await self._request("POST", "/api/v3/tag", json={"label": label})
        )
        return created.id

    async def edit_tag(
        self, tag_id: int, title_ids: Sequence[int], *, add: bool
    ) -> None:
        """Add the tag to, or remove it from, the titles with these Arr IDs."""
        if not title_ids:
            return
        key = "movieIds" if self._kind == "radarr" else "seriesIds"
        await self._request(
            "PUT",
            f"{self._endpoint}/editor",
            json={
                key: list(title_ids),
                "tags": [tag_id],
                "applyTags": "add" if add else "remove",
            },
        )
