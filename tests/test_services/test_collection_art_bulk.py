"""Assets runs over collections: group scopes and collection art."""

lazy from typing import override

lazy from overture.config import Settings
lazy from overture.db.art_slots import (
    ArtFileFacts,
    read_art_slot,
    record_art_file,
    select_art,
)
lazy from overture.db.models.media_collection import MediaCollection
lazy from overture.db.models.public_dataset import PublicDatasetCollection
lazy from overture.db.session import Database
lazy from overture.domain import (
    ArtBulkSource,
    ArtType,
    MediaType,
    ServerType,
)
lazy from overture.jobs.kinds import JobKind
lazy from overture.jobs.lifecycle import ManagedJobLifecycle
lazy from overture.jobs.progress_log import JobOutcome
lazy from overture.jobs.runner import run_managed_job
lazy from overture.jobs.tally import BulkAssetTally
lazy from overture.schemas.art import ArtCandidate, ArtMatchResponse, SaveArtRequest
lazy from overture.schemas.bulk import BulkMatchArtRequest, BulkThemeRequest
lazy from overture.schemas.common import Status, StatusResponse
lazy from overture.services.art.collection_art import CollectionArtService
lazy from overture.services.art.collection_bulk import (
    plan_collection_art,
    run_collection_art,
)
lazy from overture.services.themes.collection_bulk import plan_collection_themes
lazy from overture.utils.art_urls import PublicArtUrl
lazy from overture.utils.time import utc_now
lazy from tests.bulk_helpers import enable_public_dataset
lazy from tests.collection_helpers import managing_rule, stored_collection
lazy from tests.runtime_helpers import JobProbe

CATALOG_URL = "https://image.tmdb.org/t/p/original/catalog.jpg"


async def _seed(database: Database) -> None:
    async with database.write_session() as session:
        for collection_id, group in ((1, "Sagas"), (2, "Studios"), (3, None)):
            row = stored_collection(
                id=collection_id,
                server_item_id=f"server-{collection_id}",
                server_type=ServerType.PLEX,
                media_type=MediaType.MOVIE,
                library_id="movies",
                title=f"Collection {collection_id}",
                group=group,
                last_synced_at=utc_now(),
            )
            session.add(row)
            await session.flush()
            session.add(managing_rule(collection_id))


async def test_group_scope_resolves_to_the_groups_collections(
    *, app_config: Settings, database: Database
) -> None:
    await _seed(database)

    async def planned(**scope: object) -> int:
        params = BulkThemeRequest.model_validate(scope)
        plan = await plan_collection_themes(
            params, app_config=app_config, database=database
        )
        return plan.total

    assert await planned(collection_groups=["Sagas"]) == 1
    assert await planned(collection_groups=["Sagas", "Studios"]) == 2
    assert await planned(all_collections=True) == 3


async def test_collection_art_plans_posters_and_backgrounds_with_item_rules(
    *, app_config: Settings, database: Database
) -> None:
    await _seed(database)
    async with database.write_session() as session:
        row = await session.get(MediaCollection, 1)
        assert row is not None
        select_art(row, ArtType.POSTER, PublicArtUrl("https://saved.test/poster.jpg"))
        record_art_file(
            row, ArtType.POSTER, ArtFileFacts("hash", "a" * 64, 1000, 1500, 1, 1)
        )
        row.tmdb_collection_id = 10
        row.art_url = "https://plex.test/background.jpg"
        session.add(row)

    plan = await plan_collection_art(
        BulkMatchArtRequest(collection_ids=[1]),
        app_config=app_config,
        database=database,
    )

    # The saved poster is kept; the background is matched with the server's.
    assert plan.total == 2
    assert sum(plan.decided.values()) == 1
    assert [dict(batch) for batch in plan.batches()] == [{1: (ArtType.BACKGROUND,)}]


async def test_slots_no_source_can_serve_are_decided_together_while_planning(
    *, app_config: Settings, database: Database
) -> None:
    await _seed(database)

    plan = await plan_collection_art(
        BulkMatchArtRequest(collection_groups=["Sagas"]),
        app_config=app_config,
        database=database,
    )

    # Without a TMDB collection or a server image, local matching has nothing
    # to compare, and OvertureDB is off: no slot is visited.
    assert list(plan.batches()) == []
    assert plan.decided == {
        (
            JobOutcome.NO_MATCH,
            (
                "OvertureDB is disabled; "
                "Local art matching: the collection has no TMDB collection ID"
            ),
        ): 2
    }


class RecordingArt(CollectionArtService):
    def __init__(self, matches: list[ArtCandidate] | None = None) -> None:
        self.saved: list[tuple[int, ArtType, str | None]] = []
        self.adopted: list[tuple[int, ArtType, str]] = []
        self.matches = matches or []

    @override
    async def match(
        self,
        collection_id: int,
        art_type: ArtType,
        threshold: int,
    ) -> ArtMatchResponse:
        return ArtMatchResponse(
            matches=self.matches, total_compared=1, reference="media_server"
        )

    @override
    async def adopt(self, collection_id: int, art_type: ArtType, url: str) -> bool:
        self.adopted.append((collection_id, art_type, url))
        return True

    @override
    async def save(
        self,
        collection_id: int,
        art_type: ArtType,
        body: SaveArtRequest,
    ) -> StatusResponse:
        self.saved.append((collection_id, art_type, body.url))
        return StatusResponse(status=Status.OK)


async def _run(
    params: BulkMatchArtRequest,
    art: RecordingArt,
    *,
    app_config: Settings,
    database: Database,
) -> BulkAssetTally:
    plan = await plan_collection_art(params, app_config=app_config, database=database)
    probe = JobProbe(lifecycle=ManagedJobLifecycle(JobKind.BULK_ART))
    async with run_managed_job(
        probe.context, BulkAssetTally(), database=database
    ) as job:
        await job.started()
        await job.planned(plan.total)
        await run_collection_art(
            job, params, plan, art=art, app_config=app_config, database=database
        )
        return job.tally


async def test_collection_art_run_uploads_the_catalog_art_it_finds(
    *, app_config: Settings, database: Database
) -> None:
    await _seed(database)
    async with database.write_session() as session:
        row = await session.get(MediaCollection, 1)
        assert row is not None
        row.tmdb_collection_id = 10
        session.add(row)
        session.add(
            PublicDatasetCollection(tmdb_id=10, title="Saga", poster_url=CATALOG_URL)
        )
        await enable_public_dataset(session)
    params = BulkMatchArtRequest(
        collection_groups=["Sagas"], source_order=[ArtBulkSource.OVERTUREDB]
    )
    plan = await plan_collection_art(params, app_config=app_config, database=database)
    assert plan.decided == {
        (JobOutcome.NO_MATCH, "OvertureDB has no background for it"): 1
    }
    art = RecordingArt()

    tally = await _run(params, art, app_config=app_config, database=database)

    assert art.saved == [(1, ArtType.POSTER, CATALOG_URL)]
    assert tally.downloaded == 1
    async with database.read_session() as session:
        row = await session.get(MediaCollection, 1)
    assert row is not None
    assert row.last_matched_at is not None
    assert read_art_slot(row, ArtType.BACKGROUND).url is None


async def test_local_matching_compares_the_server_image_overture_did_not_upload(
    *, app_config: Settings, database: Database
) -> None:
    await _seed(database)
    async with database.write_session() as session:
        row = await session.get(MediaCollection, 1)
        assert row is not None
        row.tmdb_collection_id = 10
        row.thumb_url = "https://plex.test/poster.jpg"
        session.add(row)
    params = BulkMatchArtRequest(
        collection_ids=[1],
        art_types=[ArtType.POSTER],
        source_order=[ArtBulkSource.LOCAL_ART_MATCHING],
    )
    art = RecordingArt([ArtCandidate(url=CATALOG_URL, hamming=0, perfect_match=True)])

    tally = await _run(params, art, app_config=app_config, database=database)
    assert art.adopted == [(1, ArtType.POSTER, CATALOG_URL)]
    assert tally.adopted == 1
