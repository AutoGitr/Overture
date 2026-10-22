"""Season upsert reconciliation for TV show media items."""

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...domain import ArtType
lazy from ...media_servers.adapters import ServerSeason
lazy from ...repositories.seasons import SeasonRepository
lazy from .art_urls import ResolvedArtUrls, apply_provider_art_url


class SeasonSynchronizer:
    """Create/update Season records from provider season snapshots."""

    async def upsert_seasons(
        self,
        session: AsyncSession,
        item: MediaItem,
        season_data: list[ServerSeason],
        resolved: ResolvedArtUrls,
        *,
        only_missing_art: bool,
    ) -> None:
        """Create or update Season records from server season data."""
        if not item.id:
            return

        existing_seasons = await SeasonRepository(session).map_by_number_for_item(
            item.id
        )
        all_seasons: list[Season] = list(existing_seasons.values())
        seen_season_nums: set[int] = set()
        poster_urls_by_season_num: dict[int, str | None] = {}

        for s in season_data:
            season_num = s.num
            seen_season_nums.add(season_num)
            poster_urls_by_season_num[season_num] = s.poster_url
            season = existing_seasons.get(season_num)
            season_title = s.title or (
                f"Season {season_num}" if season_num > 0 else "Specials"
            )
            file_count = s.file_count

            if not season:
                season = Season(
                    media_item_id=item.id,
                    season_num=season_num,
                    title=season_title,
                    file_count=file_count,
                )
                all_seasons.append(season)
            else:
                season.title = season_title
                season.file_count = file_count

            season.server_item_id = s.server_item_id

            session.add(season)

        for season_num, season in existing_seasons.items():
            if season_num not in seen_season_nums:
                season.file_count = 0
                session.add(season)

        await session.flush()

        for season in all_seasons:
            if season.season_num in poster_urls_by_season_num:
                apply_provider_art_url(
                    season,
                    ArtType.SEASON_POSTER,
                    poster_urls_by_season_num[season.season_num],
                    resolved,
                    only_missing=only_missing_art,
                )
