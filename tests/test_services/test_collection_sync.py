"""Mirroring media-server collections, their members and their TMDB match."""

lazy from dataclasses import replace
lazy from datetime import timedelta
lazy from pathlib import Path
lazy from typing import Any, override

lazy import httpx2
lazy import pytest
lazy from pydantic import SecretStr
lazy from sqlmodel import select

lazy from overture.config import MediaServerConfig, Settings
lazy from overture.db.ledger import (
    Destination,
    delivery,
    read_asset,
)
lazy from overture.db.models.catalog import CatalogCollection
lazy from overture.db.models.download_job import DownloadJob
lazy from overture.db.models.media_collection import (
    CollectionLibrary,
    MediaCollection,
    MediaCollectionMember,
)
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.settings import get_app_settings
lazy from overture.db.session import Database
lazy from overture.domain import (
    ArtType,
    AssetStatus,
    CollectionKind,
    DeliveryChannel,
    IncrementalThemeOrder,
    MediaType,
    ServerAsset,
    ServerType,
    TermKind,
)
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.integrations.tmdb import TMDBClient, TmdbFacts
lazy from overture.jobs.kinds import JobKind
lazy from overture.jobs.lifecycle import ManagedJobLifecycle
lazy from overture.jobs.progress_log import JobOutcome
lazy from overture.jobs.runner import run_managed_job
lazy from overture.jobs.tally import JobTally
lazy from overture.media_servers.adapters import ServerCollection, UploadThemes
lazy from overture.media_servers.jellyfin import JellyfinProvider
lazy from overture.media_servers.registry import Provider
lazy from overture.repositories.collection_items import CollectionItemRepository
lazy from overture.repositories.collections import CollectionRepository
lazy from overture.repositories.terms import TermRepository
lazy from overture.services.art.phash import PHASH_HEX_LENGTH, PhashService
lazy from overture.services.art.uploads import ArtUploads
lazy from overture.services.collections.theme_files import (
    collection_folder,
    inspect_theme_file,
)
lazy from overture.services.server_copies import ServerCopies
lazy from overture.services.sync.collection_sync import (
    CollectionSync,
    ListedCopy,
    by_row,
)
lazy from overture.services.sync.tmdb_enrichment import REFRESH_AFTER, TmdbEnrichment
lazy from overture.utils.time import utc_now
lazy from tests.bulk_helpers import enable_catalog, make_bulk_downloads
lazy from tests.collection_helpers import copy_id, managing_rule, stored_collection
lazy from tests.factories import (
    seed_asset,
    seed_theme,
    server_ref,
    theme_of,
)
lazy from tests.media_servers import (
    TEST_SERVER,
    TEST_SERVER_ID,
    configure,
    served_item,
    server_of,
)
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import JobProbe, NoopProviderRegistry, unused

LIFECYCLE = ManagedJobLifecycle(JobKind.SYNC)


def _jellyfin(collections: Path) -> MediaServerConfig:
    """A Jellyfin server whose collections folder Overture sees at *collections*."""
    return TEST_SERVER.model_copy(
        update={
            "type": ServerType.JELLYFIN,
            "name": "Jellyfin",
            "collections_path": collections,
        }
    )


def test_collection_folders_resolve_by_name_inside_the_root(tmp_path: Path) -> None:
    (tmp_path / "Saga [boxset]").mkdir()
    (tmp_path / "Saga [boxset]" / "theme.mp3").write_bytes(b"mp3")
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "escape").symlink_to(outside)

    folder = collection_folder(
        _jellyfin(tmp_path), "/jellyfin/data/collections/Saga [boxset]"
    )

    assert folder == (tmp_path / "Saga [boxset]").resolve()
    assert inspect_theme_file(folder) is not None
    assert inspect_theme_file(tmp_path) is None
    for path in ("/x/..", "/x/missing", "/x/escape", ""):
        with pytest.raises(ValueError, match=r"collection|folder"):
            collection_folder(_jellyfin(tmp_path), path)


class Server:
    """A Plex-like server listing fixed collections."""

    server_type = ServerType.PLEX
    collections = UploadThemes()

    def __init__(self, *collections: ServerCollection) -> None:
        self.listed = list(collections)
        #: The fingerprint of the image at each URL; one missing is unreadable.
        self.images: dict[str, str] = {}

    async def list_collections(self) -> list[ServerCollection]:
        return self.listed


class ServedImages(ServerCopies):
    """Server copies whose images are read from fingerprints, not the network."""

    def __init__(self, images: dict[str, str], *, app_config: Settings) -> None:
        super().__init__(
            phash=PhashService(app_config=app_config),
            image_clients=unused(ProxyClientManager),
            uploads=unused(ArtUploads),
            config_dir=unused(Path),
        )
        self._images = images

    @override
    async def collection_image(
        self,
        provider: Provider,
        server_item_id: str,
        art_type: ArtType,
        server_url: str,
    ) -> str:
        if server_url not in self._images:
            raise httpx2.ConnectError("server unreachable")
        return self._images[server_url]


def _collection(
    server_id: str,
    *members: str,
    media_type: MediaType | None = MediaType.MOVIE,
    library_id: str | None = "1:1",
    theme_id: str | None = None,
    tmdb_id: int | None = None,
    path: str | None = None,
) -> ServerCollection:
    return ServerCollection(
        id=server_id,
        title=f"Collection {server_id}",
        member_ids=members,
        media_type=media_type,
        library_id=library_id,
        theme_id=theme_id,
        tmdb_id=tmdb_id,
        path=path,
    )


async def _seed_movies(database: Database) -> dict[str, int]:
    async with database.write_session() as session:
        movies = [
            served_item(
                media_type=MediaType.MOVIE,
                title=f"Movie {n}",
                server_item_id=f"m{n}",
                library_id="1:1" if n < 3 else "1:2",
                tmdb_collection_id=10 if n < 2 else None,
            )
            for n in range(4)
        ]
        session.add_all(movies)
    return {movie.copies[0].server_item_id: movie.id or 0 for movie in movies}


async def _run(
    server: object,
    database: Database,
    app_config: Settings,
    *,
    library_ids: list[str] | None = None,
    theme_order: IncrementalThemeOrder = IncrementalThemeOrder.OFF,
) -> None:
    registry = NoopProviderRegistry(server)
    sync = CollectionSync(
        downloads=make_bulk_downloads(
            app_config=app_config, database=database, provider=server
        ),
        publisher=NullEventPublisher(),
        database=database,
        checks=ServedImages(getattr(server, "images", {}), app_config=app_config),
    )
    async with run_managed_job(
        JobProbe(lifecycle=LIFECYCLE).context, JobTally()
    ) as job:
        await sync.run(
            job, registry.providers(), library_ids=library_ids, theme_order=theme_order
        )


async def _rows(database: Database) -> dict[str, MediaCollection]:
    async with database.read_session() as session:
        rows = (await session.exec(select(MediaCollection))).all()
    return {key: row for row in rows if (key := copy_id(row)) is not None}


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
    assert server_ref(rows["saga"], ServerAsset.THEME) == "/theme/1"
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


def _uploaded_theme(server_item_id: str, ref: str, **fields: Any) -> MediaCollection:
    """Return a collection whose theme Overture uploaded to its copy as *ref*."""
    return seed_theme(
        stored_collection(
            server_item_id=server_item_id, media_type=MediaType.MOVIE, **fields
        ),
        "abcDEF12345",
        destination=Destination(TEST_SERVER_ID, server_item_id, DeliveryChannel.UPLOAD),
        uploaded_as=ref,
    )


async def test_sync_keeps_theme_choices_and_takes_content_only_from_changed_copies(
    *, app_config: Settings, database: Database
) -> None:
    await _seed_movies(database)
    async with database.write_session() as session:
        session.add_all(
            [
                _uploaded_theme(
                    "saga", "/theme/saga", monitored=False, tmdb_collection_id=99
                ),
                _uploaded_theme("kept", "/theme/kept"),
                _uploaded_theme("unread", "/theme/unread"),
                stored_collection(
                    server_item_id="gone",
                    media_type=MediaType.MOVIE,
                    last_synced_at=utc_now(),
                ),
            ]
        )

    await _run(
        Server(
            _collection("saga", "m0", "m1"),
            _collection("kept", "m0", theme_id="/theme/kept"),
            # Overture holds no fingerprint to compare a renamed theme with.
            _collection("unread", "m2", theme_id="/theme/other"),
        ),
        database,
        app_config,
    )

    rows = await _rows(database)
    assert set(rows) == {"saga", "kept", "unread"}
    assert rows["saga"].monitored is False
    # A manual match is the user's and outlives the members' majority.
    assert rows["saga"].tmdb_collection_id == 99
    themes = {key: theme_of(row).youtube_id for key, row in rows.items()}
    assert themes == dict.fromkeys(rows, "abcDEF12345")
    assert {key: theme_of(row).status for key, row in rows.items()} == {
        "saga": AssetStatus.PARTIAL,
        "kept": AssetStatus.COMPLETE,
        "unread": AssetStatus.COMPLETE,
    }
    assert server_ref(rows["unread"], ServerAsset.THEME) == "/theme/unread"


async def test_a_library_scoped_sync_leaves_other_libraries_collections(
    *, app_config: Settings, database: Database
) -> None:
    await _seed_movies(database)
    async with database.write_session() as session:
        session.add(
            stored_collection(
                server_item_id="elsewhere",
                media_type=MediaType.MOVIE,
                library_id="1:2",
                last_synced_at=utc_now(),
            )
        )

    await _run(
        Server(_collection("here", "m0"), _collection("there", "m3", library_id="1:2")),
        database,
        app_config,
        library_ids=["1:1"],
    )

    assert set(await _rows(database)) == {"elsewhere", "here"}


async def test_jellyfin_collections_take_type_library_and_theme_from_disk(
    tmp_path: Path, *, app_config: Settings, database: Database
) -> None:
    await _seed_movies(database)
    folder = tmp_path / "Saga [boxset]"
    folder.mkdir()
    (folder / "theme.mp3").write_bytes(b"mp3")
    configure(app_config, collections_path=tmp_path)

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

    await _run(
        Jellyfin(
            server=server_of(app_config, ServerType.JELLYFIN),
            server_id=TEST_SERVER_ID,
            app_config=app_config,
        ),
        database,
        app_config,
    )

    row = (await _rows(database))["box"]
    # A BoxSet stands outside the libraries, so it spans those its members are in.
    assert (row.media_types, row.library_ids) == ([MediaType.MOVIE], ["1:1", "1:2"])
    assert row.tmdb_collection_id == 77
    assert server_ref(row, ServerAsset.THEME) is None
    found = delivery(
        theme_of(row), Destination(TEST_SERVER_ID, "box", DeliveryChannel.FILE)
    )
    assert found is not None
    assert (found.observed_hash is not None, found.file_size) == (True, 3)


def _facts(tmdb_id: int) -> TmdbFacts:
    return TmdbFacts(
        original_language="English",
        origin_countries=("United States of America",),
        rating=7.5,
        votes=1200,
        keywords=("christmas",),
        companies=("Studio",),
        networks=("HBO",) if tmdb_id == 4 else (),
        streaming=("Netflix",),
        status="Ended",
        last_aired="2020-05-01" if tmdb_id == 4 else None,
        collection_id=10 if tmdb_id == 1 else None,
        imdb_id=f"tt{tmdb_id:07d}",
        tvdb_id=None,
    )


async def test_enrichment_reads_new_rematched_and_old_titles_once(
    *, app_config: Settings, database: Database
) -> None:
    app_config.TMDB_READ_ACCESS_TOKEN = SecretStr("key")
    asked: list[int] = []

    class Tmdb(TMDBClient):
        def __init__(self) -> None:
            pass

        @override
        async def get_facts(
            self, media_type: MediaType, tmdb_id: int, region: str
        ) -> TmdbFacts | None:
            asked.append(tmdb_id)
            assert region == "US"
            return _facts(tmdb_id)

    now = utc_now()
    async with database.write_session() as session:
        session.add_all(
            [
                MediaItem(media_type=MediaType.MOVIE, title="A", tmdb_id=1),
                MediaItem(
                    media_type=MediaType.MOVIE, title="B", tmdb_id=2, imdb_id="tt9"
                ),
                MediaItem(
                    media_type=MediaType.MOVIE,
                    title="Checked",
                    tmdb_id=3,
                    tmdb_checked_id=3,
                    tmdb_checked_at=now,
                ),
                MediaItem(media_type=MediaType.SHOW, title="Show", tmdb_id=4),
                MediaItem(
                    media_type=MediaType.MOVIE,
                    title="Old",
                    tmdb_id=5,
                    tmdb_checked_id=5,
                    tmdb_checked_at=now - REFRESH_AFTER - timedelta(hours=1),
                ),
            ]
        )
    enrichment = TmdbEnrichment(
        app_config=app_config, database=database, tmdb_client=Tmdb()
    )

    async with run_managed_job(
        JobProbe(lifecycle=LIFECYCLE).context, JobTally()
    ) as job:
        assert await enrichment.run(job) == 4
        assert await enrichment.run(job) == 0

    assert sorted(asked) == [1, 2, 4, 5]
    async with database.read_session() as session:
        items = {
            item.title: item for item in (await session.exec(select(MediaItem))).all()
        }
        values = {
            title: await TermRepository(session).values_of(item.id or 0)
            for title, item in items.items()
        }
    assert items["A"].tmdb_collection_id == 10
    assert values["A"][TermKind.TMDB_KEYWORD] == ["christmas"]
    # TMDB completes the IDs a title lacks and never replaces the server's.
    assert items["A"].imdb_id == "tt0000001"
    assert items["B"].imdb_id == "tt9"
    assert TermKind.TMDB_KEYWORD not in values["Checked"]
    show = items["Show"]
    assert (
        values["Show"][TermKind.NETWORK],
        show.last_aired,
        values["Show"][TermKind.STREAMING],
    ) == (
        ["HBO"],
        "2020-05-01",
        ["Netflix"],
    )


async def test_enrichment_reports_titles_tmdb_could_not_read(
    *, app_config: Settings, database: Database
) -> None:
    app_config.TMDB_READ_ACCESS_TOKEN = SecretStr("key")

    class Tmdb(TMDBClient):
        def __init__(self) -> None:
            pass

        @override
        async def get_facts(
            self, media_type: MediaType, tmdb_id: int, region: str
        ) -> TmdbFacts | None:
            raise OSError("TMDB is down")

    async with database.write_session() as session:
        session.add(MediaItem(media_type=MediaType.MOVIE, title="A", tmdb_id=1))
    probe = JobProbe(lifecycle=LIFECYCLE)
    enrichment = TmdbEnrichment(
        app_config=app_config, database=database, tmdb_client=Tmdb()
    )
    async with run_managed_job(probe.context, JobTally()) as job:
        assert await enrichment.run(job) == 0

    [reason] = [
        entry["reason"]
        for _, payload in probe.events
        if (entry := payload.get("log"))
        and entry["target"] == "TMDB"
        and entry["outcome"] == JobOutcome.ERROR
    ]
    assert "could not read 1 of 1 titles" in reason
    assert "TMDB is down" in reason


async def test_enrichment_does_nothing_without_a_tmdb_key(
    *, app_config: Settings, database: Database
) -> None:
    enrichment = TmdbEnrichment(
        app_config=app_config, database=database, tmdb_client=unused(TMDBClient)
    )
    async with run_managed_job(
        JobProbe(lifecycle=LIFECYCLE).context, JobTally()
    ) as job:
        assert await enrichment.run(job) == 0


@pytest.mark.parametrize("library_ids", [None, ["1:2"]])
async def test_enrichment_reads_the_titles_in_the_sync_scope(
    library_ids: list[str] | None,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    app_config.TMDB_READ_ACCESS_TOKEN = SecretStr("key")
    asked: list[int] = []

    class Tmdb(TMDBClient):
        def __init__(self) -> None:
            pass

        @override
        async def get_facts(
            self, media_type: MediaType, tmdb_id: int, region: str
        ) -> TmdbFacts | None:
            asked.append(tmdb_id)
            return None

    async with database.write_session() as session:
        session.add_all(
            served_item(
                media_type=MediaType.MOVIE,
                title=f"Movie {n}",
                server_item_id=f"m{n}",
                library_id=f"1:{n}",
                tmdb_id=n,
            )
            for n in range(1, 4)
        )
    probe = JobProbe(lifecycle=LIFECYCLE)
    enrichment = TmdbEnrichment(
        app_config=app_config, database=database, tmdb_client=Tmdb()
    )
    async with run_managed_job(probe.context, JobTally()) as job:
        await enrichment.run(job, library_ids=library_ids)

    assert sorted(asked) == ([2] if library_ids else [1, 2, 3])
    assert any(
        "reading details" in payload.get("log", {}).get("reason", "")
        for _, payload in probe.events
    )


async def test_an_unavailable_jellyfin_mount_preserves_theme_facts_and_provenance(
    tmp_path: Path,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    await _seed_movies(database)
    async with database.write_session() as session:
        session.add(
            seed_theme(
                stored_collection(
                    server_item_id="box",
                    media_type=MediaType.MOVIE,
                    last_synced_at=utc_now(),
                ),
                "JG5OsfOuEy0",
                file_hash="known",
                file_size=3,
                file_mtime_ns=1234,
                destination=Destination(TEST_SERVER_ID, "box", DeliveryChannel.FILE),
            )
        )

    class Jellyfin(JellyfinProvider):
        @override
        async def list_collections(self) -> list[ServerCollection]:
            return [_collection("box", "m0", path="/config/collections/Saga [boxset]")]

    configure(
        app_config,
        collections_path=tmp_path / "missing",
    )
    await _run(
        Jellyfin(
            server=server_of(app_config, ServerType.JELLYFIN),
            server_id=TEST_SERVER_ID,
            app_config=app_config,
        ),
        database,
        app_config,
    )
    row = (await _rows(database))["box"]
    delivered = delivery(
        theme_of(row), Destination(TEST_SERVER_ID, "box", DeliveryChannel.FILE)
    )
    assert delivered is not None
    assert (theme_of(row).youtube_id, delivered.observed_hash, delivered.file_size) == (
        "JG5OsfOuEy0",
        "known",
        3,
    )


async def test_a_listed_boxset_without_local_members_preserves_manual_matching(
    *, app_config: Settings, database: Database
) -> None:
    async with database.write_session() as session:
        session.add(
            stored_collection(
                server_item_id="box",
                media_type=MediaType.MOVIE,
                library_id="1:1",
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

    await _run(
        Jellyfin(
            server=server_of(app_config, ServerType.JELLYFIN),
            server_id=TEST_SERVER_ID,
            app_config=app_config,
        ),
        database,
        app_config,
        library_ids=["1:1"],
    )
    row = (await _rows(database))["box"]
    assert row.tmdb_collection_id == 99
    assert row.child_count == 1


def test_boxset_marker_or_xml_is_required_and_theme_symlinks_cannot_escape(
    tmp_path: Path,
) -> None:
    plain = tmp_path / "Saga"
    plain.mkdir()
    with pytest.raises(ValueError, match="BoxSet marker"):
        collection_folder(_jellyfin(tmp_path), "/data/Saga")
    (plain / "collection.xml").write_text("<Item />")
    assert collection_folder(_jellyfin(tmp_path), "/data/Saga") == plain
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"audio")
    (plain / "theme.mp3").symlink_to(outside)
    with pytest.raises(ValueError, match="outside"):
        inspect_theme_file(plain)


async def test_a_newly_imported_collection_waits_for_adoption_before_themes(
    *, app_config: Settings, database: Database
) -> None:
    await _seed_movies(database)
    async with database.write_session() as session:
        session.add(
            CatalogCollection(tmdb_id=10, title="Saga", youtube_id_overturedb="o" * 11)
        )
        await enable_catalog(session)
    await _run(
        Server(_collection("saga", "m0", "m1", "unknown", tmdb_id=10)),
        database,
        app_config,
        theme_order=IncrementalThemeOrder.OVERTUREDB_THEMERRDB,
    )
    # Imported collections are unmanaged, so incremental themes leave them alone.
    async with database.read_session() as session:
        assert (await session.exec(select(DownloadJob))).all() == []
    assert (await _rows(database))["saga"].tmdb_collection_id == 10


async def test_disabling_unmanaged_import_skips_new_collections_and_refreshes_existing(
    *, app_config: Settings, database: Database
) -> None:
    await _seed_movies(database)
    await _run(Server(_collection("existing", "m0")), database, app_config)
    async with database.write_session() as session:
        settings = await get_app_settings(session)
        settings.collection_import_unmanaged = False
        session.add(settings)
    await _run(
        Server(_collection("existing", "m0", "m1"), _collection("new", "m2")),
        database,
        app_config,
    )
    rows = await _rows(database)
    assert set(rows) == {"existing"}
    assert rows["existing"].child_count == 2


async def test_imported_literal_expressions_follow_server_metadata(
    *, app_config: Settings, database: Database
) -> None:
    await _seed_movies(database)
    server = Server(
        ServerCollection(
            id="literal",
            title="Literal",
            member_ids=("m0",),
            summary="An {overview}",
            sort_title="01_{literal}",
        )
    )
    await _run(server, database, app_config)
    imported = (await _rows(database))["literal"]
    assert imported.summary_format == "An {{overview}}"
    assert imported.sort_title_format == "01_{{literal}}"
    server.listed = [replace(server.listed[0], summary="Changed {overview}")]
    await _run(server, database, app_config)
    refreshed = (await _rows(database))["literal"]
    assert refreshed.summary == "Changed {overview}"
    assert refreshed.summary_source == "Changed {overview}"
    assert refreshed.summary_format == "Changed {{overview}}"


async def test_unsynced_choices_and_members_survive_a_library_sync(
    *, app_config: Settings, database: Database
) -> None:
    movies = await _seed_movies(database)
    server = Server(_collection("saga", "m0", "m1"))
    await _run(server, database, app_config)
    async with database.write_session() as session:
        row = (await _rows(database))["saga"]
        row.title = "Renamed"
        row.unsynced = True
        session.add(row)
        await CollectionRepository(session).replace_members(row.id or 0, [movies["m2"]])
    server.listed = [replace(server.listed[0], thumb_url="https://server.test/new")]
    await _run(server, database, app_config)
    refreshed = (await _rows(database))["saga"]
    assert (refreshed.title, server_ref(refreshed, ServerAsset.POSTER)) == (
        "Renamed",
        "https://server.test/new",
    )
    async with database.read_session() as session:
        members = await CollectionItemRepository(session).members(refreshed.id or 0)
    assert [member.id for member in members] == [movies["m2"]]


UPLOADED = "0" * PHASH_HEX_LENGTH
OTHER = "f" * PHASH_HEX_LENGTH


async def _uploaded_poster(
    server: Server, database: Database, app_config: Settings
) -> None:
    """Sync the server's "saga", then record the poster Overture uploaded to it."""
    await _seed_movies(database)
    server.listed = [replace(server.listed[0], thumb_url="https://server.test/1")]
    server.images["https://server.test/1"] = UPLOADED
    await _run(server, database, app_config)
    async with database.write_session() as session:
        row = (await _rows(database))["saga"]
        seed_asset(
            row,
            ServerAsset.POSTER,
            upload_hash="a" * 64,
            file_hash="a" * 64,
            fingerprint=UPLOADED,
        )
        session.add(row)


async def _poster_after_sync(
    server: Server, database: Database, app_config: Settings, url: str | None
) -> AssetStatus:
    """Sync with the copy showing *url*, and return the poster's status."""
    server.listed = [replace(server.listed[0], thumb_url=url)]
    await _run(server, database, app_config)
    return read_asset((await _rows(database))["saga"], ServerAsset.POSTER).status


async def test_an_upload_survives_syncs_while_the_server_still_shows_it(
    *, app_config: Settings, database: Database
) -> None:
    """Plex's image URL carries the last edit, so a URL alone proves nothing."""
    server = Server(_collection("saga", "m0"))
    await _uploaded_poster(server, database, app_config)

    for url in ("https://server.test/1", "https://server.test/edited"):
        server.images[url] = UPLOADED
        status = await _poster_after_sync(server, database, app_config, url)
        assert status is AssetStatus.COMPLETE
    saga = (await _rows(database))["saga"]
    assert server_ref(saga, ServerAsset.POSTER) == "https://server.test/edited"

    unreadable = await _poster_after_sync(
        server, database, app_config, "https://server.test/unreadable"
    )
    assert unreadable is AssetStatus.COMPLETE


@pytest.mark.parametrize("url", ["https://server.test/other", None])
async def test_an_image_replaced_on_the_server_is_no_longer_the_one_overture_uploaded(
    url: str | None, *, app_config: Settings, database: Database
) -> None:
    server = Server(_collection("saga", "m0"))
    await _uploaded_poster(server, database, app_config)
    server.images["https://server.test/other"] = OTHER

    replaced = await _poster_after_sync(server, database, app_config, url)

    assert replaced is AssetStatus.PARTIAL


async def test_managed_collections_keep_overtures_choices_and_outlive_their_server_copy(
    *, app_config: Settings, database: Database
) -> None:
    """Overture's sync sends what it manages; only unmanaged ones mirror the server."""
    await _seed_movies(database)
    server = Server(_collection("saga", "m0", "m1"), _collection("loose", "m0"))
    await _run(server, database, app_config)
    async with database.write_session() as session:
        row = (await _rows(database))["saga"]
        row.title = "Saga"
        row.sort_title_format = "01_{title}"
        session.add(row)
        session.add(managing_rule(row.id or 0))
    server.listed = [
        replace(server.listed[0], title="Renamed on Plex", member_ids=("m0",)),
        server.listed[1],
    ]
    await _run(server, database, app_config)
    saga = (await _rows(database))["saga"]
    assert (saga.title, saga.sort_title_format, saga.child_count) == (
        "Saga",
        "01_{title}",
        1,
    )

    server.listed = []
    await _run(server, database, app_config)
    async with database.read_session() as session:
        repo = CollectionRepository(session)
        kept = await repo.get(saga.id or 0)
        assert kept is not None
        assert (copy_id(kept), kept.child_count) == (None, 0)
        assert await CollectionItemRepository(session).members(saga.id or 0) == []
        assert [row.title for row in await repo.list_all()] == ["Saga"]


async def test_a_library_sync_keeps_a_separator_a_separator(
    *, app_config: Settings, database: Database
) -> None:
    """Plex lists a separator as an empty collection; only Overture knows its role."""
    server = Server(_collection("sep"))
    await _run(server, database, app_config)
    async with database.write_session() as session:
        row = (await _rows(database))["sep"]
        row.kind = CollectionKind.SEPARATOR
        session.add(row)
        session.add(managing_rule(row.id or 0))

    await _run(server, database, app_config)

    assert (await _rows(database))["sep"].kind is CollectionKind.SEPARATOR


def test_the_copy_on_the_lead_server_leads_whatever_order_libraries_were_saved_in() -> (
    None
):
    row = stored_collection(id=1, title="Requests")
    plex = row.libraries[0]
    plex.server_item_id = "p1"
    jellyfin = CollectionLibrary(
        server_id=2,
        collection_id=1,
        library_id="2:movies",
        media_type=MediaType.MOVIE,
        server_item_id="j1",
    )
    # Its Jellyfin library was saved first.
    row.libraries = [jellyfin, plex]
    listed = [
        ListedCopy(2, ServerCollection(id="j1", title="Requests", member_ids=())),
        ListedCopy(1, ServerCollection(id="p1", title="Requests", member_ids=())),
    ]

    [(owner, copies)] = by_row(listed, [row], [1, 2])

    # Plex leads, so its copy says the collection's images, kind and theme.
    assert owner is row
    assert [copy.key for copy in copies] == [(1, "p1"), (2, "j1")]
