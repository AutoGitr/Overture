"""Reading collections as clients see them."""

lazy from fastapi import Response

lazy from ...catalog_contract.contract import entry_file_stem
lazy from ...db.ledger import Destination, delivery, dimensions, read_asset
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.settings import get_app_settings
lazy from ...domain import ITEM_ART_TYPES, ArtType, CollectionKind, ImageSize
lazy from ...integrations.proxy import ProxyClientManager
lazy from ...repositories.collection_items import CollectionItemRepository
lazy from ...repositories.collections import CollectionRepository
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
lazy from ..catalog.agreement import collection_agreement
lazy from ..downloads.collection_theme import collection_theme_unavailable
lazy from ..provider_images import proxy_provider_image
lazy from .access import CollectionAccess, catalog_collections
lazy from .membership import display_order
lazy from .policy import resolve_policy
lazy from .rules import criteria_of, rule_read


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
            )
        return [
            collection_read(
                row,
                catalog.get(row.tmdb_collection_id or 0),
                row.rule,
                copies=self._access.held_copies(row),
            ).model_copy(
                update={
                    "below_minimum": row.child_count < policy.minimum_items,
                    "home_order": policy.home_order,
                    "contributed_style": policy.contributed_style,
                    "catalog_selections": collection_agreement(
                        row,
                        catalog.get(row.tmdb_collection_id or 0),
                        policy.overturedb_posters,
                    ),
                    "has_incorrect_aspect_ratio": any(
                        has_incorrect_aspect_ratio(
                            *dimensions(read_asset(row, art_type.server_asset)),
                            art_type,
                            defaults.aspect_ratio_tolerance,
                        )
                        for art_type in ITEM_ART_TYPES
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
            records = RecordRepository(session)
            stored = await records.rows(MediaCollection, collection_id)
            libraries = await records.library_names(stored)
        return DatabaseRecord.of(stored, read, libraries=libraries)

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
                list(
                    {
                        member.id: member
                        for member in await CollectionItemRepository(session).members(
                            row.id or 0
                        )
                    }.values()
                ),
                row.order_type,
            )
            policy = await self._access.policy(session, row.group, saved)
            catalog = await catalog_collections(
                session,
                {row.tmdb_collection_id} if row.tmdb_collection_id else set(),
            )
        entry = catalog.get(row.tmdb_collection_id or 0)
        reason = await collection_theme_unavailable(
            row, provider_registry=self._access.provider_registry
        )
        return CollectionDetail(
            **collection_read(
                row,
                entry,
                saved,
                copies=self._access.held_copies(row),
            )
            .model_copy(
                update={
                    "below_minimum": row.child_count < policy.minimum_items,
                    "contributed_style": policy.contributed_style,
                    "catalog_selections": collection_agreement(
                        row, entry, policy.overturedb_posters
                    ),
                }
            )
            .model_dump(),
            effective_sync_mode=policy.sync_mode,
            lists_missing=any(
                criteria_of(part).listing_sources()
                for part in row.libraries
                if saved is not None and part.criteria is not None
            ),
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
        """Proxy the lead copy's poster or background with bounded response size."""
        self._access.require_collections()
        if art_type.owned_by_season:
            raise PublicServiceError(404, "Collection image not found")
        async with self._access.database.read_session() as session:
            row = await CollectionRepository(session).get(collection_id)
        lead = self._access.lead(row) if row is not None else None
        if row is None or row.last_synced_at is None or lead is None:
            raise PublicServiceError(404, "Collection not found")
        seen = delivery(
            read_asset(row, art_type.server_asset),
            Destination(lead.server_id, lead.server_item_id),
        )
        if seen is None or (current_url := seen.observed_ref) is None:
            raise PublicServiceError(404, "Collection image not found")
        request = await self._access.provider(
            lead.server_id
        ).build_collection_image_request(
            lead.server_item_id or "", art_type, size, current_url=current_url
        )
        return await proxy_provider_image(request, proxy_clients=self._proxy_clients)
