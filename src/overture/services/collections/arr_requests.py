"""Missing titles of a collection's lists, and requesting them from Radarr or Sonarr."""

lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.settings import AppSettings, get_app_settings
lazy from ...domain import MediaType
lazy from ...schemas.collections import (
    ArrTagRead,
    CollectionArrOptions,
    CollectionMissing,
    CollectionMissingTitle,
    CollectionRequest,
    CollectionRequestResult,
    FilterGroup,
)
lazy from ...utils.errors import PublicServiceError
lazy from .access import CollectionAccess
lazy from .member_effects import MemberEffects
lazy from .rules import criteria_of
lazy from .sources import SourceResolver


class CollectionArr:
    """Radarr and Sonarr as collections use them: tags, options and requests."""

    def __init__(
        self,
        *,
        access: CollectionAccess,
        sources: SourceResolver,
        effects: MemberEffects,
    ) -> None:
        self._access = access
        self._sources = sources
        self._effects = effects

    async def radarr_tags(self) -> list[ArrTagRead]:
        """Return all tags configured in Radarr."""
        return await self._sources.radarr_tags()

    async def sonarr_tags(self) -> list[ArrTagRead]:
        """Return all tags configured in Sonarr."""
        return await self._sources.sonarr_tags()

    async def options(self, media_type: MediaType) -> CollectionArrOptions:
        """The root folders and quality profiles Radarr or Sonarr offers."""
        options = await self._sources.arr(media_type).options()
        return CollectionArrOptions(
            root_folders=list(options.root_folders),
            quality_profiles=[
                ArrTagRead(id=profile.id, label=profile.label)
                for profile in options.quality_profiles
            ],
        )

    async def missing(self, collection_id: int) -> CollectionMissing:
        """Titles the collection's lists hold that its libraries lack.

        Each title is named from TMDB, so none are listed without a TMDB key.
        """
        async with self._access.database.read_session() as session:
            row = await self._access.require(session, collection_id)
        requestable = any(
            self._sources.arr(media_type).configured for media_type in row.media_types
        )
        if row.rule is None or not self._access.app_config.tmdb_configured:
            return CollectionMissing(titles=[], requestable=requestable)
        found: dict[tuple[MediaType, int], CollectionMissingTitle] = {}
        truncated = False
        region = await self._access.region()
        for part in row.libraries:
            if part.criteria is None:
                continue
            missing = await self._effects.missing(
                criteria_of(part),
                part.media_type,
                await self._access.library_items(part.library_id, part.media_type),
                region=region,
            )
            truncated = truncated or missing.truncated
            for title in missing.titles:
                found.setdefault((title.media_type, title.tmdb_id), title)
        return CollectionMissing(
            titles=list(found.values()), truncated=truncated, requestable=requestable
        )

    async def request_missing(
        self, collection_id: int, body: CollectionRequest
    ) -> CollectionRequestResult:
        """Ask Radarr or Sonarr for missing titles, or for the chosen ones."""
        async with self._access.database.read_session() as session:
            row = await self._access.require(session, collection_id)
            settings = await get_app_settings(session)
        titles = body.titles
        wanted = {title.media_type for title in titles or ()}
        result = CollectionRequestResult()
        for part in row.libraries:
            media_type = part.media_type
            if part.criteria is None or (
                titles is not None and media_type not in wanted
            ):
                continue
            if not self._sources.arr(media_type).configured:
                if titles is not None:
                    raise PublicServiceError(
                        422,
                        "Set up Radarr to request movies"
                        if media_type is MediaType.MOVIE
                        else "Set up Sonarr to request shows",
                    )
                continue
            done = await self.request(
                media_type,
                criteria_of(part),
                await self._access.library_items(part.library_id, media_type),
                settings,
                [t.tmdb_id for t in titles if t.media_type is media_type]
                if titles is not None
                else None,
            )
            result.requested += done.requested
            result.present += done.present
            result.errors += done.errors
            # A title is requested once, however many libraries could hold it.
            wanted.discard(media_type)
        return result

    async def request(
        self,
        media_type: MediaType,
        criteria: FilterGroup,
        items: list[MediaItem],
        settings: AppSettings,
        tmdb_ids: list[int] | None = None,
    ) -> CollectionRequestResult:
        """Request the given titles, or every missing one, from Radarr or Sonarr."""
        if tmdb_ids is None:
            tmdb_ids = await self._effects.missing_ids(
                criteria, media_type, items, region=settings.tmdb_region
            )
        result = await self._effects.request(media_type, tmdb_ids, settings)
        if result.errors and not result.requested:
            raise PublicServiceError(502, "; ".join(result.errors[:3]))
        return result
