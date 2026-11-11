"""Reading collections as clients see them."""

lazy from fastapi import Response
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...config import Settings
lazy from ...dataset_contract.contract import entry_file_stem
lazy from ...db.art_slots import find_art_slot
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.public_dataset import PublicDatasetCollection
lazy from ...db.models.settings import get_app_settings
lazy from ...domain import ITEM_ART_TYPES, ArtType, CollectionKind, ImageSize
lazy from ...integrations.proxy import ProxyClientManager
lazy from ...repositories.collections import CollectionRepository
lazy from ...repositories.public_dataset import PublicDatasetRepository
lazy from ...repositories.records import RecordRepository
lazy from ...schemas.collections import (
    CollectionDefaults,
    CollectionDetail,
    CollectionRead,
    collection_read,
)
lazy from ...schemas.records import DatabaseRecord
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.image import has_incorrect_aspect_ratio
lazy from ..downloads.collection_theme import collection_theme_unavailable
lazy from ..provider_images import proxy_provider_image
lazy from ..schedule_store import PUBLIC_DATASET_SCHEDULE, load_schedule
lazy from .access import CollectionAccess
lazy from .membership import display_order
lazy from .policy import resolve_policy
lazy from .rules import rule_read


async def catalog_collections(
    session: AsyncSession, tmdb_ids: set[int], *, app_config: Settings
) -> dict[int, PublicDatasetCollection]:
    """Return the catalog's entries for these TMDB collections, if it is enabled."""
    schedule = await load_schedule(
        session, PUBLIC_DATASET_SCHEDULE, timezone=app_config.TZ
    )
    if not schedule.enabled or not tmdb_ids:
        return {}
    return await PublicDatasetRepository(session).collections_by_tmdb_id(tmdb_ids)


class CollectionReader:
    """List collections and show one, with their catalog entries and policy."""

    def __init__(
        self, *, access: CollectionAccess, proxy_clients: ProxyClientManager
    ) -> None:
        self._access = access
        self._proxy_clients = proxy_clients

    async def listed(self) -> list[CollectionRead]:
        """Return the collections the last sync listed.

        Separators are left out: each is part of its group, which keeps it.
        """
        self._access.require_collections()
        async with self._access.database.read_session() as session:
            repo = CollectionRepository(session)
            rows = [
                row
                for row in await repo.list_listed()
                if row.kind is not CollectionKind.SEPARATOR
            ]
            defaults = await get_app_settings(session)
            catalog = await catalog_collections(
                session,
                {row.tmdb_collection_id for row in rows if row.tmdb_collection_id},
                app_config=self._access.app_config,
            )
        return [
            collection_read(
                row,
                catalog.get(row.tmdb_collection_id or 0),
                row.rule,
                trust_no_theme=defaults.overturedb_no_theme,
                backgrounds=policy.backgrounds,
            ).model_copy(
                update={
                    "below_minimum": row.child_count < policy.minimum_items,
                    "home_order": policy.home_order,
                    "has_incorrect_aspect_ratio": any(
                        has_incorrect_aspect_ratio(
                            slot.width,
                            slot.height,
                            art_type,
                            defaults.aspect_ratio_tolerance,
                        )
                        for art_type in ITEM_ART_TYPES
                        if (slot := find_art_slot(row, art_type)) is not None
                    ),
                }
            )
            for row in rows
            for policy in (resolve_policy(defaults, row.group, row.rule),)
        ]

    async def record(self, collection_id: int) -> DatabaseRecord:
        """Return a collection's stored rows and what the API derives from them."""
        read = await self.get(collection_id)
        async with self._access.database.read_session() as session:
            stored = await RecordRepository(session).rows(
                MediaCollection, collection_id
            )
        return DatabaseRecord.of(stored, read)

    async def get(self, collection_id: int) -> CollectionDetail:
        """Return one collection with its members and catalog entry.

        Raises:
            PublicServiceError: 404 for a separator, which only its group shows.
        """
        async with self._access.database.read_session() as session:
            row = await self._access.require(session, collection_id)
            if row.kind is CollectionKind.SEPARATOR:
                raise PublicServiceError(404, "Collection not found")
            saved = row.rule
            members = display_order(
                await CollectionRepository(session).members(row.id or 0), row.order_type
            )
            policy = await self._access.policy(session, row.group, saved)
            catalog = await catalog_collections(
                session,
                {row.tmdb_collection_id} if row.tmdb_collection_id else set(),
                app_config=self._access.app_config,
            )
            trust_no_theme = (await get_app_settings(session)).overturedb_no_theme
        entry = catalog.get(row.tmdb_collection_id or 0)
        reason = await collection_theme_unavailable(
            row, provider=self._access.provider(), app_config=self._access.app_config
        )
        return CollectionDetail(
            **collection_read(
                row,
                entry,
                saved,
                trust_no_theme=trust_no_theme,
                backgrounds=policy.backgrounds,
            )
            .model_copy(
                update={"below_minimum": row.child_count < policy.minimum_items}
            )
            .model_dump(),
            effective_sync_mode=policy.sync_mode,
            member_ids=[member.id for member in members],
            rule=rule_read(saved, row),
            theme_unavailable=reason,
            theme_writable=reason is None,
            catalog_entry_key=entry_file_stem({"tmdb_id": entry.tmdb_id})
            if entry
            else None,
            catalog_title=entry.title if entry else None,
            youtube_id_overturedb=entry.youtube_id_overturedb if entry else None,
            youtube_id_themerrdb=entry.youtube_id_themerrdb if entry else None,
        )

    async def inherited_policy(self, name: str | None = None) -> CollectionDefaults:
        """Expose resolved defaults for form placeholders without duplicating rules."""
        async with self._access.database.read_session() as session:
            policy = await self._access.policy(
                session, await self._access.group(session, name)
            )
        return CollectionDefaults.model_validate(
            {key: getattr(policy, key) for key in CollectionDefaults.model_fields}
        )

    async def image(
        self, collection_id: int, art_type: ArtType, size: ImageSize | None
    ) -> Response:
        """Proxy a collection's poster or background with bounded response size."""
        provider = self._access.provider()
        if art_type.owned_by_season:
            raise PublicServiceError(404, "Collection image not found")
        async with self._access.database.read_session() as session:
            row = await CollectionRepository(session).get(collection_id)
        if row is None or row.last_synced_at is None or row.server_item_id is None:
            raise PublicServiceError(404, "Collection not found")
        if (current_url := row.server_image_url(art_type)) is None:
            raise PublicServiceError(404, "Collection image not found")
        request = await provider.build_collection_image_request(
            row.server_item_id, art_type, size, current_url=current_url
        )
        return await proxy_provider_image(request, proxy_clients=self._proxy_clients)
