"""On-demand media-server artwork ID resolution."""

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.db.session import Database
lazy from overture.domain import ArtType, MediaType
lazy from overture.services.server_identity import resolve_server_item_id
lazy from tests.runtime_helpers import NoopProviderRegistry, row_id


async def test_season_resolution_recovers_parent_without_tmdb(
    db_session: AsyncSession,
    database: Database,
) -> None:
    calls: list[tuple[object, ...]] = []

    class _Provider:
        async def find_item_id(self, item: MediaItem) -> str:
            calls.append(("item", item.tvdb_id))
            return "show-1"

        async def build_item_link(self, server_id: str) -> str:
            return f"https://server/{server_id}"

        async def find_season_id(self, server_id: str, season_num: int) -> str:
            calls.append(("season", server_id, season_num))
            return "season-1"

    item = MediaItem(id=1, media_type=MediaType.SHOW, title="Show", tvdb_id=123)
    season = Season(id=10, media_item_id=1, season_num=1)
    db_session.add(item)
    db_session.add(season)
    await db_session.commit()
    provider_registry = NoopProviderRegistry(_Provider())

    server_id = await resolve_server_item_id(
        row_id(item),
        ArtType.SEASON_POSTER,
        season.id,
        database=database,
        provider_registry=provider_registry,
    )

    assert server_id == "season-1"
    assert calls == [
        ("item", 123),
        ("season", "show-1", 1),
    ]
    await db_session.refresh(item)
    await db_session.refresh(season)
    assert item.server_item_id == "show-1"
    assert season.server_item_id == "season-1"


async def test_season_resolution_rejects_a_season_from_another_item(
    db_session: AsyncSession,
    database: Database,
) -> None:
    class _Provider:
        async def find_item_id(self, _item: MediaItem) -> str:
            raise AssertionError("provider lookup must not run")

    requested_item = MediaItem(
        id=1,
        media_type=MediaType.SHOW,
        title="Requested show",
    )
    other_item = MediaItem(id=2, media_type=MediaType.SHOW, title="Other show")
    season = Season(id=10, media_item_id=2, season_num=1)
    db_session.add_all([requested_item, other_item, season])
    await db_session.commit()

    assert (
        await resolve_server_item_id(
            row_id(requested_item),
            ArtType.SEASON_POSTER,
            season.id,
            database=database,
            provider_registry=NoopProviderRegistry(_Provider()),
        )
        is None
    )
