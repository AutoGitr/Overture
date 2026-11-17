"""Season upsert reconciliation for TV show media items."""

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...domain import ArtType
lazy from ...media_servers.adapters import ServerSeason
lazy from ...repositories.copies import CopyRepository
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
        server_id: int,
        lead: bool,
        only_missing_art: bool,
    ) -> None:
        """Record one server's seasons of a show.

        The lead server describes the seasons: their titles, file counts and
        artwork. Any server adds a season the title lacks, and records its own
        ID of each.
        """
        if not item.id:
            return

        existing_seasons = await SeasonRepository(session).map_by_number_for_item(
            item.id
        )
        listed: dict[int, Season] = {}
        poster_urls_by_season_num: dict[int, str | None] = {}

        for s in season_data:
            season_num = s.num
            poster_urls_by_season_num[season_num] = s.poster_url
            season = existing_seasons.get(season_num)
            season_title = s.title or (
                f"Season {season_num}" if season_num > 0 else "Specials"
            )
            if not season:
                season = Season(
                    media_item_id=item.id,
                    season_num=season_num,
                    title=season_title,
                    file_count=s.file_count,
                )
            elif lead:
                season.title = season_title
                season.file_count = s.file_count
            listed[season_num] = season
            session.add(season)

        if lead:
            for season_num, season in existing_seasons.items():
                if season_num not in listed:
                    season.file_count = 0
                    session.add(season)

        await session.flush()

        copies = CopyRepository(session)
        server_ids = {s.num: s.server_item_id for s in season_data}
        for season_num, season in {**existing_seasons, **listed}.items():
            await copies.set_season_id(
                season.id or 0, server_id, server_ids.get(season_num)
            )

        if not lead:
            return
        for season in listed.values():
            apply_provider_art_url(
                season,
                ArtType.SEASON_POSTER,
                poster_urls_by_season_num[season.season_num],
                resolved,
                only_missing=only_missing_art,
            )
