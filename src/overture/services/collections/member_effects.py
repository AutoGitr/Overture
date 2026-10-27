"""What a sync does beyond membership: requests, Radarr and Sonarr tags, Home order."""

lazy from collections.abc import Sequence

lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.settings import AppSettings
lazy from ...domain import FilterOperator, MediaType
lazy from ...integrations.arr import ArrRequest, ArrTitle
lazy from ...integrations.tmdb import TMDBClient
lazy from ...schemas.collections import (
    CollectionMissing,
    CollectionMissingTitle,
    CollectionRequestResult,
    FilterGroup,
    RadarrTagSource,
    SonarrTagSource,
)
lazy from ...utils.errors import PublicServiceError
lazy from .sources import SourceResolver

#: Missing titles the panel lists, each looked up on TMDB once.
MISSING_LIMIT = 100


class MemberEffects:
    """Compare a collection's lists with the library, and act on Radarr or Sonarr."""

    def __init__(self, *, sources: SourceResolver, tmdb: TMDBClient) -> None:
        self._sources = sources
        self._tmdb = tmdb

    async def missing_ids(
        self,
        criteria: FilterGroup,
        media_type: MediaType,
        items: Sequence[MediaItem],
        *,
        region: str,
    ) -> list[int]:
        """TMDB IDs the criteria's lists hold and the library lacks, in list order.

        Radarr and Sonarr tags hold titles the library has or is downloading,
        so only TMDB and MDBList lists count.
        """
        have = {item.tmdb_id for item in items if item.tmdb_id is not None}
        found: dict[int, None] = {}
        for condition in criteria.source_conditions():
            source = condition.source
            if condition.operator is not FilterOperator.IS or isinstance(
                source, RadarrTagSource | SonarrTagSource
            ):
                continue
            for tmdb_id in await self._sources.tmdb_ids(
                source, media_type, region=region
            ):
                if tmdb_id not in have:
                    found.setdefault(tmdb_id, None)
        return list(found)

    async def missing(
        self,
        criteria: FilterGroup,
        media_type: MediaType,
        items: Sequence[MediaItem],
        *,
        region: str,
    ) -> CollectionMissing:
        """The first missing titles, and whether Radarr or Sonarr has each."""
        ids = await self.missing_ids(criteria, media_type, items, region=region)
        arr = self._sources.arr(media_type)
        held = (
            _external_ids(await arr.titles(), media_type)
            if arr.configured
            else set[int]()
        )
        titles: list[CollectionMissingTitle] = []
        for tmdb_id in ids[:MISSING_LIMIT]:
            details = await self._tmdb.get_details(media_type, tmdb_id)
            if details is None:
                continue
            external = tmdb_id if media_type is MediaType.MOVIE else details.tvdb_id
            titles.append(
                CollectionMissingTitle(
                    tmdb_id=tmdb_id,
                    title=details.title,
                    year=details.year,
                    poster_url=details.poster_url,
                    requested=external in held,
                )
            )
        return CollectionMissing(
            titles=titles,
            truncated=len(ids) > MISSING_LIMIT,
            requestable=arr.configured,
        )

    async def request(
        self, media_type: MediaType, tmdb_ids: Sequence[int], settings: AppSettings
    ) -> CollectionRequestResult:
        """Add titles to Radarr or Sonarr with the configured folder and profile."""
        arr = self._sources.arr(media_type)
        request = _arr_request(media_type, settings)
        held = _external_ids(await arr.titles(), media_type)
        result = CollectionRequestResult()
        for tmdb_id in tmdb_ids:
            try:
                external = await self._external_id(media_type, tmdb_id)
                if external is None:
                    result.errors.append(f"TMDB {tmdb_id} has no TVDB ID for Sonarr")
                elif external in held:
                    result.present += 1
                else:
                    await arr.add(external, request)
                    held.add(external)
                    result.requested += 1
            except PublicServiceError as exc:
                result.errors.append(f"TMDB {tmdb_id}: {exc.message}")
        return result

    async def tag(
        self, media_type: MediaType, tag: str, members: Sequence[MediaItem]
    ) -> None:
        """Give the tag to exactly the members among Radarr's or Sonarr's titles."""
        arr = self._sources.arr(media_type)
        tag_id = await arr.tag_id(tag)
        wanted = {
            external
            for item in members
            if (
                external := item.tmdb_id
                if media_type is MediaType.MOVIE
                else item.tvdb_id
            )
            is not None
        }
        titles = await arr.titles()
        add = [
            title.id
            for title in titles
            if _external_id(title, media_type) in wanted and tag_id not in title.tags
        ]
        remove = [
            title.id
            for title in titles
            if tag_id in title.tags and _external_id(title, media_type) not in wanted
        ]
        await arr.edit_tag(tag_id, add, add=True)
        await arr.edit_tag(tag_id, remove, add=False)

    async def _external_id(self, media_type: MediaType, tmdb_id: int) -> int | None:
        """Radarr adds by TMDB ID; Sonarr by TVDB ID, which TMDB knows."""
        if media_type is MediaType.MOVIE:
            return tmdb_id
        details = await self._tmdb.get_details(media_type, tmdb_id)
        return details.tvdb_id if details else None


def _arr_request(media_type: MediaType, settings: AppSettings) -> ArrRequest:
    movie = media_type is MediaType.MOVIE
    folder = settings.radarr_root_folder if movie else settings.sonarr_root_folder
    profile = (
        settings.radarr_quality_profile_id
        if movie
        else settings.sonarr_quality_profile_id
    )
    if not folder or profile is None:
        name = "Radarr" if movie else "Sonarr"
        raise PublicServiceError(
            422, f"Choose a {name} root folder and quality profile in Settings"
        )
    return ArrRequest(
        root_folder=folder,
        quality_profile_id=profile,
        search=settings.radarr_search if movie else settings.sonarr_search,
    )


def _external_id(title: ArrTitle, media_type: MediaType) -> int | None:
    return title.tmdb_id if media_type is MediaType.MOVIE else title.tvdb_id


def _external_ids(titles: Sequence[ArrTitle], media_type: MediaType) -> set[int]:
    return {
        external
        for title in titles
        if (external := _external_id(title, media_type)) is not None
    }
