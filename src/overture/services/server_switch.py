"""Moving what Overture keeps for one media server over to another."""

lazy import logging
lazy from collections.abc import Collection

lazy from sqlmodel import col, select, update
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..config import Settings, media_server_identity
lazy from ..db.models.collection_group import CollectionGroup
lazy from ..db.models.job_result import JobRun
lazy from ..db.models.media_collection import MediaCollection
lazy from ..db.models.saved_schedule import SavedSchedule
lazy from ..db.models.settings import SETTINGS_ROW_ID, AppSettings
lazy from ..db.models.shared import PolicyOverrides
lazy from ..db.session import Database
lazy from ..domain import (
    DEFAULT_COLLECTION_ORDER,
    CollectionKind,
    CollectionMode,
    CollectionOrder,
    MediaType,
    ScheduleKind,
    ServerType,
)
lazy from ..jobs.kinds import JobKind
lazy from ..repositories.collections import CollectionRepository
lazy from ..utils.collection_fields import available_orders
lazy from .schedule_store import SYNC_SERVER_SCHEDULE, load_schedule, patch_payload

logger = logging.getLogger(__name__)

#: Runs whose findings name the earlier server's items and collections.
_SERVER_RUNS = (JobKind.SERVER_AUDIT, JobKind.SERVER_AUDIT_FIX)


def _order_fits(
    order: CollectionOrder | None,
    server: ServerType,
    media_types: Collection[MediaType],
) -> bool:
    return order is None or all(
        order in available_orders(server, media_type, smart=False)
        for media_type in media_types
    )


def _fit_overrides(
    overrides: PolicyOverrides,
    server: ServerType,
    media_types: Collection[MediaType],
) -> None:
    """Leave a group's or a rule's choices only what *server* offers."""
    if not _order_fits(overrides.order_type, server, media_types):
        overrides.order_type = None
    if server is ServerType.PLEX:
        return
    overrides.collection_mode = None
    overrides.collection_filtering = None
    overrides.visible_home = None
    overrides.visible_shared = None
    overrides.visible_library = None
    overrides.home_order = None
    overrides.member_label = None


def _fit_defaults(settings: AppSettings, server: ServerType) -> None:
    """Leave the global collection defaults only what *server* offers."""
    if not _order_fits(settings.collection_order_default, server, tuple(MediaType)):
        settings.collection_order_default = DEFAULT_COLLECTION_ORDER
    if server is ServerType.PLEX:
        return
    settings.collection_mode_default = CollectionMode.DEFAULT
    settings.collection_visible_home = False
    settings.collection_visible_shared = False
    settings.collection_visible_library = False


def _fit_collection(row: MediaCollection, server: ServerType) -> None:
    """Forget a collection's server copies and what only *server* lacks.

    The next sync makes its copies on the new server and sends its art and
    theme to them, as for any collection that has none yet.
    """
    for part in row.libraries:
        part.server_item_id = None
    if row.kind is CollectionKind.SMART:
        row.kind = CollectionKind.REGULAR
    row.thumb_url = None
    row.art_url = None
    row.server_path = None
    row.server_added_at = None
    row.server_theme_id = None
    row.provider_tmdb_id = None
    row.unsynced = True
    if not _order_fits(row.order_type, server, row.media_types):
        row.order_type = DEFAULT_COLLECTION_ORDER
    if server is not ServerType.PLEX:
        row.collection_mode = None
        row.collection_filtering = None
        row.visible_home = False
        row.visible_shared = False
        row.visible_library = False
    if (rule := row.rule) is not None:
        _fit_overrides(rule, server, row.media_types)
        if server is not ServerType.PLEX:
            rule.smart = False


def _fit_group(group: CollectionGroup, server: ServerType) -> None:
    _fit_overrides(group, server, tuple(MediaType))
    if server is not ServerType.PLEX and group.generator is not None:
        group.generator = {**group.generator, "smart": False}


class MediaServerSwitch:
    """Notice that Overture now talks to another media server, and move over.

    Collections and groups are Overture's own. Their server copies, and the
    choices the new server cannot keep, are let go, so the next sync makes
    them there, or takes over a collection of the same title the server
    already holds. Collections the earlier server made itself, which Overture
    does not manage, go with it.
    """

    def __init__(self, *, database: Database, app_config: Settings) -> None:
        self._database = database
        self._app_config = app_config

    async def reconcile(self) -> None:
        """Move over if the configured server is another than the last one."""
        server = self._app_config.MEDIA_SERVER
        if server is None:
            return
        current = media_server_identity(server, self._app_config.MEDIA_SERVER_URL)
        async with self._database.read_session() as session:
            last = (await load_schedule(session, SYNC_SERVER_SCHEDULE)).payload
        if last.last_media_server == current:
            return
        async with self._database.write_session() as session:
            if last.last_media_server is not None:
                await self._move_to(session, server)
            await patch_payload(
                session, SYNC_SERVER_SCHEDULE, last_media_server=current
            )

    async def _move_to(self, session: AsyncSession, server: ServerType) -> None:
        repo = CollectionRepository(session)
        rows = await repo.list_all()
        dropped = [row.id or 0 for row in rows if row.rule is None]
        await repo.delete_ids(dropped)
        kept = [row for row in rows if (row.id or 0) not in set(dropped)]
        for row in kept:
            _fit_collection(row, server)
            session.add(row)
        for group in await repo.groups():
            _fit_group(group, server)
            session.add(group)
        # Unsaved settings are the defaults, which every server offers.
        if (settings := await session.get(AppSettings, SETTINGS_ROW_ID)) is not None:
            _fit_defaults(settings, server)
            session.add(settings)
        # Library IDs and polling checkpoints belong to the server that issued
        # them; an emptied list syncs every library.
        for record in (
            await session.exec(
                select(SavedSchedule).where(
                    col(SavedSchedule.kind) == ScheduleKind.SYNC
                )
            )
        ).all():
            record.payload = {**record.payload, "library_ids": []}
            record.state = {}
            session.add(record)
        await session.exec(
            update(JobRun)
            .where(col(JobRun.kind).in_(_SERVER_RUNS))
            .values(cleared=True)
        )
        logger.info(
            "Media server changed to %s: %d collections are made there by the "
            "next sync; %d the earlier server held itself are forgotten",
            server.display_name,
            len(kept),
            len(dropped),
        )
