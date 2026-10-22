"""Media-item lookups that only identify a row skip loading its artwork."""

lazy from datetime import UTC, datetime
lazy from pathlib import Path

lazy import pytest
lazy from sqlalchemy.exc import InvalidRequestError
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.db.art_slots import find_art_slot, write_art_slot
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.session import Database
lazy from overture.domain import ArtType, MediaType
lazy from overture.repositories.media_items import MediaItemRepository


async def test_a_match_only_lookup_finds_the_row_but_refuses_its_artwork(
    db_session: AsyncSession, database: Database
) -> None:
    item = MediaItem(
        title="Movie",
        media_type=MediaType.MOVIE,
        folder_path="/media/Movie",
        server_item_id="server-1",
        tmdb_id=603,
    )
    write_art_slot(item, ArtType.POSTER, file_hash="hash")
    db_session.add(item)
    await db_session.commit()

    async with database.read_session() as session:
        repo = MediaItemRepository(session)
        found = [
            await repo.find_by_folder_path(
                "/media/Movie/", MediaType.MOVIE, load_art=False
            ),
            await repo.find_by_server_id("server-1", MediaType.MOVIE, load_art=False),
            await repo.find_by_external_guids(
                {"tmdb": "603"}, MediaType.MOVIE, load_art=False
            ),
        ]
    async with database.read_session() as session:
        loaded = await MediaItemRepository(session).find_by_folder_path(
            "/media/Movie", MediaType.MOVIE
        )

    assert [row.id if row else None for row in found] == [item.id] * 3
    for row in found:
        assert row is not None
        with pytest.raises(InvalidRequestError):
            find_art_slot(row, ArtType.POSTER)
    assert loaded is not None
    slot = find_art_slot(loaded, ArtType.POSTER)
    assert slot is not None
    assert slot.file_hash == "hash"


@pytest.fixture
async def populated_repository(
    db_session: AsyncSession, tmp_path: Path
) -> MediaItemRepository:
    removed = datetime(2026, 1, 1, tzinfo=UTC)
    db_session.add_all(
        [
            MediaItem(
                id=1,
                title="Zulu",
                media_type=MediaType.MOVIE,
                library_id="movies",
                folder_path=str(tmp_path / "movies" / "Zulu"),
                server_item_id="one",
                tmdb_id=10,
                tvdb_id=20,
                imdb_id="tt30",
                director="Director",
                director_etag="v1",
            ),
            MediaItem(
                id=2,
                title="Alpha",
                media_type=MediaType.MOVIE,
                library_id="movies",
                folder_path=str(tmp_path / "movies" / "Alpha"),
                server_item_id="two",
                monitored=False,
            ),
            MediaItem(
                id=3,
                title="Show",
                media_type=MediaType.SHOW,
                library_id="shows",
                folder_path=str(tmp_path / "shows" / "Show"),
                server_item_id="three",
                tmdb_id=10,
                director_etag="v1",
            ),
            MediaItem(
                id=4,
                title="Removed",
                media_type=MediaType.MOVIE,
                library_id="movies",
                folder_path=str(tmp_path / "movies" / "Zulu"),
                server_item_id="one",
                tmdb_id=10,
                server_removed_at=removed,
            ),
            MediaItem(
                id=5,
                title="No folder",
                media_type=MediaType.MOVIE,
                library_id="movies",
                server_item_id="five",
                director_etag="v2",
            ),
            MediaItem(id=6, title="Unconnected", media_type=MediaType.SHOW, tmdb_id=11),
        ]
    )
    await db_session.commit()
    return MediaItemRepository(db_session)


async def test_lookup_preference_exclusions_and_provider_priority(
    populated_repository: MediaItemRepository, tmp_path: Path
) -> None:
    repo = populated_repository
    found = await repo.find_by_server_id("one", "movie")
    assert found is not None
    assert found.id == 1
    found = await repo.find_by_server_id("one", "movie", exclude_item_ids={1})
    assert found is not None
    assert found.id == 4
    assert await repo.find_by_server_id("one", "show") is None
    found = await repo.find_by_folder_path(
        str(tmp_path / "movies" / "Zulu"), "movie", exclude_item_ids={1}
    )
    assert found is not None
    assert found.id == 4
    assert await repo.find_by_external_guids({"tmdb": "invalid"}, "movie") is None
    found = await repo.find_by_external_guids(
        {"tmdb": "10"}, "movie", exclude_item_ids={1}
    )
    assert found is not None
    assert found.id == 4
    found = await repo.find_by_external_guids(
        {"tmdb": "10", "imdb": "tt30"}, "movie", server_item_id="one"
    )
    assert found is not None
    assert found.id == 1


async def test_folder_batch_preserves_requested_spelling_and_prefers_present(
    populated_repository: MediaItemRepository, tmp_path: Path
) -> None:
    repo = populated_repository
    requested = (tmp_path / "movies" / "Zulu").as_posix() + "/"
    found = await repo.by_folder_paths([requested, "/missing"])
    assert {folder: item.id for folder, item in found.items()} == {requested: 1}
    assert await repo.by_folder_paths([]) == {}


async def test_identifier_and_director_maps_filter_and_prefer_present_rows(
    populated_repository: MediaItemRepository,
) -> None:
    repo = populated_repository
    assert await repo.ids_by_tmdb_ids(MediaType.MOVIE, [10, 999]) == {10: 1}
    assert await repo.ids_by_tmdb_ids(MediaType.SHOW, [10, 11]) == {10: 3, 11: 6}
    assert await repo.ids_by_tmdb_ids(MediaType.MOVIE, []) == {}
    assert await repo.directors_by_version([]) == {}
    assert await repo.directors_by_version(["one", "two", "three", "five"]) == {
        ("one", "v1"): "Director",
        ("five", "v2"): None,
    }


async def test_bulk_targets_apply_scope_monitoring_and_id_pagination(
    populated_repository: MediaItemRepository,
) -> None:
    repo = populated_repository
    assert [item.id for item in await repo.list_bulk_targets()] == [1, 3]
    assert [
        item.id
        for item in await repo.list_bulk_targets(["movies"], include_unmonitored=True)
    ] == [2, 1]
    assert [
        item.id
        for item in await repo.list_bulk_targets(
            item_ids=[1, 2, 3], include_unmonitored=True, after_id=1, limit=1
        )
    ] == [2]
    assert await repo.list_bulk_targets(item_ids=[]) == []
    assert [
        item.id
        for item in await repo.list_monitored_with_folder_paths(
            item_ids=[1, 3], after_id=1, limit=1
        )
    ] == [3]
    assert await repo.list_monitored_with_folder_paths(item_ids=[]) == []


async def test_visible_folder_queries_intersect_filters_and_include_unmonitored(
    populated_repository: MediaItemRepository,
) -> None:
    repo = populated_repository
    assert [item.id for item in await repo.list_visible_with_folder_paths()] == [
        1,
        2,
        3,
    ]
    assert [
        item.id
        for item in await repo.list_visible_with_folder_paths(
            media_type=MediaType.MOVIE,
            library_id="movies",
            library_ids=["movies"],
            item_ids=[1, 2, 3],
            after_id=1,
            limit=1,
        )
    ] == [2]
    assert await repo.list_visible_with_folder_paths(library_ids=[]) == []
    assert await repo.list_visible_with_folder_paths(item_ids=[]) == []
    assert [
        item.id
        for item in await repo.list_visible_with_server_ids(
            ["movies"], after_id=1, limit=1
        )
    ] == [2]
    assert [item.id for item in await repo.list_visible_with_server_ids()] == [
        2,
        5,
        1,
        3,
    ]
    assert [item.id for item in await repo.list_unconnected_tmdb_shows()] == [6]


async def test_counts_folders_and_visible_lists_respect_removal(
    populated_repository: MediaItemRepository, tmp_path: Path
) -> None:
    repo = populated_repository
    assert await repo.library_counts() == {"movies": 3, "shows": 1}
    assert await repo.library_counts(MediaType.SHOW) == {"shows": 1}
    assert [item.id for item in await repo.list_visible(MediaType.MOVIE)] == [2, 5, 1]
    assert [item.id for item in await repo.list_visible()] == [2, 5, 1, 3, 6]
    assert sorted(await repo.folder_paths()) == sorted(
        str(tmp_path / area / title)
        for area, title in [
            ("movies", "Zulu"),
            ("movies", "Alpha"),
            ("shows", "Show"),
            ("movies", "Zulu"),
        ]
    )
    assert await repo.item_folders([1, 4, 5, 999]) == [
        (str(tmp_path / "movies" / "Zulu"), "movie")
    ]
    assert await repo.folder_roots() == {
        "movies": [str(tmp_path / "movies")],
        "shows": [str(tmp_path / "shows")],
    }


async def test_stamps_only_update_the_requested_rows(
    populated_repository: MediaItemRepository, db_session: AsyncSession
) -> None:
    repo = populated_repository
    when = datetime(2026, 2, 1, tzinfo=UTC)
    await repo.mark_matched(set(), when)
    await repo.mark_synced([], when)
    await repo.mark_matched({1, 2, 999}, when)
    await repo.mark_synced([1, 3, 999], when)
    await db_session.commit()
    db_session.expire_all()
    rows = {item.id: item for item in await repo.list_visible()}
    assert {key for key, item in rows.items() if item.last_matched_at == when} == {1, 2}
    assert {key for key, item in rows.items() if item.last_synced_at == when} == {1, 3}
    assert {key for key, item in rows.items() if item.server_verified_at == when} == {
        1,
        3,
    }
