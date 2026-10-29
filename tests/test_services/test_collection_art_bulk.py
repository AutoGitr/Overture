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
lazy from overture.db.session import Database
lazy from overture.domain import (
    ArtBulkSource,
    ArtSource,
    ArtType,
    MediaType,
    ServerType,
)
lazy from overture.jobs.kinds import JobKind
lazy from overture.jobs.lifecycle import ManagedJobLifecycle
lazy from overture.jobs.runner import run_managed_job
lazy from overture.jobs.tally import BulkAssetTally
lazy from overture.schemas.art import ArtCandidate, ArtSourcesResponse, SaveArtRequest
lazy from overture.schemas.bulk import BulkMatchArtRequest, BulkThemeRequest
lazy from overture.schemas.common import Status, StatusResponse
lazy from overture.services.art.collection_bulk import (
    plan_collection_art,
    run_collection_art,
)
lazy from overture.services.art.matcher import ArtMatcher
lazy from overture.services.art.service import ArtService
lazy from overture.services.themes.collection_bulk import plan_collection_themes
lazy from overture.utils.time import utc_now
lazy from tests.collection_helpers import managing_rule
lazy from tests.runtime_helpers import JobProbe, unused

CATALOG_URL = "https://image.tmdb.org/t/p/original/catalog.jpg"


async def _seed(database: Database) -> None:
    async with database.write_session() as session:
        for collection_id, group in ((1, "Sagas"), (2, "Studios"), (3, None)):
            row = MediaCollection(
                id=collection_id,
                server_item_id=f"server-{collection_id}",
                server_type=ServerType.PLEX,
                media_type=MediaType.MOVIE,
                library_id="movies",
                title=f"Collection {collection_id}",
                collection_group=group,
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
    *, database: Database
) -> None:
    await _seed(database)
    async with database.write_session() as session:
        row = await session.get(MediaCollection, 1)
        assert row is not None
        select_art(row, ArtType.POSTER, "https://saved.test/poster.jpg")
        record_art_file(
            row, ArtType.POSTER, ArtFileFacts("hash", "a" * 64, 1000, 1500, 1, 1)
        )
        session.add(row)

    plan = await plan_collection_art(
        BulkMatchArtRequest(collection_ids=[1]), database=database
    )

    # The saved poster is kept; the background and nothing else is visited.
    assert plan.total == 2
    assert sum(plan.decided.values()) == 1
    assert [dict(batch) for batch in plan.batches()] == [{1: (ArtType.BACKGROUND,)}]


class RecordingArt(ArtService):
    def __init__(self) -> None:
        self.saved: list[tuple[int, ArtType, str]] = []

    @override
    async def get_collection_sources(
        self, collection_id: int, media_type: MediaType, art_type: ArtType
    ) -> ArtSourcesResponse:
        return ArtSourcesResponse(
            sources={ArtSource.OVERTUREDB: [ArtCandidate(url=CATALOG_URL)]}
            if art_type is ArtType.POSTER
            else {}
        )

    @override
    async def save_collection(
        self,
        collection_id: int,
        media_type: MediaType,
        art_type: ArtType,
        body: SaveArtRequest,
    ) -> StatusResponse:
        self.saved.append((collection_id, art_type, body.url))
        return StatusResponse(status=Status.OK)


async def test_collection_art_run_uploads_the_catalog_art_it_finds(
    *, database: Database
) -> None:
    await _seed(database)
    params = BulkMatchArtRequest(
        collection_groups=["Sagas"], source_order=[ArtBulkSource.OVERTUREDB]
    )
    plan = await plan_collection_art(params, database=database)
    art = RecordingArt()
    probe = JobProbe(lifecycle=ManagedJobLifecycle(JobKind.BULK_ART))
    async with run_managed_job(
        probe.context, BulkAssetTally(), database=database
    ) as job:
        await job.started()
        await job.planned(plan.total)
        await run_collection_art(
            job, params, plan, art=art, matcher=unused(ArtMatcher), database=database
        )
        tally = job.tally

    assert art.saved == [(1, ArtType.POSTER, CATALOG_URL)]
    assert (tally.downloaded, tally.no_match) == (1, 1)
    async with database.read_session() as session:
        row = await session.get(MediaCollection, 1)
    assert row is not None
    assert row.last_matched_at is not None
    assert read_art_slot(row, ArtType.BACKGROUND).url is None
