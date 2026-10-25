"""TMDB API client."""

lazy from collections.abc import Callable
lazy from dataclasses import dataclass
lazy from typing import Any, Literal

lazy import httpx2

lazy from ..config import Settings
lazy from ..domain import (
    ArtSource,
    ArtType,
    CatalogMediaType,
    MediaType,
    TmdbLanguageFilter,
    TmdbPersonRole,
)
lazy from ..schemas.art import ArtCandidate
lazy from ..services.public_dataset.schema.contract import canonical_art_url
lazy from ..utils.art_urls import art_preview_url
lazy from ..utils.cache import AsyncMemoizer
lazy from .http import LazyClient, RequestLimiter, create_client, request_with_retry

_TMDB_BASE = "https://api.themoviedb.org/3"
_TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/original"

#: The TMDB path segment for each media type.
_TMDB_KIND = frozendict({MediaType.MOVIE: "movie", MediaType.SHOW: "tv"})  # pyright: ignore[reportCallIssue] -- stale frozendict stub
#: The images-response list that holds each art type.
_TMDB_IMAGE_LIST = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        ArtType.POSTER: "posters",
        ArtType.SEASON_POSTER: "posters",
        ArtType.BACKGROUND: "backdrops",
    }
)


@dataclass(frozen=True, slots=True)
class TmdbTitle:
    """One movie, show or collection as TMDB lists it."""

    tmdb_id: int
    title: str
    year: int | None
    release_date: str | None
    poster_url: str | None


@dataclass(frozen=True, slots=True)
class TmdbSeason:
    """One season of a TMDB show."""

    season_num: int
    title: str | None
    episode_count: int
    poster_url: str | None


@dataclass(frozen=True, slots=True)
class TmdbDetails:
    """A movie or show with its external IDs and, for shows, its seasons."""

    media_type: MediaType
    tmdb_id: int
    title: str
    year: int | None
    tvdb_id: int | None
    imdb_id: str | None
    poster_url: str | None
    background_url: str | None
    seasons: tuple[TmdbSeason, ...]
    #: The TMDB collection a movie belongs to.
    collection_id: int | None = None

    @property
    def summary(self) -> TmdbTitle:
        """Return the movie or show as a search lists it."""
        return TmdbTitle(
            tmdb_id=self.tmdb_id,
            title=self.title,
            year=self.year,
            release_date=None,
            poster_url=self.poster_url,
        )

    @property
    def tracked_seasons(self) -> tuple[TmdbSeason, ...]:
        """Return the seasons with episodes; announced ones hold nothing yet."""
        return tuple(season for season in self.seasons if season.episode_count > 0)


@dataclass(frozen=True, slots=True)
class TmdbCollection:
    """A TMDB collection and the movies it groups."""

    tmdb_id: int
    title: str
    poster_url: str | None
    parts: tuple[TmdbTitle, ...]

    @property
    def summary(self) -> TmdbTitle:
        """Return the collection as a search lists it."""
        return TmdbTitle(
            tmdb_id=self.tmdb_id,
            title=self.title,
            year=None,
            release_date=None,
            poster_url=self.poster_url,
        )


@dataclass(frozen=True, slots=True)
class TmdbPerson:
    """One person (actor, director, writer, producer) as TMDB lists them."""

    tmdb_id: int
    name: str
    known_for_department: str | None
    profile_url: str | None
    biography: str | None = None


def _image_url(path: object) -> str | None:
    """Return the canonical original-size URL of a TMDB image path."""
    if not isinstance(path, str) or not path:
        return None
    try:
        return canonical_art_url(f"{_TMDB_IMAGE_BASE}{path}")
    except ValueError:
        return None


def _records(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Return the list of JSON objects under *key*, or an empty list."""
    records: list[dict[str, Any]] = data.get(key) or []
    return records


def _year(date: object) -> int | None:
    """Return the year of a TMDB ``YYYY-MM-DD`` date, if it has one."""
    if isinstance(date, str) and len(date) >= 4 and date[:4].isdigit():
        return int(date[:4])
    return None


def _title(data: dict[str, Any]) -> TmdbTitle:
    """Read a movie, show or collection from a TMDB list or details payload."""
    date = data.get("release_date") or data.get("first_air_date") or None
    return TmdbTitle(
        tmdb_id=int(data["id"]),
        title=str(data.get("title") or data.get("name") or ""),
        year=_year(date),
        release_date=date,
        poster_url=_image_url(data.get("poster_path")),
    )


def _person(data: dict[str, Any]) -> TmdbPerson:
    """Read a person from a TMDB search or details payload."""
    dept = data.get("known_for_department")
    bio = data.get("biography")
    return TmdbPerson(
        tmdb_id=int(data["id"]),
        name=str(data.get("name") or ""),
        known_for_department=str(dept) if isinstance(dept, str) and dept else None,
        profile_url=_image_url(data.get("profile_path")),
        biography=str(bio).strip() if isinstance(bio, str) and bio.strip() else None,
    )


def _is_self_credit(credit: dict[str, Any]) -> bool:
    """Return whether a cast credit is a self/biography appearance."""
    character = str(credit.get("character") or "").strip().casefold()
    if not character:
        return False
    return character in {
        "self",
        "himself",
        "herself",
        "themselves",
    } or character.startswith(("self ", "himself ", "herself "))


def _matches_crew_role(
    credit: dict[str, Any], roles: frozenset[TmdbPersonRole]
) -> bool:
    """Return whether a crew credit matches any requested person role."""
    department = str(credit.get("department") or "").strip().casefold()
    job = str(credit.get("job") or "").strip().casefold()
    if TmdbPersonRole.DIRECTOR in roles and (
        job == "director" or department == "directing"
    ):
        return True
    if TmdbPersonRole.WRITER in roles and (
        department == "writing"
        or job in {"writer", "screenplay", "story", "characters", "teleplay"}
    ):
        return True
    return TmdbPersonRole.PRODUCER in roles and (
        department == "production" or job in {"producer", "executive producer"}
    )


def _details(media_type: MediaType, data: dict[str, Any]) -> TmdbDetails:
    """Read a movie or show details payload with ``external_ids`` appended."""
    title = _title(data)
    external_ids: dict[str, Any] = data.get("external_ids") or {}
    tvdb_id = external_ids.get("tvdb_id")
    imdb_id = external_ids.get("imdb_id") or data.get("imdb_id")
    collection: dict[str, Any] = data.get("belongs_to_collection") or {}
    collection_id = collection.get("id")
    return TmdbDetails(
        media_type=media_type,
        tmdb_id=title.tmdb_id,
        title=title.title,
        year=title.year,
        tvdb_id=tvdb_id if isinstance(tvdb_id, int) else None,
        imdb_id=imdb_id if isinstance(imdb_id, str) and imdb_id else None,
        poster_url=title.poster_url,
        background_url=_image_url(data.get("backdrop_path")),
        seasons=tuple(
            TmdbSeason(
                season_num=int(season["season_number"]),
                title=season.get("name") or None,
                episode_count=int(season.get("episode_count") or 0),
                poster_url=_image_url(season.get("poster_path")),
            )
            for season in _records(data, "seasons")
        ),
        collection_id=collection_id
        if type(collection_id) is int and collection_id > 0
        else None,
    )


def _image_language_params(language_filter: TmdbLanguageFilter) -> dict[str, str]:
    """Return TMDB image language query params for the configured filter."""
    if language_filter is TmdbLanguageFilter.ALL:
        return {}
    return {"include_image_language": "en,null"}


def extract_art(images_data: dict[str, Any], art_type: ArtType) -> list[ArtCandidate]:
    """Return the *art_type* images of a TMDB images response, largest first."""
    results: list[ArtCandidate] = []
    for image in _records(images_data, _TMDB_IMAGE_LIST[art_type]):
        url = _image_url(image.get("file_path"))
        if url is None:
            continue
        results.append(
            ArtCandidate(
                url=url,
                preview_url=art_preview_url(url, art_type) or url,
                width=image.get("width", 0),
                height=image.get("height", 0),
                iso_639_1=image.get("iso_639_1"),
                source=ArtSource.TMDB,
            )
        )
    results.sort(key=lambda candidate: candidate.area, reverse=True)
    return results


class TMDBClient:
    """Interface to the TMDB v3 API."""

    def __init__(
        self,
        *,
        app_config: Settings,
        client_factory: Callable[..., httpx2.AsyncClient] = create_client,
        limiter: RequestLimiter | None = None,
    ) -> None:
        """Initialize instance state."""
        self._app_config = app_config
        self._limiter = limiter if limiter is not None else RequestLimiter()
        self._cache: AsyncMemoizer[tuple[str | int, ...]] = AsyncMemoizer(maxsize=2_000)

        async def build() -> httpx2.AsyncClient:
            return client_factory(
                base_url=_TMDB_BASE,
                params={"api_key": app_config.TMDB_API_KEY.get_secret_value()},
            )

        self._client = LazyClient(build, name="TMDB")

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._cache.close()
        await self._client.close()

    async def _get(self, path: str, **kwargs: Any) -> Any:
        """Return the JSON TMDB serves at *path*."""
        resp = await request_with_retry(
            await self._client.get(), "GET", path, limiter=self._limiter, **kwargs
        )
        resp.raise_for_status()
        return resp.json()

    async def _get_found(self, path: str, **kwargs: Any) -> Any:
        """Return the JSON at *path*, or ``None`` when TMDB has no such record."""
        try:
            return await self._get(path, **kwargs)
        except httpx2.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise

    async def art_candidates(
        self,
        media_type: MediaType | CatalogMediaType,
        tmdb_id: int,
        art_type: ArtType,
        *,
        season_num: int | None = None,
        language_filter: TmdbLanguageFilter = TmdbLanguageFilter.EN_NULL,
    ) -> list[ArtCandidate]:
        """Return TMDB's *art_type* images of a title, or of one of its seasons."""
        kind = (
            "collection"
            if media_type == CatalogMediaType.COLLECTION
            else _TMDB_KIND[MediaType(media_type)]
        )
        path = f"/{kind}/{tmdb_id}"
        if art_type.owned_by_season:
            path = f"{path}/season/{season_num}"
        images = await self._cache.get_or_compute(
            (path, "images", language_filter),
            self._get,
            f"{path}/images",
            params=_image_language_params(language_filter),
        )
        return extract_art(images, art_type)

    async def search(
        self, kind: Literal["movie", "tv", "collection"], query: str
    ) -> tuple[TmdbTitle, ...]:
        """Return the first page of TMDB's title search for one kind."""
        data = await self._cache.get_or_compute(
            ("search", kind, query.casefold()),
            self._get,
            f"/search/{kind}",
            params={"query": query, "include_adult": "false"},
        )
        return tuple(_title(result) for result in _records(data, "results"))

    async def get_details(
        self, media_type: MediaType, tmdb_id: int
    ) -> TmdbDetails | None:
        """Return a movie or show with its external IDs, or ``None``."""
        kind = _TMDB_KIND[media_type]
        data = await self._cache.get_or_compute(
            (kind, tmdb_id, "details"),
            self._get_found,
            f"/{kind}/{tmdb_id}",
            params={"append_to_response": "external_ids"},
        )
        return _details(media_type, data) if data else None

    async def get_collection(self, collection_id: int) -> TmdbCollection | None:
        """Return a collection and its movies, or ``None``."""
        data = await self._cache.get_or_compute(
            ("collection", collection_id),
            self._get_found,
            f"/collection/{collection_id}",
        )
        if not data:
            return None
        title = _title(data)
        return TmdbCollection(
            tmdb_id=title.tmdb_id,
            title=title.title,
            poster_url=title.poster_url,
            parts=tuple(_title(part) for part in _records(data, "parts")),
        )

    async def get_person(self, person_id: int) -> TmdbPerson | None:
        """Return a TMDB person by ID, or ``None``."""
        data = await self._cache.get_or_compute(
            ("person", person_id),
            self._get_found,
            f"/person/{person_id}",
        )
        return _person(data) if data else None

    async def search_people(self, query: str) -> tuple[TmdbPerson, ...]:
        """Return the first page of TMDB's person search."""
        data = await self._cache.get_or_compute(
            ("search", "person", query.casefold()),
            self._get,
            "/search/person",
            params={"query": query, "include_adult": "false"},
        )
        return tuple(_person(result) for result in _records(data, "results"))

    async def get_person_credits(
        self,
        person_id: int,
        media_type: MediaType,
        roles: frozenset[TmdbPersonRole] | set[TmdbPersonRole],
    ) -> tuple[int, ...]:
        """Return TMDB IDs of movies or shows credited to *person_id* in *roles*."""
        role_set = frozenset(roles)
        if not role_set:
            return ()
        endpoint = (
            f"/person/{person_id}/movie_credits"
            if media_type is MediaType.MOVIE
            else f"/person/{person_id}/tv_credits"
        )
        data = await self._cache.get_or_compute(
            ("person_credits", person_id, media_type.value),
            self._get_found,
            endpoint,
        )
        if not data:
            return ()
        matched: dict[int, tuple[str, int]] = {}
        include_actor = TmdbPersonRole.ACTOR in role_set
        include_bio = TmdbPersonRole.BIOGRAPHY in role_set
        if include_actor or include_bio:
            for credit in _records(data, "cast"):
                is_self = _is_self_credit(credit)
                if (include_actor and not is_self) or (include_bio and is_self):
                    title = _title(credit)
                    matched.setdefault(
                        title.tmdb_id, (title.release_date or "9999", title.tmdb_id)
                    )
        if role_set.intersection(
            {TmdbPersonRole.DIRECTOR, TmdbPersonRole.WRITER, TmdbPersonRole.PRODUCER}
        ):
            for credit in _records(data, "crew"):
                if _matches_crew_role(credit, role_set):
                    title = _title(credit)
                    matched.setdefault(
                        title.tmdb_id, (title.release_date or "9999", title.tmdb_id)
                    )
        return tuple(
            tmdb_id
            for tmdb_id, _sort_key in sorted(matched.items(), key=lambda kv: kv[1])
        )

    async def test_connection(self) -> bool:
        """Test if TMDB is reachable."""
        if not self._app_config.tmdb_configured:
            return False
        try:
            resp = await request_with_retry(
                await self._client.get(),
                "GET",
                "/configuration",
                limiter=self._limiter,
            )
            return resp.status_code == 200
        except httpx2.HTTPError:
            return False
