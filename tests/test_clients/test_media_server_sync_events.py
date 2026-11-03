"""Media-server sync library event behavior."""

lazy import os
lazy from collections.abc import AsyncIterator, Callable, Collection
lazy from datetime import UTC, datetime
lazy from pathlib import Path
lazy from typing import Any, cast, override

lazy import pytest
lazy from PIL import Image
lazy from sqlalchemy.ext.asyncio import async_sessionmaker
lazy from sqlmodel import select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.session import Database
lazy from overture.domain import MediaType, ServerAsset
lazy from overture.jobs.progress_log import JobLogEntry
lazy from overture.jobs.tally import SyncTally
lazy from overture.media_servers.adapters import ServerItem, SyncItemResult
lazy from overture.media_servers.jellyfin import JellyfinProvider
lazy from overture.services.sync.reconciler import LibraryReconciler
lazy from overture.utils.audio import ThemeAudioMetadata
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import NoopDownloads, make_local_assets
lazy from tests.sync_helpers import sync_full


class Provider(JellyfinProvider):
    """A media server listing fixed items; it must never be refreshed."""

    def __init__(self, items: list[ServerItem], *, app_config: Settings) -> None:
        super().__init__(app_config=app_config)
        self.items = items
        self.refresh_calls: list[str] = []

    @override
    async def iter_items(
        self, library_ids: list[str] | None = None
    ) -> AsyncIterator[list[ServerItem]]:
        if not library_ids:
            yield self.items
        else:
            yield [item for item in self.items if item.library_id in library_ids]

    @override
    async def refresh_item(
        self, item_id: str, *, unlock: Collection[ServerAsset]
    ) -> None:
        self.refresh_calls.append(item_id)
        raise AssertionError("pull-only sync must not refresh media-server items")


class DirectorProvider(Provider):
    def __init__(
        self, directors: dict[str, str | None], *, app_config: Settings
    ) -> None:
        super().__init__([], app_config=app_config)
        self.directors = directors
        self.director_calls: list[list[str]] = []

    @override
    async def get_directors(self, server_item_ids: list[str]) -> dict[str, str | None]:
        self.director_calls.append(server_item_ids)
        return {
            key: self.directors[key] for key in server_item_ids if key in self.directors
        }


def _server_item(
    item_id: str,
    title: str,
    library_id: str = "lib1",
    director: str | None = None,
    folder_path: str | None = None,
    media_type: MediaType = MediaType.MOVIE,
    director_etag: str | None = None,
) -> ServerItem:
    return ServerItem(
        id=item_id,
        title=title,
        year=1979,
        guids={},
        media_type=media_type,
        poster_url=None,
        background_url=None,
        server_link=f"https://server/items/{item_id}",
        library_id=library_id,
        director=director,
        director_etag=director_etag,
        folder_path=folder_path,
    )


async def test_deferred_directors_are_fetched_only_when_the_etag_changes(
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    async with isolated_session_factory() as session:
        session.add_all(
            [
                MediaItem(
                    media_type=MediaType.MOVIE,
                    title="Brazil",
                    server_item_id="same",
                    director="Terry Gilliam",
                    director_etag="v1",
                ),
                MediaItem(
                    media_type=MediaType.MOVIE,
                    title="Alien",
                    server_item_id="changed",
                    director="Someone Else",
                    director_etag="v1",
                ),
            ]
        )
        await session.commit()
    provider = DirectorProvider(
        {"changed": "Ridley Scott", "new": "John Carpenter", "same": "Wrong"},
        app_config=app_config,
    )
    reconciler = LibraryReconciler(
        publisher=NullEventPublisher(),
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=NoopDownloads(),
        app_config=app_config,
        database=database,
    )
    items = [
        _server_item("same", "Brazil", director_etag="v1"),
        _server_item("changed", "Alien", director_etag="v2"),
        _server_item("new", "The Thing", director_etag="v1"),
        _server_item("gone", "Gone", director_etag="v1"),
        _server_item("inline", "Inline", director="Plex Director"),
        _server_item("show", "Show", media_type=MediaType.SHOW),
    ]

    await reconciler.fill_deferred_directors(provider, items)

    assert provider.director_calls == [["changed", "new", "gone"]]
    assert [(item.director, item.director_etag) for item in items] == [
        ("Terry Gilliam", "v1"),
        ("Ridley Scott", "v2"),
        ("John Carpenter", "v1"),
        (None, None),
        ("Plex Director", None),
        (None, None),
    ]

    await sync_full(reconciler, items)
    async with isolated_session_factory() as session:
        stored = {
            item.server_item_id: (item.director, item.director_etag)
            for item in (await session.exec(select(MediaItem))).all()
        }
    assert stored["changed"] == ("Ridley Scott", "v2")
    assert stored["new"] == ("John Carpenter", "v1")
    assert stored["gone"] == (None, None)

    unchanged = [_server_item("changed", "Alien", director_etag="v2")]
    await reconciler.fill_deferred_directors(provider, unchanged)
    assert len(provider.director_calls) == 1
    assert unchanged[0].director == "Ridley Scott"


async def test_failed_stamp_never_replaces_the_sync_error(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    reconciler = LibraryReconciler(
        publisher=NullEventPublisher(),
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=NoopDownloads(),
        app_config=app_config,
        database=database,
    )
    stamped: list[set[int]] = []

    async def reconcile(
        _item: ServerItem, _seen: set[int], **_kwargs: object
    ) -> SyncItemResult:
        return SyncItemResult(item_id=42, media_type=MediaType.MOVIE)

    async def report(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("progress failed")

    async def stamp(item_ids: set[int]) -> None:
        stamped.append(set(item_ids))
        raise OSError("disk full")

    monkeypatch.setattr(reconciler, "_reconcile_one", reconcile)
    monkeypatch.setattr(reconciler, "_report", report)
    monkeypatch.setattr(reconciler, "_mark_synced", stamp)
    with pytest.raises(RuntimeError, match="progress failed"):
        await sync_full(reconciler, [_server_item("a", "Alien")])
    assert stamped == [{42}]


@pytest.mark.parametrize("stop_after", [None, 2])
async def test_sync_progress_and_result_share_partial_counters(
    stop_after: int | None,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    reconciler = LibraryReconciler(
        publisher=NullEventPublisher(),
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=NoopDownloads(),
        app_config=app_config,
        database=database,
    )
    tally = SyncTally()
    progress: list[dict[str, int | None]] = []

    async def reconcile(
        item: ServerItem, _seen: set[int], **_kwargs: object
    ) -> SyncItemResult | str:
        if item.id == "b":
            return "disk unavailable"
        return SyncItemResult(
            item_id=42 if item.id == "a" else 43,
            media_type=MediaType.MOVIE,
            created=item.id == "a",
        )

    async def record_progress(_entry: JobLogEntry) -> None:
        progress.append(tally.counters())

    monkeypatch.setattr(reconciler, "_reconcile_one", reconcile)
    result = await sync_full(
        reconciler,
        [_server_item(key, key) for key in ("a", "b", "c")],
        tally=tally,
        progress_cb=record_progress,
        stop_check=lambda: stop_after is not None and tally.done >= stop_after,
    )
    assert result.tally is tally
    assert result.created_item_ids == [42]
    assert [step["done"] for step in progress] == ([1, 2] if stop_after else [1, 2, 3])
    assert progress[-1] == {
        "done": 2 if stop_after else 3,
        "total": 3,
        "errors": 1,
        "added": 1,
        "updated": 0,
        "unchanged": 0 if stop_after else 1,
        "removed": 0,
    }


async def test_recent_sync_processes_movies_then_shows_in_title_order(
    *, app_config: Settings, database: Database
) -> None:
    reconciler = LibraryReconciler(
        publisher=NullEventPublisher(),
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=NoopDownloads(),
        app_config=app_config,
        database=database,
    )

    lines: list[str] = []

    async def record(entry: JobLogEntry) -> None:
        lines.append(entry.format())

    # A full sync takes the server's listing order, which lists movie
    # libraries first; recent items arrive in any order and are sorted alike.
    await reconciler.sync_recent(
        [
            _server_item("show-z", "Zulu Show", media_type=MediaType.SHOW),
            _server_item("movie-z", "Zulu Movie"),
            _server_item("show-a", "Alpha Show", media_type=MediaType.SHOW),
            _server_item("movie-a", "Alpha Movie"),
        ],
        progress_cb=record,
    )

    assert lines == [
        "Added Alpha Movie - new library item",
        "Added Zulu Movie - new library item",
        "Added Alpha Show - new library item",
        "Added Zulu Show - new library item",
    ]


async def test_sync_keeps_distinct_server_items_with_identical_titles(
    monkeypatch: pytest.MonkeyPatch,
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    provider = Provider(
        [
            _server_item("original", "All Quiet on the Western Front"),
            _server_item("remake", "All Quiet on the Western Front"),
        ],
        app_config=app_config,
    )
    reconciler = LibraryReconciler(
        publisher=NullEventPublisher(),
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=NoopDownloads(),
        app_config=app_config,
        database=database,
    )
    server_items = [item async for page in provider.iter_items() for item in page]
    stats = await sync_full(reconciler, server_items)

    async with isolated_session_factory() as session:
        items = list(
            (
                await session.exec(
                    select(MediaItem).where(
                        MediaItem.title == "All Quiet on the Western Front"
                    )
                )
            ).all()
        )

    assert stats.tally.added == 2
    assert stats.tally.unchanged == 0
    assert {item.server_item_id for item in items} == {"original", "remake"}


async def test_sync_emits_targeted_upserts_and_removals(
    monkeypatch: pytest.MonkeyPatch,
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    events: list[tuple[str, object]] = []

    class RecordingPublisher:
        async def broadcast(
            self, event: str, payload: Any = None, **_kwargs: object
        ) -> None:
            events.append((event, payload))

        async def broadcast_built(
            self, builder: Callable[[], tuple[str, Any] | None]
        ) -> bool:
            built = builder()
            if built is None:
                return False
            event, payload = built
            events.append((event, payload))
            return True

    async with isolated_session_factory() as session:
        session.add_all(
            [
                MediaItem(
                    id=1,
                    media_type=MediaType.MOVIE,
                    title="Removed",
                    server_item_id="removed",
                    library_id="lib1",
                ),
                MediaItem(
                    id=2,
                    media_type=MediaType.MOVIE,
                    title="Revived",
                    server_item_id="revived",
                    library_id="lib1",
                    server_removed_at=datetime(2026, 1, 1, tzinfo=UTC),
                ),
                MediaItem(
                    id=3,
                    media_type=MediaType.MOVIE,
                    title="Changed",
                    server_item_id="changed",
                    library_id="lib1",
                ),
                MediaItem(
                    id=4,
                    media_type=MediaType.MOVIE,
                    title="Skipped",
                    year=1979,
                    server_item_id="skipped",
                    server_link="https://server/items/skipped",
                    library_id="lib1",
                ),
                MediaItem(
                    id=5,
                    media_type=MediaType.MOVIE,
                    title="Out of Scope",
                    server_item_id="out-of-scope",
                    library_id="lib2",
                ),
                MediaItem(
                    id=6,
                    media_type=MediaType.MOVIE,
                    title="Preserved Year",
                    year=1980,
                    director="Existing Director",
                    server_item_id="preserved-year",
                    server_link="https://server/items/preserved-year",
                    library_id="lib1",
                ),
            ]
        )
        await session.commit()

    provider = Provider(
        [
            _server_item("revived", "Revived"),
            _server_item("new", "New"),
            _server_item("changed", "Changed", director="Ridley Scott"),
            _server_item("skipped", "Skipped"),
            _server_item(
                "preserved-year", "Preserved Year", director="Existing Director"
            ),
        ],
        app_config=app_config,
    )
    publisher = RecordingPublisher()
    reconciler = LibraryReconciler(
        publisher=publisher,
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=NoopDownloads(),
        app_config=app_config,
        database=database,
    )
    pages = provider.iter_items(["lib1"])
    server_items = [item async for page in pages for item in page]
    lines: list[str] = []

    async def record(entry: JobLogEntry) -> None:
        lines.append(entry.format())

    stats = await sync_full(
        reconciler, server_items, library_ids=["lib1"], progress_cb=record
    )

    async with isolated_session_factory() as session:
        removed = await session.get(MediaItem, 1)
        revived = await session.get(MediaItem, 2)
        changed = await session.get(MediaItem, 3)
        out_of_scope = await session.get(MediaItem, 5)
        preserved_year = await session.get(MediaItem, 6)

    assert stats.tally.added == 1
    assert stats.tally.errors == 0
    assert stats.created_item_ids
    # Every outcome is one line, and each counter counts exactly its lines.
    assert sorted(lines) == [
        "Added New - new library item",
        "Removed Removed - no longer on the media server; hidden from the library",
        "Unchanged Preserved Year - matches the media server and the local files",
        "Unchanged Skipped - matches the media server and the local files",
        "Updated Changed - changed: metadata",
        "Updated Revived - changed: metadata",
    ]
    assert (
        stats.tally.added,
        stats.tally.updated,
        stats.tally.unchanged,
        stats.tally.removed,
    ) == (1, 2, 2, 1)
    assert stats.tally.done == stats.tally.total == 5
    assert provider.refresh_calls == []
    assert removed is not None
    assert removed.server_removed_at is not None
    assert revived is not None
    assert revived.server_removed_at is None
    assert changed is not None
    assert changed.director == "Ridley Scott"
    assert changed.year == 1979
    assert preserved_year is not None
    assert preserved_year.year == 1980
    assert preserved_year.director == "Existing Director"
    assert out_of_scope is not None
    assert out_of_scope.server_removed_at is None

    event_names = [event for event, _ in events]
    assert event_names.count("library.item.upserted") == 3
    assert event_names.count("library.item.removed") == 1
    upserted_titles: list[str] = []
    removed_ids: list[int] = []
    for event, raw_payload in events:
        assert isinstance(raw_payload, dict)
        payload = cast("dict[str, Any]", raw_payload)
        if event == "library.item.upserted":
            raw_item = payload["item"]
            assert isinstance(raw_item, dict)
            item_payload = cast("dict[str, Any]", raw_item)
            upserted_titles.append(str(item_payload["title"]))
        if event == "library.item.removed":
            removed_ids.append(int(payload["media_item_id"]))

    # A full sync reconciles in listing order.
    assert upserted_titles == ["Revived", "New", "Changed"]
    assert removed_ids == [1]


async def test_sync_emits_upsert_when_only_asset_state_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    events: list[tuple[str, object]] = []

    async def probe(_path: Path) -> ThemeAudioMetadata:
        assert not database.write_lock.locked()
        return ThemeAudioMetadata(duration=35)

    monkeypatch.setattr(
        "overture.services.local_assets.theme.ffprobe_theme_metadata", probe
    )

    class RecordingPublisher:
        async def broadcast(
            self, event: str, payload: Any = None, **_kwargs: object
        ) -> None:
            events.append((event, payload))

        async def broadcast_built(
            self, builder: Callable[[], tuple[str, Any] | None]
        ) -> bool:
            built = builder()
            if built is None:
                return False
            event, payload = built
            events.append((event, payload))
            return True

    movie_dir = tmp_path / "Movie"
    movie_dir.mkdir()
    Image.new("RGB", (8, 8), color="red").save(movie_dir / "poster.jpg")
    (movie_dir / "theme.mp3").write_bytes(b"local theme")

    async with isolated_session_factory() as session:
        session.add(
            MediaItem(
                id=10,
                media_type=MediaType.MOVIE,
                title="Movie",
                year=1979,
                tmdb_id=123,
                folder_path=str(movie_dir),
                server_item_id="movie",
                server_link="https://server/items/movie",
                library_id="lib1",
            )
        )
        await session.commit()

    provider = Provider(
        [_server_item("movie", "Movie", folder_path=str(movie_dir))],
        app_config=app_config,
    )
    publisher = RecordingPublisher()
    reconciler = LibraryReconciler(
        publisher=publisher,
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=NoopDownloads(),
        app_config=app_config,
        database=database,
    )
    pages = provider.iter_items(["lib1"])
    server_items = [item async for page in pages for item in page]
    stats = await sync_full(reconciler, server_items, library_ids=["lib1"])

    assert stats.tally.errors == 0
    upserts: list[dict[str, Any]] = [
        payload
        for event, payload in events
        if event == "library.item.upserted" and isinstance(payload, dict)
    ]
    assert len(upserts) == 1
    raw_item = upserts[0]["item"]
    assert isinstance(raw_item, dict)
    item_payload = cast("dict[str, Any]", raw_item)
    # Local files without a recorded link or video are only partly complete.
    assert item_payload["art_status"] == "partial"
    assert item_payload["theme_status"] == "partial"
    assert item_payload["poster_hash"]
    original_hash = item_payload["theme_file_hash"]
    assert original_hash

    # Replacing only the theme must publish its new hash, even when presence
    # and saved provenance have not changed.
    events.clear()
    (movie_dir / "theme.mp3").write_bytes(b"replacement theme audio")
    stats = await sync_full(reconciler, server_items, library_ids=["lib1"])
    assert stats.tally.errors == 0
    replacements = [
        payload for event, payload in events if event == "library.item.upserted"
    ]
    assert len(replacements) == 1
    replacement = cast("dict[str, Any]", replacements[0])
    assert replacement["item"]["theme_file_hash"] != original_hash

    events.clear()
    await sync_full(reconciler, server_items, library_ids=["lib1"])
    assert not [event for event, _ in events if event == "library.item.upserted"]

    # A different folder can contain a different file with identical stat data.
    moved_dir = tmp_path / "Moved"
    moved_dir.mkdir()
    old_stat = (movie_dir / "theme.mp3").stat()
    moved_theme = moved_dir / "theme.mp3"
    moved_theme.write_bytes(b"REPLACEMENT THEME AUDIO")
    os.utime(moved_theme, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    moved_server_item = _server_item("movie", "Movie", folder_path=str(moved_dir))
    moved_server_item.guids = {"tmdb": "123"}
    await sync_full(
        reconciler,
        [moved_server_item],
        library_ids=["lib1"],
    )
    async with database.read_session() as session:
        moved_item = await session.get(MediaItem, 10)
        assert moved_item is not None
        assert moved_item.theme_file_hash != replacement["item"]["theme_file_hash"]
