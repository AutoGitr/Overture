"""Whether each asset is wanted at all: the one rule, applied to stored assets.

An asset nothing is wanted for is complete as it is, and its stored status
says so. What is wanted follows outside the asset: OvertureDB's No theme flag
(trusted while the catalog is enabled and the setting trusts it) for a
title's or collection's theme, and a collection's policy for its background
and theme. Whatever changes one of those calls :meth:`AssetNeeds.apply` for
the rows it touched, or :meth:`AssetNeeds.apply_all`.
"""

lazy from collections.abc import Sequence

lazy from sqlmodel import col, inspect, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..config import Settings
lazy from ..db.ledger import set_needed
lazy from ..db.models.media_collection import MediaCollection
lazy from ..db.models.media_item import MediaItem
lazy from ..db.models.settings import AppSettings, get_app_settings
lazy from ..db.session import CHUNK_SIZE, Database
lazy from ..domain import ServerAsset
lazy from ..media_servers.registry import ProviderRegistry
lazy from ..repositories.catalog import CatalogRepository
lazy from .collections.destinations import place_collection
lazy from .collections.policy import resolve_policy
lazy from .schedule_store import CATALOG_SCHEDULE, load_schedule


async def _trusts_no_theme(
    session: AsyncSession, settings: AppSettings, app_config: Settings
) -> bool:
    """Whether OvertureDB's No theme flag counts: the catalog is on and trusted."""
    if not settings.overturedb_no_theme:
        return False
    schedule = await load_schedule(session, CATALOG_SCHEDULE, timezone=app_config.TZ)
    return schedule.enabled


async def apply_needs(
    session: AsyncSession,
    *,
    items: Sequence[MediaItem] = (),
    collections: Sequence[MediaCollection] = (),
    app_config: Settings,
) -> None:
    """Record what is wanted for each of *items* and *collections*."""
    settings = await get_app_settings(session)
    trusted = await _trusts_no_theme(session, settings, app_config)
    catalog = CatalogRepository(session)
    if items:
        entries = await catalog.items_by_media_item_id(items) if trusted else {}
        for item in items:
            entry = entries.get(item.id or 0)
            set_needed(item, ServerAsset.THEME, not (entry and entry.no_theme))
            session.add(item)
    if collections:
        entries = (
            await catalog.collections_by_tmdb_id(
                {
                    row.tmdb_collection_id
                    for row in collections
                    if row.tmdb_collection_id
                }
            )
            if trusted
            else {}
        )
        for row in collections:
            # A row made in this session has not loaded what decides its policy.
            if unloaded := {"group", "rule"} & inspect(row).unloaded:
                await session.refresh(row, list(unloaded))
            policy = resolve_policy(settings, row.group, row.rule)
            entry = entries.get(row.tmdb_collection_id or 0)
            set_needed(row, ServerAsset.BACKGROUND, policy.backgrounds)
            set_needed(
                row, ServerAsset.THEME, policy.themes and not (entry and entry.no_theme)
            )
            session.add(row)


class AssetNeeds:
    """Keep every stored asset's need, and collections' places, in step."""

    def __init__(
        self,
        *,
        app_config: Settings,
        database: Database,
        provider_registry: ProviderRegistry,
    ) -> None:
        self._app_config = app_config
        self._database = database
        self._provider_registry = provider_registry

    async def apply_all(self) -> None:
        """Record what is wanted for every title and collection, a chunk at a time.

        Run at startup and after the catalog or a setting that decides needs
        changed.
        """
        await self._apply(MediaItem)
        await self.apply_collections()

    async def apply_collections(self) -> None:
        """Record what is wanted for every collection, and place its assets.

        Each collection's assets are placed on its copies on the configured
        servers, so a server that joined or left ``MEDIA_SERVERS`` is
        accounted for. Run after a group's or collection's policy changed.
        """
        await self._apply(MediaCollection)

    async def _apply[RowT: MediaItem | MediaCollection](
        self, model: type[RowT]
    ) -> None:
        after = 0
        while True:
            async with self._database.write_session() as session:
                rows = list(
                    (
                        await session.exec(
                            select(model)
                            .where(col(model.id) > after)
                            .order_by(col(model.id))
                            .limit(CHUNK_SIZE)
                        )
                    ).all()
                )
                if not rows:
                    return
                items = [row for row in rows if isinstance(row, MediaItem)]
                collections = [row for row in rows if isinstance(row, MediaCollection)]
                for row in collections:
                    place_collection(row, self._provider_registry)
                await apply_needs(
                    session,
                    items=items,
                    collections=collections,
                    app_config=self._app_config,
                )
            after = rows[-1].id or after
