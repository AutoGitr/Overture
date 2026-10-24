"""Mirroring media-server collections, their members and their TMDB match."""

lazy from pathlib import Path
lazy from typing import override

lazy import pytest
lazy from pydantic import SecretStr
lazy from sqlmodel import select

lazy from overture.config import Settings
lazy from overture.db.models.download_job import DownloadJob
lazy from overture.db.models.media_collection import (
    MediaCollection,
    MediaCollectionMember,
)
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.public_dataset import PublicDatasetCollection
lazy from overture.db.session import Database
lazy from overture.domain import (
    IncrementalThemeOrder,
    MediaType,
    ServerType,
)
lazy from overture.integrations.tmdb import TMDBClient, TmdbDetails
lazy from overture.jobs.runner import ManagedJob, run_managed_job
lazy from overture.jobs.tally import SyncTally
lazy from overture.media_servers.adapters import ServerCollection, UploadThemes
lazy from overture.media_servers.jellyfin import JellyfinProvider
lazy from overture.services.collections.theme_files import (
    collection_folder,
    inspect_theme_file,
)
lazy from overture.services.sync.collection_sync import CollectionSync
lazy from overture.services.sync.tmdb_collections import TmdbCollectionEnrichment
lazy from overture.utils.time import utc_now
lazy from tests.bulk_helpers import enable_public_dataset, make_bulk_downloads
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import JobProbe, NoopProviderRegistry, unused


def test_collection_folders_resolve_by_name_inside_the_root(tmp_path: Path) -> None:
    (tmp_path / "Saga [boxset]").mkdir()
    (tmp_path / "Saga [boxset]" / "theme.mp3").write_bytes(b"mp3")
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "escape").symlink_to(outside)

    folder = collection_folder(tmp_path, "/jellyfin/data/collections/Saga [boxset]")

    assert folder == (tmp_path / "Saga [boxset]").resolve()
    assert inspect_theme_file(folder) is not None
    assert inspect_theme_file(tmp_path) is None
    for path in ("/x/..", "/x/missing", "/x/escape", ""):
        with pytest.raises(ValueError, match=r"collection|folder"):
            collection_folder(tmp_path, path)


class Server:
    """A Plex-like server listing fixed collections."""

    server_type = ServerType.PLEX
    collections = UploadThemes()

    def __init__(self, *collections: ServerCollection) -> None:
        self.listed = list(collections)

    async def list_collections(self) -> list[ServerCollection]:
        return self.listed


class NoTmdb(TmdbCollectionEnrichment):
    def __init__(self) -> None:
        pass

    @override
    async def run(
        self, job: ManagedJob[SyncTally], *, library_ids: list[str] | None = None
    ) -> int:
        return 0


def _collection(
    server_id: str,
    *members: str,
    media_type: MediaType | None = MediaType.MOVIE,
    library_id: str | None = "1",
    theme_id: str | None = None,
    tmdb_id: int | None = None,
    path: str | None = None,
) -> ServerCollection:
    return ServerCollection(
        id=server_id,
        title=f"Collection {server_id}",
        member_ids=members,
        server_link=f"https://server.test/{server_id}",
        media_type=media_type,
        library_id=library_id,
        theme_id=theme_id,
        tmdb_id=tmdb_id,
        path=path,
    )


async def _seed_movies(database: Database) -> dict[str, int]:
    async with database.write_session() as session:
        movies = [
            MediaItem(
                media_type=MediaType.MOVIE,
                title=f"Movie {n}",
                server_item_id=f"m{n}",
                library_id="1" if n < 3 else "2",
                tmdb_collection_id=10 if n < 2 else None,
            )
            for n in range(4)
        ]
        session.add_all(movies)
    return {movie.server_item_id or "": movie.id or 0 for movie in movies}


async def _run(
    server: object,
    database: Database,
    app_config: Settings,
    *,
    library_ids: list[str] | None = None,
    theme_order: IncrementalThemeOrder = IncrementalThemeOrder.OFF,
) -> None:
    sync = CollectionSync(
        provider_registry=NoopProviderRegistry(server),
        enrichment=NoTmdb(),
        downloads=make_bulk_downloads(
            app_config=app_config, database=database, provider=server
        ),
        publisher=NullEventPublisher(),
        app_config=app_config,
        database=database,
    )
    async with run_managed_job(JobProbe().context, SyncTally()) as job:
        await sync.run(job, library_ids=library_ids, theme_order=theme_order)


async def _rows(database: Database) -> dict[str, MediaCollection]:
    async with database.read_session() as session:
        rows = (await session.exec(select(MediaCollection))).all()
    return {row.server_item_id: row for row in rows}


async def test_sync_stores_collections_with_members_and_their_tmdb_match(
    *, app_config: Settings, database: Database
) -> None:
    ids = await _seed_movies(database)
    server = Server(
        _collection("saga", "m0", "m1", "m2", "unknown", theme_id="/theme/1"),
        _collection("mixed", "m0", "m2"),
    )

    await _run(server, database, app_config)

    rows = await _rows(database)
    assert rows["saga"].tmdb_collection_id is None
    assert rows["saga"].child_count == 4
    assert rows["saga"].server_theme_id == "/theme/1"
    assert rows["saga"].last_synced_at is not None
    assert rows["mixed"].tmdb_collection_id is None
    async with database.read_session() as session:
        members = (
            await session.exec(
                select(MediaCollectionMember.media_item_id).where(
                    MediaCollectionMember.collection_id == rows["saga"].id
                )
            )
        ).all()
    assert sorted(members) == sorted([ids["m0"], ids["m1"], ids["m2"]])


async def test_sync_keeps_choices_but_drops_provenance_for_replaced_themes(
    *, app_config: Settings, database: Database
) -> None:
    await _seed_movies(database)
    async with database.write_session() as session:
        session.add_all(
            [
                MediaCollection(
                    server_item_id="saga",
                    media_type=MediaType.MOVIE,
                    server_type=ServerType.PLEX,
                    youtube_id="abcDEF12345",
                    server_theme_id="/theme/old",
                    monitored=False,
                    tmdb_collection_id=99,
                ),
                MediaCollection(
                    server_item_id="kept",
                    media_type=MediaType.MOVIE,
                    server_type=ServerType.PLEX,
                    youtube_id="abcDEF12345",
                    server_theme_id="/theme/kept",
                ),
                MediaCollection(
                    server_item_id="gone",
                    media_type=MediaType.MOVIE,
                    server_type=ServerType.PLEX,
                    last_synced_at=utc_now(),
                ),
            ]
        )

    await _run(
        Server(
            _collection("saga", "m0", "m1", theme_id="/theme/new"),
            _collection("kept", "m0", theme_id="/theme/kept"),
        ),
        database,
        app_config,
    )

    rows = await _rows(database)
    assert set(rows) == {"saga", "kept"}
    assert rows["saga"].monitored is False
    assert rows["saga"].youtube_id is None
    assert rows["saga"].server_theme_id == "/theme/new"
    # A manual match is the user's and outlives the members' majority.
    assert rows["saga"].tmdb_collection_id == 99
    assert rows["kept"].youtube_id == "abcDEF12345"


async def test_a_library_scoped_sync_leaves_other_libraries_collections(
    *, app_config: Settings, database: Database
) -> None:
    await _seed_movies(database)
    async with database.write_session() as session:
        session.add(
            MediaCollection(
                server_item_id="elsewhere",
                media_type=MediaType.MOVIE,
                server_type=ServerType.PLEX,
                library_id="2",
                last_synced_at=utc_now(),
            )
        )

    await _run(
        Server(_collection("here", "m0"), _collection("there", "m3", library_id="2")),
        database,
        app_config,
        library_ids=["1"],
    )

    assert set(await _rows(database)) == {"elsewhere", "here"}


async def test_jellyfin_collections_take_type_library_and_theme_from_disk(
    tmp_path: Path, *, app_config: Settings, database: Database
) -> None:
    await _seed_movies(database)
    folder = tmp_path / "Saga [boxset]"
    folder.mkdir()
    (folder / "theme.mp3").write_bytes(b"mp3")
    app_config.JELLYFIN_COLLECTIONS_PATH = tmp_path

    class Jellyfin(JellyfinProvider):
        @override
        async def list_collections(self) -> list[ServerCollection]:
            return [
                _collection(
                    "box",
                    "m0",
                    "m3",
                    "m2",
                    media_type=None,
                    library_id=None,
                    tmdb_id=77,
                    path="/config/data/collections/Saga [boxset]",
                )
            ]

    await _run(Jellyfin(app_config=app_config), database, app_config)

    row = (await _rows(database))["box"]
    assert (row.media_type, row.library_id) == (MediaType.MOVIE, "1")
    assert row.tmdb_collection_id == 77
    assert row.server_theme_id is None
    assert row.theme_file_hash is not None
    assert row.theme_file_size == 3


async def test_enrichment_asks_tmdb_once_per_tmdb_id(
    *, app_config: Settings, database: Database
) -> None:
    app_config.TMDB_API_KEY = SecretStr("key")
    asked: list[int] = []

    class Tmdb(TMDBClient):
        def __init__(self) -> None:
            pass

        @override
        async def get_details(
            self, media_type: MediaType, tmdb_id: int
        ) -> TmdbDetails | None:
            asked.append(tmdb_id)
            return TmdbDetails(
                media_type=media_type,
                tmdb_id=tmdb_id,
                title="Movie",
                year=None,
                tvdb_id=None,
                imdb_id=None,
                poster_url=None,
                background_url=None,
                seasons=(),
                collection_id=10 if tmdb_id == 1 else None,
            )

    async with database.write_session() as session:
        session.add_all(
            [
                MediaItem(media_type=MediaType.MOVIE, title="A", tmdb_id=1),
                MediaItem(media_type=MediaType.MOVIE, title="B", tmdb_id=2),
                MediaItem(
                    media_type=MediaType.MOVIE,
                    title="Checked",
                    tmdb_id=3,
                    tmdb_collection_checked_id=3,
                ),
                MediaItem(media_type=MediaType.SHOW, title="Show", tmdb_id=4),
            ]
        )
    enrichment = TmdbCollectionEnrichment(
        app_config=app_config, database=database, tmdb_client=Tmdb()
    )

    async with run_managed_job(JobProbe().context, SyncTally()) as job:
        assert await enrichment.run(job) == 2
        assert await enrichment.run(job) == 0

    assert sorted(asked) == [1, 2]
    async with database.read_session() as session:
        found = {
            item.title: item.tmdb_collection_id
            for item in (await session.exec(select(MediaItem))).all()
        }
    assert found == {"A": 10, "B": None, "Checked": None, "Show": None}


async def test_enrichment_does_nothing_without_a_tmdb_key(
    *, app_config: Settings, database: Database
) -> None:
    enrichment = TmdbCollectionEnrichment(
        app_config=app_config, database=database, tmdb_client=unused(TMDBClient)
    )
    async with run_managed_job(JobProbe().context, SyncTally()) as job:
        assert await enrichment.run(job) == 0


@pytest.mark.parametrize("library_ids", [None, ["2"]])
async def test_collection_discovery_includes_ungrouped_movies_in_the_sync_scope(
    library_ids: list[str] | None,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    app_config.TMDB_API_KEY = SecretStr("key")
    asked: list[int] = []

    class Tmdb(TMDBClient):
        def __init__(self) -> None:
            pass

        @override
        async def get_details(
            self, media_type: MediaType, tmdb_id: int
        ) -> TmdbDetails | None:
            asked.append(tmdb_id)
            return None

    async with database.write_session() as session:
        session.add_all(
            MediaItem(
                media_type=MediaType.MOVIE,
                title=f"Movie {n}",
                server_item_id=f"m{n}",
                library_id=str(n),
                tmdb_id=n,
            )
            for n in range(1, 4)
        )
    server = Server()
    probe = JobProbe()
    sync = CollectionSync(
        provider_registry=NoopProviderRegistry(server, collections=False),
        enrichment=TmdbCollectionEnrichment(
            app_config=app_config, database=database, tmdb_client=Tmdb()
        ),
        downloads=make_bulk_downloads(
            app_config=app_config, database=database, provider=server
        ),
        publisher=NullEventPublisher(),
        app_config=app_config,
        database=database,
    )
    async with run_managed_job(probe.context, SyncTally()) as job:
        await sync.run(job, library_ids=library_ids)

    assert sorted(asked) == ([2] if library_ids else [1, 2, 3])
    assert any(
        "checking TMDB memberships" in payload.get("log", {}).get("reason", "")
        for _, payload in probe.events
    )


@pytest.mark.parametrize("unavailable_mount", [None, "missing"])
async def test_an_unavailable_jellyfin_mount_preserves_theme_facts_and_provenance(
    tmp_path: Path,
    *,
    unavailable_mount: str | None,
    app_config: Settings,
    database: Database,
) -> None:
    await _seed_movies(database)
    async with database.write_session() as session:
        session.add(
            MediaCollection(
                server_item_id="box",
                server_type=ServerType.JELLYFIN,
                media_type=MediaType.MOVIE,
                youtube_id="JG5OsfOuEy0",
                theme_file_hash="known",
                theme_file_size=3,
                theme_file_mtime_ns=1234,
                last_synced_at=utc_now(),
            )
        )

    class Jellyfin(JellyfinProvider):
        @override
        async def list_collections(self) -> list[ServerCollection]:
            return [_collection("box", "m0", path="/config/collections/Saga [boxset]")]

    app_config.JELLYFIN_COLLECTIONS_PATH = (
        tmp_path / unavailable_mount if unavailable_mount else None
    )
    await _run(Jellyfin(app_config=app_config), database, app_config)
    row = (await _rows(database))["box"]
    assert (row.youtube_id, row.theme_file_hash, row.theme_file_size) == (
        "JG5OsfOuEy0",
        "known",
        3,
    )


async def test_a_listed_boxset_without_local_members_preserves_manual_matching(
    *, app_config: Settings, database: Database
) -> None:
    async with database.write_session() as session:
        session.add(
            MediaCollection(
                server_item_id="box",
                server_type=ServerType.JELLYFIN,
                media_type=MediaType.MOVIE,
                library_id="1",
                tmdb_collection_id=99,
                last_synced_at=utc_now(),
            )
        )

    class Jellyfin(JellyfinProvider):
        @override
        async def list_collections(self) -> list[ServerCollection]:
            return [
                _collection(
                    "box", "unknown", media_type=None, library_id=None, tmdb_id=10
                )
            ]

    await _run(Jellyfin(app_config=app_config), database, app_config, library_ids=["1"])
    row = (await _rows(database))["box"]
    assert row.tmdb_collection_id == 99
    assert row.child_count == 1


def test_boxset_marker_or_xml_is_required_and_theme_symlinks_cannot_escape(
    tmp_path: Path,
) -> None:
    plain = tmp_path / "Saga"
    plain.mkdir()
    with pytest.raises(ValueError, match="BoxSet marker"):
        collection_folder(tmp_path, "/data/Saga")
    (plain / "collection.xml").write_text("<Item />")
    assert collection_folder(tmp_path, "/data/Saga") == plain
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"audio")
    (plain / "theme.mp3").symlink_to(outside)
    with pytest.raises(ValueError, match="outside"):
        inspect_theme_file(plain)


async def test_a_new_explicit_identity_queues_incremental_catalog_themes(
    *, app_config: Settings, database: Database
) -> None:
    await _seed_movies(database)
    async with database.write_session() as session:
        session.add(
            PublicDatasetCollection(
                tmdb_id=10, title="Saga", youtube_id_overturedb="o" * 11
            )
        )
        await enable_public_dataset(session)
    await _run(
        Server(_collection("saga", "m0", "m1", "unknown", tmdb_id=10)),
        database,
        app_config,
        theme_order=IncrementalThemeOrder.OVERTUREDB_THEMERRDB,
    )
    async with database.read_session() as session:
        (job,) = (await session.exec(select(DownloadJob))).all()
        assert job.collection_id == (await _rows(database))["saga"].id
        assert job.target_url == "o" * 11
