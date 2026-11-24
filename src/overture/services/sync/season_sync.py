"""Season upsert reconciliation for TV show media items."""

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...db.ledger import place_local
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...domain import ArtType, ServerAsset
lazy from ...media_servers.adapters import ServerSeason, image_version
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
        moved: bool = False,
    ) -> None:
        """Record one server's seasons of a show.

        The lead server describes the seasons: their titles, file counts and
        artwork. Any server adds a season the title lacks, and records its own
        ID of each. Each season's poster goes in the show's folder; *moved*
        says the show's folder changed.
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
        for season in {**existing_seasons, **listed}.values():
            place_local(
                season,
                (ServerAsset.SEASON_POSTER,),
                folder=item.folder_path is not None,
                moved=moved,
            )

        copies = CopyRepository(session)
        by_num = {s.num: s for s in season_data}
        for season_num, season in {**existing_seasons, **listed}.items():
            found = by_num.get(season_num)
            await copies.set_season_copy(
                season.id or 0,
                server_id,
                found.server_item_id if found else None,
                image_version(found.poster_url) if found else None,
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
