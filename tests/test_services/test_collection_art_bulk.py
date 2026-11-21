"""Assets runs over collections: group scopes and collection art."""

lazy from collections import Counter
lazy from typing import override

lazy import pytest
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.ledger import read_asset
lazy from overture.db.models.catalog import CatalogCollection
lazy from overture.db.models.media_collection import MediaCollection
lazy from overture.db.session import Database
lazy from overture.domain import (
    ArtBulkSource,
    ArtType,
    CollectionPosterStyle,
    MediaType,
    ServerAsset,
)
lazy from overture.jobs.kinds import JobKind
lazy from overture.jobs.lifecycle import ManagedJobLifecycle
lazy from overture.jobs.progress_log import JobOutcome
lazy from overture.schemas.art import (
    ArtCandidate,
    ArtMatchResponse,
    SaveCollectionArtRequest,
)
lazy from overture.schemas.bulk import BulkMatchArtRequest, BulkThemeRequest
lazy from overture.schemas.common import Status, StatusResponse
lazy from overture.services.art.collection_art import CollectionArtService
lazy from overture.services.art.matcher import ArtMatcher, ImageComparison
lazy from overture.services.art.perfect_match import PERFECT_MATCH_MAX_DISTANCE
lazy from overture.services.asset_runs import run as asset_run
lazy from overture.services.asset_runs.plan import AssetPlan, plan_run
lazy from overture.utils.art_urls import PublicArtUrl
lazy from overture.utils.errors import PublicServiceError
lazy from overture.utils.time import utc_now
lazy from tests.bulk_helpers import (
    Context,
    disable_catalog,
    enable_catalog,
    make_bulk_downloads,
    progress_logs,
)
lazy from tests.collection_helpers import (
    managing_rule,
    shown_on_server,
    stored_collection,
)
lazy from tests.factories import seed_asset
lazy from tests.runtime_helpers import JobProbe, make_local_assets, unused

CATALOG_URL = "https://image.tmdb.org/t/p/original/catalog.jpg"


async def _seed(database: Database) -> None:
    async with database.write_session() as session:
        for collection_id, group in ((1, "Sagas"), (2, "Studios"), (3, None)):
            row = stored_collection(
                id=collection_id,
                server_item_id=f"server-{collection_id}",
                media_type=MediaType.MOVIE,
                library_id="1:movies",
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
        plan = await plan_run(params, database=database)
        return plan.total

    assert await planned(collection_groups=["Sagas"]) == 1
    assert await planned(collection_groups=["Sagas", "Studios"]) == 2
    # A chosen collection joins the chosen groups' collections.
    assert await planned(collection_groups=["Sagas"], collection_ids=[3]) == 2
    assert await planned(all_collections=True) == 3


async def test_collection_art_plans_posters_and_backgrounds_with_item_rules(
    *, app_config: Settings, database: Database
) -> None:
    await _seed(database)
    async with database.write_session() as session:
        row = await session.get(MediaCollection, 1)
        assert row is not None
        shown_on_server(row, background="https://plex.test/background.jpg")
        seed_asset(
            row,
            ServerAsset.POSTER,
            url="https://saved.test/poster.jpg",
            poster_style=CollectionPosterStyle.INDIVIDUAL,
            file_hash="hash",
            fingerprint="a" * 64,
            width=1000,
            height=1500,
        )
        row.tmdb_collection_id = 10
        session.add(row)

    plan = await plan_run(
        BulkMatchArtRequest(collection_ids=[1]),
        database=database,
    )

    # The saved poster is kept; the background is matched with the server's.
    assert plan.total == 2
    assert sum(plan.decided.values()) == 1
    assert [batch.visits for batch in plan.batches()] == [
        {1: ((ServerAsset.BACKGROUND, None),)}
    ]


async def test_slots_no_source_can_serve_are_decided_together_while_planning(
    db_session: AsyncSession, *, app_config: Settings, database: Database
) -> None:
    await _seed(database)
    await disable_catalog(db_session)

    plan = await plan_run(
        BulkMatchArtRequest(collection_groups=["Sagas"]),
        database=database,
    )

    # Without a TMDB collection or a server image, local matching has nothing
    # to compare, and OvertureDB is off: no slot is visited.
    assert list(plan.batches()) == []
    assert decided(plan) == {
        (
            JobOutcome.NO_MATCH,
            (
                "OvertureDB is disabled; "
                "Local art matching: the collection has no TMDB collection ID"
            ),
        ): 2
    }


class RecordingArt(CollectionArtService):
    def __init__(
        self,
        matches: list[ArtCandidate] | None = None,
        in_place: tuple[str, str | None] | None = None,
    ) -> None:
        self.art_in_place = in_place
        self.saved: list[
            tuple[int, ArtType, str | None, CollectionPosterStyle | None]
        ] = []
        self.adopted: list[tuple[int, ArtType, str]] = []
        self.matches = matches or []
        self.thresholds: list[int] = []

    @override
    async def match(
        self,
        collection_id: int,
        art_type: ArtType,
        threshold: int,
    ) -> ArtMatchResponse:
        self.thresholds.append(threshold)
        return ArtMatchResponse(
            matches=self.matches, total_compared=1, reference="media_server"
        )

    @override
    async def in_place(
        self, row: MediaCollection, art_type: ArtType
    ) -> tuple[str, str | None] | None:
        return self.art_in_place

    @override
    async def adopt(
        self,
        collection_id: int,
        art_type: ArtType,
        url: PublicArtUrl,
        poster_style: CollectionPosterStyle | None,
    ) -> None:
        self.adopted.append((collection_id, art_type, url))

    @override
    async def apply(
        self,
        collection_id: int,
        art_type: ArtType,
        body: SaveCollectionArtRequest,
    ) -> StatusResponse:
        self.saved.append((collection_id, art_type, body.url, body.poster_style))
        return StatusResponse(status=Status.OK)


def decided(plan: AssetPlan) -> dict[tuple[JobOutcome, str], int]:
    """Return what planning decided for collections, by outcome and reason."""
    return {
        (outcome, reason): count
        for (collection, outcome, reason), count in plan.decided.items()
        if collection
    }


async def _run(
    params: BulkMatchArtRequest,
    art: RecordingArt,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
    plan: AssetPlan | None = None,
    probe: JobProbe | None = None,
    matcher: ArtMatcher | None = None,
) -> Counter[JobOutcome]:
    """Run an Assets art job while the art lane's worker uploads what it queues."""
    if plan is not None:

        async def planned(*_args: object, **_kwargs: object) -> AssetPlan:
            return plan

        monkeypatch.setattr(asset_run, "plan_run", planned)
    probe = probe or JobProbe(lifecycle=ManagedJobLifecycle(JobKind.BULK_ART))
    downloads = make_bulk_downloads(
        app_config=app_config, database=database, collection_art=art
    )
    await downloads.start()
    try:
        await asset_run.run_art(
            probe.context,
            params,
            downloads=downloads,
            art_matcher=matcher or unused(ArtMatcher),
            art=art,
            local_assets=make_local_assets(app_config=app_config, database=database),
            app_config=app_config,
            database=database,
        )
    finally:
        await downloads.stop()
    return probe.context.counts.targets


async def test_collection_art_run_uploads_the_catalog_art_it_finds(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings, database: Database
) -> None:
    await _seed(database)
    async with database.write_session() as session:
        row = await session.get(MediaCollection, 1)
        assert row is not None
        row.tmdb_collection_id = 10
        session.add(row)
        session.add(
            CatalogCollection(
                tmdb_id=10, title="Saga", poster_url_individual=CATALOG_URL
            )
        )
        await enable_catalog(session)
    params = BulkMatchArtRequest(
        collection_groups=["Sagas"], source_order=[ArtBulkSource.OVERTUREDB]
    )
    plan = await plan_run(params, database=database)
    assert decided(plan) == {
        (JobOutcome.NO_MATCH, "OvertureDB has no background for it"): 1
    }
    art = RecordingArt()

    tally = await _run(
        params, art, monkeypatch, app_config=app_config, database=database
    )

    assert art.saved == [
        (1, ArtType.POSTER, CATALOG_URL, CollectionPosterStyle.INDIVIDUAL)
    ]
    assert tally[JobOutcome.DOWNLOADED] == 1
    async with database.read_session() as session:
        row = await session.get(MediaCollection, 1)
    assert row is not None
    assert row.last_matched_at is not None
    assert read_asset(row, ServerAsset.BACKGROUND).url is None


class Comparing(ArtMatcher):
    def __init__(self, compared: ImageComparison) -> None:
        self.compared = compared
        self.calls: list[tuple[str, str | None, str | None]] = []

    @override
    async def compare(
        self, url: str, *, fingerprint: str | None, content_hash: str | None
    ) -> ImageComparison:
        self.calls.append((url, fingerprint, content_hash))
        return self.compared


@pytest.mark.parametrize(
    ("compared", "adopted", "saved"),
    [
        (ImageComparison(distance=0, identical=True), 1, 0),
        (ImageComparison(distance=30, identical=False), 0, 0),
    ],
)
async def test_catalog_art_keeps_a_collections_image_in_place_as_a_titles_file(
    compared: ImageComparison,
    adopted: int,
    saved: int,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """Without Replace existing, catalog art differing from the image is declined."""
    await _seed(database)
    async with database.write_session() as session:
        row = await session.get(MediaCollection, 1)
        assert row is not None
        row.tmdb_collection_id = 10
        session.add(row)
        session.add(
            CatalogCollection(
                tmdb_id=10, title="Saga", poster_url_individual=CATALOG_URL
            )
        )
        await enable_catalog(session)
    params = BulkMatchArtRequest(
        collection_ids=[1],
        art_types=[ArtType.POSTER],
        source_order=[ArtBulkSource.OVERTUREDB],
    )
    art = RecordingArt(in_place=("f" * 64, "held"))
    matcher = Comparing(compared)

    await _run(
        params,
        art,
        monkeypatch,
        app_config=app_config,
        database=database,
        matcher=matcher,
    )

    assert matcher.calls == [(CATALOG_URL, "f" * 64, "held")]
    assert len(art.adopted) == adopted
    assert len(art.saved) == saved


async def test_local_matching_compares_the_server_image_overture_did_not_upload(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings, database: Database
) -> None:
    await _seed(database)
    async with database.write_session() as session:
        row = await session.get(MediaCollection, 1)
        assert row is not None
        row.tmdb_collection_id = 10
        shown_on_server(row, poster="https://plex.test/poster.jpg")
        session.add(row)
    params = BulkMatchArtRequest(
        collection_ids=[1],
        art_types=[ArtType.POSTER],
        source_order=[ArtBulkSource.LOCAL_ART_MATCHING],
    )
    # A preview can sit a step away from the original it is identical to.
    art = RecordingArt([ArtCandidate(url=CATALOG_URL, hamming=1, perfect_match=True)])

    tally = await _run(
        params, art, monkeypatch, app_config=app_config, database=database
    )
    assert art.thresholds == [PERFECT_MATCH_MAX_DISTANCE]
    assert art.adopted == [(1, ArtType.POSTER, CATALOG_URL)]
    assert tally[JobOutcome.ADOPTED] == 1


async def test_a_saved_collection_image_a_copy_lacks_is_sent_again(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings, database: Database
) -> None:
    await _seed(database)
    async with database.write_session() as session:
        row = await session.get(MediaCollection, 1)
        assert row is not None
        # The copy shows another image than the poster Overture chose.
        shown_on_server(row, poster="https://plex.test/other.jpg")
        seed_asset(
            row,
            ServerAsset.POSTER,
            url=CATALOG_URL,
            poster_style=CollectionPosterStyle.INDIVIDUAL,
        )
        session.add(row)
    art = RecordingArt()

    tally = await _run(
        BulkMatchArtRequest(
            collection_ids=[1],
            art_types=[ArtType.POSTER],
            source_order=[ArtBulkSource.OVERTUREDB],
        ),
        art,
        monkeypatch,
        app_config=app_config,
        database=database,
    )

    # Restored without asking a source, whatever the run's sources are.
    assert art.saved == [
        (1, ArtType.POSTER, CATALOG_URL, CollectionPosterStyle.INDIVIDUAL)
    ]
    assert tally[JobOutcome.QUEUED] == 1


async def test_collection_art_whose_upload_fails_is_an_error_of_the_run(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings, database: Database
) -> None:
    await _seed(database)
    async with database.write_session() as session:
        row = await session.get(MediaCollection, 1)
        assert row is not None
        row.tmdb_collection_id = 10
        session.add(row)
        session.add(
            CatalogCollection(
                tmdb_id=10, title="Saga", poster_url_individual=CATALOG_URL
            )
        )
        await enable_catalog(session)

    class FailingArt(RecordingArt):
        @override
        async def apply(
            self,
            collection_id: int,
            art_type: ArtType,
            body: SaveCollectionArtRequest,
        ) -> StatusResponse:
            raise PublicServiceError(400, "Invalid aspect ratio for poster.")

    tally = await _run(
        BulkMatchArtRequest(
            collection_ids=[1],
            art_types=[ArtType.POSTER],
            source_order=[ArtBulkSource.OVERTUREDB],
        ),
        FailingArt(),
        monkeypatch,
        app_config=app_config,
        database=database,
    )

    assert (
        tally[JobOutcome.QUEUED],
        tally[JobOutcome.DOWNLOADED],
        tally[JobOutcome.ERROR],
    ) == (1, 0, 1)


async def test_a_run_names_collection_slots_and_skips_those_that_left(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings, database: Database
) -> None:
    await _seed(database)
    async with database.write_session() as session:
        for collection_id in (1, 2):
            row = await session.get(MediaCollection, collection_id)
            assert row is not None
            row.tmdb_collection_id = 10 + collection_id
            session.add(row)
            session.add(
                CatalogCollection(
                    tmdb_id=10 + collection_id,
                    title="Saga",
                    poster_url_individual=CATALOG_URL,
                )
            )
        await enable_catalog(session)
    params = BulkMatchArtRequest(
        collection_ids=[1, 2],
        art_types=[ArtType.POSTER],
        source_order=[ArtBulkSource.OVERTUREDB],
    )
    plan = await plan_run(params, database=database)
    async with database.write_session() as session:
        left = await session.get(MediaCollection, 2)
        await session.delete(left)
    probe = Context()

    tally = await _run(
        params,
        RecordingArt(),
        monkeypatch,
        app_config=app_config,
        database=database,
        plan=plan,
        probe=probe,
    )

    assert progress_logs(probe) == [
        "Skipped 1 collection asset - no longer in the library",
        "Queued Collection 1 (collection poster) - OvertureDB artwork",
        "Downloaded Collection 1 (collection poster) - uploaded to the media server",
    ]
    assert (tally[JobOutcome.SKIPPED], tally[JobOutcome.ERROR]) == (1, 0)
