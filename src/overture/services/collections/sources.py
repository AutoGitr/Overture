"""Resolve source conditions against TMDB, MDBList, Radarr and Sonarr."""

lazy import hashlib
lazy from collections.abc import Sequence

lazy from ...config import Settings
lazy from ...db.models.media_item import MediaItem
lazy from ...domain import MediaType, SourceType
lazy from ...integrations.arr import ArrClient
lazy from ...integrations.mdblist import MDBListClient
lazy from ...integrations.tmdb import TMDBClient
lazy from ...schemas.collections import (
    ArrTagRead,
    CollectionSource,
    MdblistSource,
    RadarrTagSource,
    SonarrTagSource,
    SourceCondition,
    TmdbCollectionSource,
    TmdbItemSource,
    TmdbListSource,
    TmdbPersonSource,
)
lazy from ...utils.errors import PublicServiceError

SOURCE_LABELS: frozendict[SourceType, str] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        SourceType.TMDB_COLLECTION: "TMDB franchise",
        SourceType.TMDB_LIST: "TMDB list",
        SourceType.TMDB_ITEM: "TMDB titles",
        SourceType.TMDB_PERSON: "TMDB person",
        SourceType.MDBLIST: "MDBList",
        SourceType.RADARR_TAG: "Radarr tags",
        SourceType.SONARR_TAG: "Sonarr tags",
    }
)

#: Labels Overture keeps on Plex items for smart collections' sources.
SOURCE_LABEL_PREFIX = "overture:"

_MOVIE_SOURCES = frozenset({SourceType.TMDB_COLLECTION, SourceType.RADARR_TAG})
_SHOW_SOURCES = frozenset({SourceType.SONARR_TAG})


def source_label(condition: SourceCondition) -> str:
    """The label marking a source's items, for Plex smart collections to filter on.

    A source with one identifier names it, so the label stays readable and
    stable (``overture:tmdb_person:5292:director``); others fall back to a
    digest of the whole source. Collections with the same source share it.
    """
    return f"{SOURCE_LABEL_PREFIX}{condition.source.type}:{_source_identity(condition)}"


def _source_identity(condition: SourceCondition) -> str:
    match condition.source:
        case TmdbCollectionSource(collection_id=identity):
            return str(identity)
        case TmdbPersonSource(person_id=identity, roles=roles):
            return f"{identity}:{'+'.join(sorted(roles))}"
        case TmdbListSource(list_ids=[identity]):
            return str(identity)
        case MdblistSource(identifiers=[identity]):
            return identity
        case RadarrTagSource(tags=[identity]) | SonarrTagSource(tags=[identity]):
            return identity
        case _:
            return hashlib.sha256(condition.key.encode()).hexdigest()[:8]


class SourceResolver:
    """Own the external clients sources read, and resolve sources to items."""

    def __init__(
        self,
        *,
        app_config: Settings,
        tmdb: TMDBClient,
        mdblist: MDBListClient,
        radarr: ArrClient | None = None,
        sonarr: ArrClient | None = None,
    ) -> None:
        self._config = app_config
        self._tmdb = tmdb
        self._mdblist = mdblist
        self._radarr = radarr or ArrClient(
            kind="radarr",
            base_url=app_config.RADARR_URL,
            api_key=app_config.RADARR_API_KEY.get_secret_value(),
            verify_tls=app_config.RADARR_VERIFY_TLS,
        )
        self._sonarr = sonarr or ArrClient(
            kind="sonarr",
            base_url=app_config.SONARR_URL,
            api_key=app_config.SONARR_API_KEY.get_secret_value(),
            verify_tls=app_config.SONARR_VERIFY_TLS,
        )

    async def close(self) -> None:
        """Close the clients this resolver owns."""
        await self._mdblist.close()
        await self._radarr.close()
        await self._sonarr.close()

    def unavailable(self, source: SourceType, media_type: MediaType) -> str | None:
        """Why a source cannot select items of the media type, if it cannot."""
        if source in _MOVIE_SOURCES and media_type is not MediaType.MOVIE:
            return f"{SOURCE_LABELS[source]} select movies only"
        if source in _SHOW_SOURCES and media_type is not MediaType.SHOW:
            return f"{SOURCE_LABELS[source]} select shows only"
        if source is SourceType.MDBLIST and not self._config.mdblist_configured:
            return "Set MDBLIST_API_KEY to use MDBList"
        if source is SourceType.RADARR_TAG and not self._radarr.configured:
            return "Set RADARR_URL and RADARR_API_KEY to use Radarr"
        if source is SourceType.SONARR_TAG and not self._sonarr.configured:
            return "Set SONARR_URL and SONARR_API_KEY to use Sonarr"
        if source.value.startswith("tmdb") and not self._config.tmdb_configured:
            return "Set TMDB_API_KEY to use TMDB"
        return None

    def require(self, source: SourceType, media_type: MediaType) -> None:
        """Reject a source that cannot select items of the media type."""
        if reason := self.unavailable(source, media_type):
            raise PublicServiceError(422, reason)

    async def radarr_tags(self) -> list[ArrTagRead]:
        """Return all tags configured in Radarr."""
        return [
            ArrTagRead(id=tag.id, label=tag.label)
            for tag in await self._radarr.list_tags()
        ]

    async def sonarr_tags(self) -> list[ArrTagRead]:
        """Return all tags configured in Sonarr."""
        return [
            ArrTagRead(id=tag.id, label=tag.label)
            for tag in await self._sonarr.list_tags()
        ]

    async def biography(self, source: TmdbPersonSource) -> str | None:
        """The person's TMDB biography, for a source that asks for it."""
        if not source.use_biography:
            return None
        person = await self._tmdb.get_person(source.person_id)
        return person.biography if person and person.biography else None

    async def resolve(
        self,
        source: CollectionSource,
        media_type: MediaType,
        items: Sequence[MediaItem],
    ) -> list[int]:
        """Return the IDs of the library items the source holds, in source order.

        Every source is read completely before membership changes, so a failed
        read raises instead of emptying the collection.
        """
        if isinstance(source, RadarrTagSource | SonarrTagSource):
            client = (
                self._radarr if isinstance(source, RadarrTagSource) else self._sonarr
            )
            matches = await client.external_ids_for_tags(source.tags)
            tmdb, tvdb, imdb = (
                set(matches.tmdb_ids),
                set(matches.tvdb_ids),
                set(matches.imdb_ids),
            )
            return [
                item.id or 0
                for item in items
                if item.tmdb_id in tmdb or item.tvdb_id in tvdb or item.imdb_id in imdb
            ]
        ranked = await self._tmdb_ids(source, media_type)
        rank: dict[int, int] = {}
        for index, tmdb_id in enumerate(ranked):
            rank.setdefault(tmdb_id, index)
        return [
            item.id or 0
            for item in sorted(
                (item for item in items if item.tmdb_id in rank),
                key=lambda item: (rank[item.tmdb_id or 0], item.id or 0),
            )
        ]

    async def _tmdb_ids(
        self,
        source: TmdbCollectionSource
        | TmdbItemSource
        | TmdbListSource
        | TmdbPersonSource
        | MdblistSource,
        media_type: MediaType,
    ) -> list[int]:
        match source:
            case MdblistSource():
                return [
                    tmdb_id
                    for identifier in source.identifiers
                    for tmdb_id in await self._mdblist.tmdb_ids(identifier, media_type)
                ]
            case TmdbListSource():
                return [
                    tmdb_id
                    for list_id in source.list_ids
                    for tmdb_id in await self._tmdb.get_list_ids(list_id, media_type)
                ]
            case TmdbItemSource():
                return list(source.tmdb_ids)
            case TmdbPersonSource():
                return list(
                    await self._tmdb.get_person_credits(
                        source.person_id, media_type, set(source.roles)
                    )
                )
            case TmdbCollectionSource():
                franchise = await self._tmdb.get_collection(source.collection_id)
                if franchise is None:
                    raise PublicServiceError(
                        404, "TMDB collection not found; membership was kept"
                    )
                return [
                    part.tmdb_id
                    for part in sorted(
                        franchise.parts,
                        key=lambda part: (part.release_date or "", part.tmdb_id),
                    )
                ]

    async def franchise_name(self, collection_id: int) -> str | None:
        """The TMDB name of a franchise, which TMDB's client memoizes."""
        franchise = await self._tmdb.get_collection(collection_id)
        return franchise.title if franchise else None
