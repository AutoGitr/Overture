"""Adopting unmanaged server collections and orphaning managed ones."""

lazy import urllib.parse
lazy from collections.abc import Awaitable, Callable

lazy from ...db.models.media_collection import MediaCollection
lazy from ...domain import CollectionKind
lazy from ...media_servers.plex.query import (
    UnmappableFilterError,
    decompile_plex_query,
    plex_field,
    plex_field_keys,
    plex_term_key,
)
lazy from ...repositories.collection_items import CollectionItemRepository
lazy from ...repositories.collections import CollectionRepository
lazy from ...schemas.collections import (
    CollectionAdoption as CollectionAdoptionRequest,
)
lazy from ...schemas.collections import (
    CollectionAdoptionPlan,
    CollectionDetail,
    CollectionLibraryCriteria,
    CollectionRuleRead,
    CollectionRuleWrite,
)
lazy from ...utils.collection_groups import collection_group
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.time import utc_now
lazy from ..needs import apply_needs
lazy from .access import CollectionAccess
lazy from .destinations import place_collection
lazy from .membership import Membership
lazy from .reader import CollectionReader
lazy from .rules import criteria_of, member_criteria, shared_franchise

type SaveRuleCallback = Callable[
    [MediaCollection, CollectionRuleWrite], Awaitable[CollectionRuleRead]
]


class CollectionAdoption:
    """Manage adoption of external server collections and orphaning of managed ones."""

    def __init__(
        self,
        *,
        access: CollectionAccess,
        membership: Membership,
        reader: CollectionReader,
        save_rule: SaveRuleCallback,
    ) -> None:
        self._access = access
        self._membership = membership
        self._reader = reader
        self._save_rule = save_rule

    async def adoption_plan(self, collection_id: int) -> CollectionAdoptionPlan:
        """What adopting a collection made outside Overture would keep.

        A regular collection keeps its current members; a Plex smart collection
        keeps its filter, read back into criteria. Movies that all belong to one
        TMDB collection keep it as their source, and it gives them art and a theme.

        Raises:
            PublicServiceError: 409 when it already has a rule, 422 when its
                Plex filter has terms criteria cannot express.
        """
        async with self._access.database.read_session() as session:
            row = await self._access.require(session, collection_id)
            if row.rule is not None:
                raise PublicServiceError(409, "Overture already manages it")
            members = await CollectionItemRepository(session).members(collection_id)
        franchise = shared_franchise(members)
        # Only TMDB can list a franchise's parts on each sync.
        kept = franchise if self._access.app_config.tmdb_configured else None
        return CollectionAdoptionPlan(
            rule=await self._smart_adoption_rule(row)
            if row.kind is CollectionKind.SMART
            else CollectionRuleWrite(
                libraries=[
                    CollectionLibraryCriteria(
                        library_id=part.library_id,
                        criteria=member_criteria(
                            row,
                            [m for m in members if m.library_id == part.library_id],
                            franchise=kept,
                        ),
                    )
                    for part in row.libraries
                ]
            ),
            tmdb_collection_id=row.tmdb_collection_id or franchise,
        )

    async def adopt(
        self, collection_id: int, body: CollectionAdoptionRequest
    ) -> CollectionDetail:
        """Give a collection made outside Overture the rule its plan keeps."""
        plan = await self.adoption_plan(collection_id)
        group = collection_group(body.group)
        async with self._access.locked(collection_id):
            async with self._access.database.write_session() as session:
                stored = await self._access.require(session, collection_id)
                stored.group = await CollectionRepository(session).ensure_group(group)
                stored.tmdb_collection_id = plan.tmdb_collection_id
                session.add(stored)
            await self._save_rule(stored, plan.rule)
        return await self._reader.get(collection_id)

    async def orphan(self, collection_id: int) -> CollectionDetail:
        """Stop managing a collection; the server keeps it, listed as unmanaged.

        The reverse of adoption: the rule and group go, and the collection is
        listed under Unmanaged until it is adopted again. Plex holds a
        cross-library collection as one collection per library, and each server
        its own, which are unrelated once Overture stops managing them, so this
        row keeps the lead copy and the next library sync lists the rest on
        their own.

        Raises:
            PublicServiceError: 409 when it has no server copy to keep, its
                group's set made it, or its Plex filter reads Overture's labels.
        """
        async with self._access.locked(collection_id):
            await self.orphan_locked(collection_id)
        await self._access.changed()
        return await self._reader.get(collection_id)

    async def orphan_locked(
        self, collection_id: int, *, set_removed: bool = False
    ) -> None:
        """Orphan a collection whose locks the caller holds.

        *set_removed* is for a group deleted with its set, so nothing
        recreates what the set made.
        """
        async with self._access.database.write_session() as session:
            row = await self._access.require(session, collection_id)
            rule = row.rule
            if rule is None:
                raise PublicServiceError(409, "Overture does not manage it")
            lead = self._access.lead(row)
            if lead is None:
                raise PublicServiceError(
                    409, "It is not on the media server; delete it instead"
                )
            if row.generated_value is not None and not set_removed:
                raise PublicServiceError(
                    409, "Its group's set made it; remove its value from the set"
                )
            if rule.smart and any(
                self._membership.labels(
                    part.library_id, part.media_type, criteria_of(part)
                )
                for part in row.libraries
                if part.criteria is not None
            ):
                raise PublicServiceError(
                    409,
                    "Its Plex filter reads labels only Overture keeps; "
                    "make it a regular collection first",
                )
            row.rule = None
            row.libraries = [
                p
                for p in row.libraries
                if (p.server_id, p.server_item_id)
                == (lead.server_id, lead.server_item_id)
            ]
            for part in row.libraries:
                part.criteria = None
                session.add(part)
            row.group = None
            row.generated_value = None
            row.unsynced = False
            row.active_start_mmdd = None
            row.active_end_mmdd = None
            row.delete_when_inactive = None
            row.tmdb_collection_id = row.provider_tmdb_id
            row.updated_at = utc_now()
            place_collection(row, self._access.provider_registry)
            await apply_needs(session, collections=[row])
            session.add(row)

    async def _smart_adoption_rule(self, row: MediaCollection) -> CollectionRuleWrite:
        part = self._access.lead(row)
        if part is None or part.server_item_id is None:
            raise PublicServiceError(409, "The collection has no server copy")
        provider = self._access.provider(part.server_id)
        media_type = part.media_type
        query = await provider.smart_collection_filter(part.server_item_id)
        fields = plex_field_keys(media_type)
        names: dict[str, dict[str, str]] = {}
        for name, _ in urllib.parse.parse_qsl(query):
            key = plex_term_key(name, media_type)
            field = fields.get(key)
            if field is None or key in names or plex_field(field).type != "tag":
                continue
            choices = await self._access.filter_choices(
                part.library_id, media_type, key
            )
            names[key] = dict(choices)
        try:
            decompiled = decompile_plex_query(query, media_type=media_type, names=names)
        except UnmappableFilterError as exc:
            raise PublicServiceError(422, str(exc)) from exc
        return CollectionRuleWrite(
            libraries=[
                CollectionLibraryCriteria(
                    library_id=part.library_id, criteria=decompiled.criteria
                )
            ],
            smart=True,
            order_type=decompiled.order,
            limit=decompiled.limit,
        )
