"""Missing titles of a collection's lists, and requesting them from Radarr or Sonarr."""

lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.settings import AppSettings, get_app_settings
lazy from ...domain import MediaType
lazy from ...repositories.collections import CollectionRepository
lazy from ...schemas.collections import (
    ArrTagRead,
    CollectionArrOptions,
    CollectionMissing,
    CollectionRequest,
    CollectionRequestResult,
    FilterGroup,
)
lazy from ...utils.errors import PublicServiceError
lazy from .access import CollectionAccess
lazy from .member_effects import MemberEffects
lazy from .rules import criteria as rule_criteria
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

    async def missing(
        self, collection_id: int, media_type: MediaType
    ) -> CollectionMissing:
        """Titles the collection's lists hold that its library lacks."""
        async with self._access.database.read_session() as session:
            row = await self._access.require(session, collection_id, media_type)
            rule = await CollectionRepository(session).rule(collection_id)
        if rule is None:
            return CollectionMissing(
                titles=[], requestable=self._sources.arr(media_type).configured
            )
        return await self._effects.missing(
            rule_criteria(rule),
            media_type,
            await self._access.library_items(row.library_id or "", media_type),
            region=await self._access.region(),
        )

    async def request_missing(
        self, collection_id: int, media_type: MediaType, body: CollectionRequest
    ) -> CollectionRequestResult:
        """Ask Radarr or Sonarr for missing titles, or for the chosen ones."""
        async with self._access.database.read_session() as session:
            row = await self._access.require(session, collection_id, media_type)
            rule = await CollectionRepository(session).rule(collection_id)
            settings = await get_app_settings(session)
        if not self._sources.arr(media_type).configured:
            raise PublicServiceError(
                422,
                "Set up Radarr to request movies"
                if media_type is MediaType.MOVIE
                else "Set up Sonarr to request shows",
            )
        return await self.request(
            media_type,
            rule_criteria(rule) if rule is not None else FilterGroup(),
            await self._access.library_items(row.library_id or "", media_type),
            settings,
            body.tmdb_ids,
        )

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
