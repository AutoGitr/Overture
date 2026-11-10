"""What each operation asks of the database, however large the library is."""

lazy import inspect
lazy from collections.abc import Awaitable, Callable
lazy from dataclasses import dataclass
lazy from typing import Any

lazy import pytest
lazy from pydantic import SecretStr
lazy from sqlalchemy.ext.asyncio import AsyncEngine

lazy from overture.config import Settings
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.session import Database
lazy from overture.domain import (
    CollectionOrder,
    FilterField,
    FilterOperator,
    MediaType,
    TermKind,
)
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.media_servers.adapters import ServerItem
lazy from overture.repositories.libraries import LibraryRepository
lazy from overture.repositories.terms import TermRepository
lazy from overture.schemas.collections import (
    CollectionCreate,
    CollectionKindRequest,
    CollectionPreviewRequest,
    FieldCondition,
    FilterGroup,
    SourceCondition,
    TmdbItemSource,
)
lazy from overture.schemas.removal import AssetRemoval, RemovalTarget
lazy from overture.services.collections.service import CollectionsService
lazy from overture.services.removal import AssetRemover
lazy from overture.services.sync.reconciler import LibraryReconciler
lazy from overture.utils.time import utc_now
lazy from tests.collection_helpers import library_rule
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import (
    NoopDownloads,
    NoopProviderRegistry,
    make_local_assets,
    make_remover,
    unused,
)
lazy from tests.sync_helpers import sync_full
lazy from tests.test_services.test_collection_management import (
    Art,
    FakeArrClient,
    Lists,
    Provider,
    Tmdb,
    settings_row,
)
lazy from tests.test_services.test_collections_service import (
    FakeDownloads,
    FakePublisher,
)
lazy from tests.workload import WRITING, Workload, recording, table_scans

#: Titles the small library holds; the operation runs again at twice as many.
_TITLES = 100
#: The tables a request must never read from end to end to answer for a few rows.
_LARGE_TABLES = ("media_items", "media_item_terms", "terms")

_LEAD = FilterGroup(
    conditions=[
        FieldCondition(
            field=FilterField.ACTOR, operator=FilterOperator.IS, value="Lead"
        )
    ]
)


@dataclass(slots=True)
class Bed:
    service: CollectionsService
    remover: AssetRemover
    database: Database
    engine: AsyncEngine
    regular: int
    smart: int
    next_id: int = 1

    async def stock(self, count: int) -> None:
        """Add titles holding many values, of which the first three star Lead."""
        first = self.next_id
        self.next_id += count
        async with self.database.write_session() as session:
            session.add_all(
                MediaItem(
                    id=item_id,
                    media_type=MediaType.MOVIE,
                    title=f"Title {item_id}",
                    year=2000,
                    tmdb_id=item_id,
                    server_item_id=f"server-{item_id}",
                    library_id="movies",
                )
                for item_id in range(first, first + count)
            )
            await session.flush()
            await TermRepository(session).assign_many(
                {
                    item_id: {
                        TermKind.ACTOR: [
                            *(["Lead"] if item_id <= 3 else []),
                            *(f"Actor {item_id % 40 + n}" for n in range(12)),
                        ],
                        TermKind.GENRE: ["Drama", "Action"],
                        TermKind.LABEL: ["Kept"],
                    }
                    for item_id in range(first, first + count)
                }
            )


def _forbid_inside_writes(provider: Provider) -> None:
    """Make the fake server fail like the network guard fails a real request."""

    def guarded(call: Callable[..., Awaitable[object]]) -> Any:
        async def checked(*args: object, **kwargs: object) -> object:
            assert not WRITING.get(), f"{call.__name__} in a write transaction"
            return await call(*args, **kwargs)

        return checked

    for name, call in inspect.getmembers(provider, inspect.iscoroutinefunction):
        setattr(provider, name, guarded(call))


@pytest.fixture
def app_config(app_config: Settings) -> Settings:
    return app_config.model_copy(update={"TMDB_API_KEY": SecretStr("tmdb")})


@pytest.fixture
async def bed(
    database: Database, isolated_engine: AsyncEngine, app_config: Settings
) -> Bed:
    provider = Provider(app_config)
    async with database.write_session() as session:
        await LibraryRepository(session).record(
            await provider.get_sections(), utc_now()
        )
        await session.merge(settings_row())
    remover = make_remover(provider, app_config=app_config, database=database)
    service = CollectionsService(
        database=database,
        provider_registry=NoopProviderRegistry(provider),
        publisher=FakePublisher(),
        downloads=FakeDownloads(),
        proxy_clients=unused(ProxyClientManager),
        app_config=app_config,
        tmdb=Tmdb(),
        mdblist=Lists(),
        remover=remover,
        art=Art(),
        radarr=FakeArrClient(1, "4k"),
        sonarr=FakeArrClient(2, "anime"),
    )
    _forbid_inside_writes(provider)
    bench = Bed(service, remover, database, isolated_engine, 0, 0)
    await bench.stock(_TITLES)
    bench.regular = (
        await service.editor.create(
            CollectionCreate(title="Regular", rule=library_rule(criteria=_LEAD))
        )
    ).id
    labelled = FilterGroup(
        conditions=[SourceCondition(source=TmdbItemSource(tmdb_ids=[1, 2]))]
    )
    bench.smart = (
        await service.editor.create(
            CollectionCreate(
                title="Smart",
                rule=library_rule(
                    criteria=labelled,
                    smart=True,
                    order_type=CollectionOrder.TITLE_ASC,
                ),
            )
        )
    ).id
    return bench


type Operation = Callable[[Bed], Awaitable[object]]


async def _preview(bed: Bed) -> object:
    return await bed.service.discovery.preview(
        CollectionPreviewRequest(rule=library_rule(criteria=_LEAD))
    )


async def _actors(bed: Bed) -> object:
    return await bed.service.discovery.field_values(
        MediaType.MOVIE, "movies", FilterField.ACTOR
    )


async def _recommend(bed: Bed) -> object:
    return await bed.service.discovery.recommend(
        CollectionKindRequest(rule=library_rule(criteria=_LEAD))
    )


async def _removal_options(bed: Bed) -> object:
    return await bed.remover.options(RemovalTarget(asset="art", item_ids=[1, 2, 3]))


#: Each operation, and how many statements it may take at any library size.
OPERATIONS: dict[str, tuple[Operation, int]] = {
    "regular rule sync": (lambda bed: bed.service.rules.sync(bed.regular), 40),
    "smart rule sync": (lambda bed: bed.service.rules.sync(bed.smart), 40),
    "preview": (_preview, 10),
    "field values": (_actors, 3),
    "recommendation": (_recommend, 5),
    "collection detail": (lambda bed: bed.service.reader.get(bed.regular), 15),
    "collection list": (lambda bed: bed.service.reader.listed(), 15),
    "removal options": (_removal_options, 6),
    "collection theme removal": (
        lambda bed: bed.service.themes.remove(bed.regular, AssetRemoval()),
        12,
    ),
}


async def _measure(bed: Bed, operation: Operation) -> Workload:
    with recording(bed.engine) as workload:
        await operation(bed)
    return workload


@pytest.mark.parametrize("name", OPERATIONS)
async def test_cost_does_not_grow_with_the_library(bed: Bed, name: str) -> None:
    operation, statements = OPERATIONS[name]
    # The first run settles what a sync only does once.
    await operation(bed)

    small = await _measure(bed, operation)
    await bed.stock(_TITLES)
    large = await _measure(bed, operation)

    assert large.counts == small.counts
    assert len(large.statements) <= statements, large.statements
    assert not large.entities["MediaItem"], large.entities


@pytest.mark.parametrize("name", OPERATIONS)
async def test_no_operation_reads_a_large_table_end_to_end(bed: Bed, name: str) -> None:
    workload = await _measure(bed, OPERATIONS[name][0])

    assert not await table_scans(bed.engine, workload.selects, _LARGE_TABLES)


def _listing(count: int) -> list[ServerItem]:
    return [
        ServerItem(
            id=f"server-{index}",
            title=f"Title {index}",
            year=2000,
            guids={"tmdb": str(index)},
            media_type=MediaType.MOVIE,
            poster_url=None,
            background_url=None,
            library_id="movies",
            actors=tuple(f"Actor {index % 40 + n}" for n in range(30)),
            genres=("Drama", "Action"),
        )
        for index in range(1, count + 1)
    ]


async def test_resyncing_an_unchanged_title_costs_the_same_at_any_size(
    database: Database, isolated_engine: AsyncEngine, app_config: Settings
) -> None:
    reconciler = LibraryReconciler(
        publisher=NullEventPublisher(),
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=NoopDownloads(),
        app_config=app_config,
        database=database,
    )
    small, large = _listing(50), _listing(100)
    await sync_full(reconciler, large)

    with recording(isolated_engine) as few:
        await sync_full(reconciler, small, library_ids=["other"])
    with recording(isolated_engine) as many:
        await sync_full(reconciler, large)

    # One statement in either direction: batches round differently.
    per_title = len(few.statements) / len(small)
    assert len(many.statements) <= per_title * len(large) + 10
    assert many.entities["MediaItem"] <= 2 * len(large) + few.entities["MediaItem"]
    assert per_title <= 12, per_title
    assert many.largest_write <= few.largest_write + 1
