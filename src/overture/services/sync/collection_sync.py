"""Sync collections, their complete membership and their TMDB matches."""

lazy import logging
lazy from collections.abc import Mapping, Sequence
lazy from dataclasses import dataclass
lazy from datetime import datetime

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.ledger import (
    Destination,
    Evidence,
    FileFacts,
    delivery,
    file_facts,
    observe,
    read_asset,
    record_file,
)
lazy from ...db.models.media_collection import CollectionLibrary, MediaCollection
lazy from ...db.models.settings import get_app_settings
lazy from ...db.session import Database
lazy from ...domain import (
    AssetScope,
    CollectionKind,
    CollectionOrder,
    DeliveryChannel,
    IncrementalThemeOrder,
    MediaType,
    ScheduleKind,
    ServerAsset,
)
lazy from ...jobs.progress_log import JobOutcome
lazy from ...jobs.runner import ManagedJob
lazy from ...jobs.tally import JobTally
lazy from ...media_servers.adapters import FolderThemes, ServerCollection, UploadThemes
lazy from ...media_servers.registry import Provider, log_server
lazy from ...repositories.collections import CollectionRepository
lazy from ...repositories.copies import CopyRepository, ServerItemFacts
lazy from ...repositories.saved_schedules import SavedScheduleRepository
lazy from ...schemas.sync import SyncScheduleConfig
lazy from ...utils.collection_formats import literal_template
lazy from ...utils.threads import owned_thread
lazy from ...utils.time import utc_now
lazy from ..catalog.downloads import queue_catalog_themes_for_collections
lazy from ..collections import COLLECTIONS_LOCK
lazy from ..collections.copies import held_copies, lead_part
lazy from ..collections.destinations import place_collection
lazy from ..collections.theme_files import collection_folder, inspect_theme_file
lazy from ..downloads.service import DownloadService
lazy from ..needs import apply_needs
lazy from ..server_copies import ServerCopies

logger = logging.getLogger(__name__)


#: A server collection, by the database's number of its server and its own ID.
type CopyKey = tuple[int, str]


@dataclass(slots=True, frozen=True)
class ListedCopy:
    """One collection a server lists."""

    server_id: int
    collection: ServerCollection

    @property
    def key(self) -> CopyKey:
        return self.server_id, self.collection.id


@dataclass(slots=True, frozen=True)
class _Observation:
    """What a sync read of one copy's asset: its evidence, or a file it found."""

    kind: ServerAsset
    destination: Destination
    evidence: Evidence
    #: What the server names its current image or theme by.
    ref: str | None
    #: The theme file found in a server's collection folder, or ``None``.
    file: FileFacts | None = None


@dataclass(slots=True, frozen=True)
class _Placed:
    """A library a server collection holds members of."""

    library_id: str
    media_type: MediaType
    server_id: int
    server_item_id: str
    server_path: str | None


def by_row(
    listed: Sequence[ListedCopy],
    rows: Sequence[MediaCollection],
    server_order: Sequence[int],
) -> list[tuple[MediaCollection | None, list[ListedCopy]]]:
    """Group server collections by the row that owns them, lead copy first.

    A collection across libraries or servers has a copy in each Plex library
    and on each server, so a row's copies are stored together; one unknown to
    Overture stands alone. The lead copy is the one on the earliest server in
    *server_order*, as everywhere else.
    """
    owners = {
        (part.server_id, part.server_item_id): row
        for row in rows
        for part in row.libraries
        if part.server_item_id
    }
    grouped: dict[int, tuple[MediaCollection, list[ListedCopy]]] = {}
    alone: list[tuple[MediaCollection | None, list[ListedCopy]]] = []
    for copy in listed:
        owner = owners.get(copy.key)
        if owner is None:
            alone.append((None, [copy]))
        else:
            grouped.setdefault(owner.id or 0, (owner, []))[1].append(copy)
    for row, copies in grouped.values():
        order = [
            (part.server_id, part.server_item_id)
            for part in held_copies(row, server_order)
        ]
        copies.sort(
            key=lambda copy: order.index(copy.key) if copy.key in order else len(order)
        )
    return [*grouped.values(), *alone]


def _placement(
    copies: Sequence[ListedCopy],
    items: Mapping[CopyKey, ServerItemFacts],
    previous: MediaCollection | None,
) -> list[_Placed]:
    """The libraries these server collections hold members of.

    Plex names a collection's library; Jellyfin and Emby keep collections
    outside theirs, so its members say, and an emptied one stays where it was.
    """
    placed: dict[str, _Placed] = {}
    for listed in copies:
        copy = listed.collection
        if copy.library_id is not None and copy.media_type is not None:
            placed[copy.library_id] = _Placed(
                copy.library_id, copy.media_type, listed.server_id, copy.id, copy.path
            )
            continue
        for identity in copy.member_ids:
            if (item := items.get((listed.server_id, identity))) is not None:
                placed.setdefault(
                    item.library_id,
                    _Placed(
                        item.library_id,
                        item.media_type,
                        listed.server_id,
                        copy.id,
                        copy.path,
                    ),
                )
    if placed or previous is None:
        return list(placed.values())
    return [
        _Placed(
            part.library_id,
            part.media_type,
            part.server_id,
            part.server_item_id,
            part.server_path,
        )
        for part in previous.libraries
        if part.server_item_id is not None
    ]


def _store_placement(row: MediaCollection, placement: Sequence[_Placed]) -> None:
    """Make these the libraries of a collection Overture does not manage."""
    parts = {part.library_id: part for part in row.libraries}
    row.libraries = [
        parts.get(placed.library_id)
        or CollectionLibrary(
            collection_id=row.id or 0,
            library_id=placed.library_id,
            media_type=placed.media_type,
            server_id=placed.server_id,
        )
        for placed in placement
    ]
    for part, placed in zip(row.libraries, placement, strict=True):
        part.server_item_id = placed.server_item_id
        part.server_path = placed.server_path


def _store_paths(row: MediaCollection, placement: Sequence[_Placed]) -> None:
    """Note where each server keeps the copies of a collection Overture manages."""
    paths = {
        (placed.server_id, placed.server_item_id): placed.server_path
        for placed in placement
    }
    for part in row.libraries:
        if (key := (part.server_id, part.server_item_id or "")) in paths:
            part.server_path = paths[key]


class CollectionSync:
    """Mirror collections while preserving manual choices and inaccessible files."""

    def __init__(
        self,
        *,
        publisher: protocols.EventPublisher,
        app_config: Settings,
        database: Database,
        downloads: DownloadService,
        checks: ServerCopies,
    ) -> None:
        self._publisher = publisher
        self._config = app_config
        self._database = database
        self._downloads = downloads
        self._checks = checks

    async def run(
        self,
        job: ManagedJob[JobTally],
        providers: Sequence[Provider],
        *,
        library_ids: list[str] | None,
        theme_order: IncrementalThemeOrder = IncrementalThemeOrder.OFF,
    ) -> None:
        """Refresh what *providers*' servers hold, then queue catalog themes.

        Only those servers' copies are read; another server's copies stay as
        the last sync of it left them.
        """
        providers = [provider for provider in providers if provider.collections]
        if job.stop_requested() or not providers:
            return
        async with self._downloads.asset_locks.acquire(COLLECTIONS_LOCK):
            listed: list[ListedCopy] = []
            for provider in providers:
                await job.report(
                    JobOutcome.STARTED,
                    "Collections",
                    f"reading collections from {provider.server.title}",
                    server=log_server(provider),
                    finished=False,
                )
                listed += [
                    ListedCopy(provider.server_id, collection)
                    for collection in await provider.list_collections()
                ]
            by_server = {provider.server_id: provider for provider in providers}
            async with self._database.read_session() as session:
                import_unmanaged = (
                    await get_app_settings(session)
                ).collection_import_unmanaged
                items = {
                    (provider.server_id, identity): facts
                    for provider in providers
                    for identity, facts in (
                        await CopyRepository(session).facts_by_server_id(
                            provider.server_id
                        )
                    ).items()
                }
                rows = await CollectionRepository(session).list_all()
                managed_ids = {
                    row.id
                    for row in rows
                    if row.rule is not None and row.id is not None
                }
            # Titles of managed collections still without a copy on a server,
            # which take over that server's collection of their title when
            # they sync.
            awaited = {
                (part.server_id, row.title.casefold())
                for row in rows
                if row.rule is not None
                for part in row.libraries
                if part.server_item_id is None
            }
            seen = {copy.key for copy in listed}
            newly_identified: list[int] = []
            identified = 0
            server_order = self._downloads.provider_registry.server_ids()
            for previous, copies in by_row(listed, rows, server_order):
                if job.stop_requested():
                    return
                lead = copies[0]
                # The lead copy's images, kind and theme stand for the
                # collection; a sync without the lead's server leaves them.
                leads = previous is None or (
                    (part := lead_part(previous, server_order)) is not None
                    and (part.server_id, part.server_item_id) == lead.key
                )
                if (
                    previous is None
                    and not import_unmanaged
                    and (lead.server_id, lead.collection.title.casefold())
                    not in awaited
                ):
                    continue
                members = list(
                    {
                        facts.id: facts
                        for copy in copies
                        for identity in copy.collection.member_ids
                        if (facts := items.get((copy.server_id, identity)))
                    }.values()
                )
                # Items no sync stored yet still count, as their server's own.
                unknown = {
                    (copy.server_id, identity)
                    for copy in copies
                    for identity in copy.collection.member_ids
                    if (copy.server_id, identity) not in items
                }
                placement = _placement(copies, items, previous)
                # An empty BoxSet is in no library yet, so there is nothing to list.
                if not placement:
                    continue
                if library_ids and not {p.library_id for p in placement} & set(
                    library_ids
                ):
                    continue
                async with self._downloads.asset_locks.acquire(
                    f"collection:{previous.id}"
                    if previous
                    else f"new-collection:{lead.server_id}:{lead.collection.id}"
                ):
                    async with self._database.read_session() as session:
                        current = await CollectionRepository(session).find_server(
                            *lead.key
                        )
                    observations = [
                        observation
                        for copy in copies
                        for observation in await self._observe(
                            current, copy, by_server[copy.server_id]
                        )
                    ]
                    async with self._database.write_session() as session:
                        row = await self._store(
                            CollectionRepository(session),
                            copies,
                            placement=placement,
                            members=members,
                            unknown=len(unknown),
                            leads=leads,
                            managed=previous is not None and previous.id in managed_ids,
                            now=utc_now(),
                        )
                        self._record(row, observations)
                        await apply_needs(
                            session, collections=[row], app_config=self._config
                        )
                identified += row.tmdb_collection_id is not None
                if (
                    row.id is not None
                    and row.tmdb_collection_id is not None
                    and (
                        previous is None
                        or previous.tmdb_collection_id != row.tmdb_collection_id
                    )
                ):
                    newly_identified.append(row.id)
                await self._publisher.broadcast(
                    "collection.updated", {"collection_id": row.id}
                )
            async with self._database.read_session() as session:
                gone = {
                    row.id: missing
                    for row in await CollectionRepository(session).list_all()
                    if row.id is not None
                    and (
                        missing := {
                            key
                            for part in row.copies
                            if part.server_id in by_server
                            and (key := (part.server_id, part.server_item_id or ""))
                            not in seen
                        }
                    )
                    and (
                        not library_ids
                        or (
                            row.last_synced_at is not None
                            and set(row.library_ids) & set(library_ids)
                        )
                    )
                }
                managed = await CollectionRepository(session).managed_ids(list(gone))
            for collection_id, missing in gone.items():
                async with (
                    self._downloads.asset_locks.acquire(f"collection:{collection_id}"),
                    self._database.write_session() as session,
                ):
                    repo = CollectionRepository(session)
                    if collection_id in managed:
                        # Overture keeps what it manages; the next rule sync
                        # puts the collection back on the server.
                        await repo.clear_server_copies(
                            collection_id, utc_now(), missing
                        )
                        continue
                    await self._downloads.cancel_assets(
                        session, AssetScope(collection_id=collection_id)
                    )
                    await repo.delete_ids([collection_id])
                await self._downloads.committed(session)
            await self._publisher.broadcast("collections.changed")
        await queue_catalog_themes_for_collections(
            newly_identified,
            theme_order=theme_order,
            downloads=self._downloads,
            app_config=self._config,
            database=self._database,
        )
        if theme_order is IncrementalThemeOrder.OFF and newly_identified:
            await self._queue_incremental_choices(newly_identified)
        await job.report(
            JobOutcome.STARTED,
            "Collections",
            f"{len(listed)} listed, {identified} with TMDB IDs, "
            f"{len(gone) - len(managed)} removed, "
            f"{len(managed)} managed no longer on the server",
            finished=False,
        )

    async def _observe(
        self, current: MediaCollection | None, listed: ListedCopy, provider: Provider
    ) -> list[_Observation]:
        """Read what one server copy shows of each asset, with no transaction open."""
        copy = listed.collection
        upload = Destination(listed.server_id, copy.id, DeliveryChannel.UPLOAD)
        observations = [
            _Observation(
                kind,
                upload,
                await self._checks.image_evidence(current, kind, upload, provider, url),
                ref=url,
            )
            for kind, url in (
                (ServerAsset.POSTER, copy.thumb_url),
                (ServerAsset.BACKGROUND, copy.art_url),
            )
        ]
        match provider.collections:
            case UploadThemes():
                observations.append(
                    _Observation(
                        ServerAsset.THEME,
                        upload,
                        await self._checks.theme_evidence(
                            current, upload, provider, copy.theme_id
                        ),
                        ref=copy.theme_id,
                    )
                )
            case FolderThemes():
                folder = Destination(listed.server_id, copy.id, DeliveryChannel.FILE)
                known = (
                    file_facts(delivery(read_asset(current, ServerAsset.THEME), folder))
                    if current is not None
                    else None
                )
                try:
                    found = await owned_thread(
                        collection_folder, provider.server, copy.path
                    )
                    facts = await owned_thread(inspect_theme_file, found, known)
                except OSError, ValueError:
                    logger.debug("Collection theme folder unavailable: %s", copy.title)
                else:
                    observations.append(
                        _Observation(
                            ServerAsset.THEME,
                            folder,
                            Evidence.SAME,
                            ref=None,
                            file=facts,
                        )
                    )
            case _:
                pass
        return observations

    def _record(
        self, row: MediaCollection, observations: Sequence[_Observation]
    ) -> None:
        """Place the collection's assets on its copies and record what each shows."""
        place_collection(row, self._downloads.provider_registry)
        now = utc_now()
        for seen in observations:
            if seen.destination.channel is DeliveryChannel.FILE:
                record_file(
                    row, seen.kind, seen.file, destination=seen.destination, at=now
                )
            else:
                observe(
                    row,
                    seen.kind,
                    seen.destination,
                    seen.evidence,
                    ref=seen.ref,
                    at=now,
                )

    async def _queue_incremental_choices(self, collection_ids: list[int]) -> None:
        """Use the oldest enabled incremental policy covering each collection."""
        async with self._database.read_session() as session:
            schedules = await SavedScheduleRepository(session).of_kind(
                ScheduleKind.SYNC
            )
            policies = [
                SyncScheduleConfig.model_validate(row.payload)
                for row in schedules
                if row.enabled
            ]
            rows = await CollectionRepository(session).bulk_targets(
                collection_ids=collection_ids
            )
        groups: dict[IncrementalThemeOrder, list[int]] = {}
        for row in rows:
            for policy in policies:
                if (
                    policy.mode == "incremental"
                    and policy.download_themes is not IncrementalThemeOrder.OFF
                    and (
                        not policy.library_ids
                        or set(row.library_ids) & set(policy.library_ids)
                    )
                ):
                    groups.setdefault(policy.download_themes, []).append(row.id or 0)
                    break
        for order, ids in groups.items():
            await queue_catalog_themes_for_collections(
                ids,
                theme_order=order,
                downloads=self._downloads,
                app_config=self._config,
                database=self._database,
            )

    @staticmethod
    async def _store(
        repository: CollectionRepository,
        listed: Sequence[ListedCopy],
        *,
        placement: Sequence[_Placed],
        members: list[ServerItemFacts],
        unknown: int,
        leads: bool,
        managed: bool,
        now: datetime,
    ) -> MediaCollection:
        """Store a collection from its server copies, the lead copy first.

        Only the lead copy, when *leads*, says the collection's kind.
        """
        collection = listed[0].collection
        row = await repository.find_server(*listed[0].key) or MediaCollection(
            created_at=now,
            tmdb_collection_id=collection.tmdb_id
            if any(placed.media_type is MediaType.MOVIE for placed in placement)
            else None,
        )
        if leads and row.kind is not CollectionKind.SEPARATOR:
            # A separator is Overture's, an empty collection to the server.
            row.kind = (
                CollectionKind.SMART if collection.smart else CollectionKind.REGULAR
            )
        row.sqlmodel_update(
            {
                "server_added_at": collection.added_at,
                "provider_tmdb_id": collection.tmdb_id,
                "last_synced_at": now,
                "updated_at": now,
            }
        )
        # What a managed collection spans is Overture's choice; otherwise it is
        # wherever the server's members are.
        if managed:
            _store_paths(row, placement)
        else:
            _store_placement(row, placement)
        # Overture owns what it manages, and its next sync sends those choices;
        # members saved in Overture and not yet synced win over the server's too.
        keep_members = row.id is not None and row.unsynced
        if not (keep_members or managed):
            _store_choices(row, collection)
        if not keep_members:
            row.child_count = len(members) + unknown
        repository.session.add(row)
        await repository.session.flush()
        if row.id is None:
            raise RuntimeError("Collection row was not assigned an ID")
        if not keep_members:
            await repository.replace_members(row.id, [member.id for member in members])
        return row


def _store_choices(row: MediaCollection, collection: ServerCollection) -> None:
    """Take the title, summary, sorting and visibility the server holds."""
    if row.id is None or collection.summary != row.summary:
        row.summary_source = collection.summary
    if row.id is None or (
        row.summary is not None and row.summary_format == literal_template(row.summary)
    ):
        row.summary_format = (
            literal_template(collection.summary)
            if collection.summary is not None
            else None
        )
    sort_title = collection.sort_title or row.sort_title
    if row.id is None or (
        row.sort_title is not None
        and row.sort_title_format == literal_template(row.sort_title)
    ):
        row.sort_title_format = (
            literal_template(sort_title) if sort_title is not None else None
        )
    row.sqlmodel_update(
        {
            "title": collection.title,
            "summary": collection.summary,
            "sort_title": sort_title,
        }
    )
    if collection.collection_mode is not None:
        row.collection_mode = collection.collection_mode
    if collection.collection_filtering is not None:
        row.collection_filtering = collection.collection_filtering
    # Overture keeps orders the server cannot sort by as a custom order.
    computed = row.order_type not in {
        CollectionOrder.RELEASE_ASC,
        CollectionOrder.TITLE_ASC,
    }
    if collection.order_type is not None and not (
        collection.order_type is CollectionOrder.CUSTOM and computed
    ):
        row.order_type = collection.order_type
