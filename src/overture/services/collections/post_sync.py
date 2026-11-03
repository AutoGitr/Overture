"""What a sync does beyond membership, as independent steps.

Each step decides from the synced collection whether it applies, so a new
step is a new :class:`PostSyncStep`, not a change to the sync itself.
"""

lazy from collections.abc import Sequence
lazy from dataclasses import dataclass
lazy from typing import Protocol

lazy from ...db.art_slots import read_art_slot
lazy from ...db.models.collection_rule import CollectionRule
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.settings import AppSettings, get_app_settings
lazy from ...domain import ArtType, MediaType
lazy from ...repositories.collections import CollectionRepository
lazy from ...schemas.art import SaveArtRequest
lazy from ...schemas.collections import SetCollectionThemeRequest
lazy from ...utils.collection_formats import format_member_tag
lazy from ...utils.errors import PublicServiceError
lazy from ..art.collection_art import CollectionArtService
lazy from .access import CollectionAccess
lazy from .arr_requests import CollectionArr
lazy from .member_effects import MemberEffects
lazy from .membership import Membership
lazy from .policy import CollectionPolicy
lazy from .reader import catalog_collections
lazy from .rules import criteria
lazy from .sources import SourceResolver
lazy from .themes import CollectionThemes


@dataclass(slots=True, frozen=True)
class SyncedCollection:
    """A collection whose members were just synced, with what its steps read."""

    row: MediaCollection
    rule: CollectionRule | None
    policy: CollectionPolicy
    members: list[MediaItem]
    library_items: list[MediaItem]
    settings: AppSettings
    plex: bool

    @property
    def collection_id(self) -> int:
        return self.row.id or 0

    @property
    def media_type(self) -> MediaType:
        return self.row.media_type

    @property
    def on_server(self) -> bool:
        return self.row.server_item_id is not None


class PostSyncStep(Protocol):
    """One thing a sync does after membership, whatever the other steps do."""

    @property
    def name(self) -> str: ...

    def applies(self, synced: SyncedCollection) -> bool: ...

    async def run(self, synced: SyncedCollection) -> None: ...


class AutoAssets:
    """Match art from the franchise or a listed person, and the catalog's theme."""

    name = "Automatic assets"

    def __init__(
        self,
        *,
        access: CollectionAccess,
        art: CollectionArtService,
        themes: CollectionThemes,
    ) -> None:
        self._access = access
        self._art = art
        self._themes = themes

    def applies(self, synced: SyncedCollection) -> bool:
        return synced.on_server

    async def run(self, synced: SyncedCollection) -> None:
        row, policy = synced.row, synced.policy
        if policy.auto_match_art:
            for art_type in (ArtType.POSTER, ArtType.BACKGROUND):
                if read_art_slot(row, art_type).url:
                    continue
                sources = await self._art.sources(
                    synced.collection_id, synced.media_type, art_type
                )
                candidates = [
                    candidate
                    for group in sources.sources.values()
                    for candidate in group
                ]
                if candidates:
                    await self._art.save(
                        synced.collection_id,
                        synced.media_type,
                        art_type,
                        SaveArtRequest(url=candidates[0].url),
                    )
        if not policy.auto_match_theme or row.youtube_id or not row.tmdb_collection_id:
            return
        async with self._access.database.read_session() as session:
            catalog = await catalog_collections(
                session, {row.tmdb_collection_id}, app_config=self._access.app_config
            )
        entry = catalog.get(row.tmdb_collection_id)
        if entry and entry.youtube_id_overturedb and self._themes.unavailable() is None:
            await self._themes.queue(
                synced.collection_id,
                SetCollectionThemeRequest(
                    media_type=synced.media_type,
                    youtube_id=entry.youtube_id_overturedb,
                ),
            )


class MemberLabel:
    """Label the members on Plex, so smart filters and users can find them."""

    name = "Member label"

    def __init__(self, *, membership: Membership) -> None:
        self._membership = membership

    def applies(self, synced: SyncedCollection) -> bool:
        return bool(synced.policy.member_label) and synced.plex and synced.on_server

    async def run(self, synced: SyncedCollection) -> None:
        label = format_member_tag(
            synced.policy.member_label or "",
            title=synced.row.title,
            group=synced.row.collection_group,
        )
        await self._membership.sync_label(
            synced.row.library_id or "",
            synced.media_type,
            label,
            {member.id or 0 for member in synced.members},
            synced.library_items,
        )


class MemberTag:
    """Tag the members in Radarr or Sonarr."""

    name = "Member tag"

    def __init__(self, *, sources: SourceResolver, effects: MemberEffects) -> None:
        self._sources = sources
        self._effects = effects

    def applies(self, synced: SyncedCollection) -> bool:
        return (
            bool(synced.policy.arr_tag)
            and self._sources.arr(synced.media_type).configured
        )

    async def run(self, synced: SyncedCollection) -> None:
        tag = format_member_tag(
            synced.policy.arr_tag or "",
            title=synced.row.title,
            group=synced.row.collection_group,
        )
        await self._effects.tag(synced.media_type, tag, synced.members)


class RequestMissing:
    """Ask Radarr or Sonarr for the titles the collection's lists hold."""

    name = "Request missing"

    def __init__(self, *, sources: SourceResolver, arr: CollectionArr) -> None:
        self._sources = sources
        self._arr = arr

    def applies(self, synced: SyncedCollection) -> bool:
        return (
            synced.policy.request_missing
            and self._sources.arr(synced.media_type).configured
            and synced.rule is not None
        )

    async def run(self, synced: SyncedCollection) -> None:
        if synced.rule is None:
            return
        await self._arr.request(
            synced.media_type,
            criteria(synced.rule),
            synced.library_items,
            synced.settings,
        )


class HomeOrder:
    """Order the library's promoted collections on Plex's Home by Home order."""

    name = "Home order"

    def __init__(self, *, access: CollectionAccess) -> None:
        self._access = access

    def applies(self, synced: SyncedCollection) -> bool:
        return synced.plex and synced.policy.home_order is not None and synced.on_server

    async def run(self, synced: SyncedCollection) -> None:
        library_id = synced.row.library_id or ""
        media_type = synced.media_type
        async with self._access.database.read_session() as session:
            repo = CollectionRepository(session)
            rows = [
                row
                for row in await repo.list_listed(media_type)
                if row.library_id == library_id and row.server_item_id is not None
            ]
            rules = {rule.collection_id: rule for rule in await repo.rules()}
            ordered: list[tuple[int, str, str]] = []
            for row in rows:
                policy = await self._access.policy(
                    session, media_type, row.collection_group, rules.get(row.id or 0)
                )
                if policy.home_order is not None and (
                    row.visible_home or row.visible_shared or row.visible_library
                ):
                    ordered.append(
                        (
                            policy.home_order,
                            row.title.casefold(),
                            row.server_item_id or "",
                        )
                    )
        await self._access.provider().order_collection_hubs(
            library_id, [server_id for _, _, server_id in sorted(ordered)]
        )


class PostSync:
    """Run every applicable step after a sync, recording the ones that fail."""

    def __init__(
        self, *, access: CollectionAccess, steps: Sequence[PostSyncStep]
    ) -> None:
        self._access = access
        self._steps = steps

    async def run(self, collection_id: int, media_type: MediaType) -> None:
        """Run what a sync does beyond membership, each step whatever the others do.

        Members are already synced, so a failed step is recorded on the rule
        and reported rather than undone.
        """
        async with self._access.database.read_session() as session:
            repo = CollectionRepository(session)
            row = await self._access.require(session, collection_id, media_type)
            rule = await repo.rule(collection_id)
            synced = SyncedCollection(
                row=row,
                rule=rule,
                policy=await self._access.policy(
                    session, media_type, row.collection_group, rule
                ),
                members=await repo.members(collection_id),
                library_items=await repo.library_items(
                    media_type, row.library_id or ""
                ),
                settings=await get_app_settings(session),
                plex=self._access.plex,
            )
        failures: list[str] = []
        for step in self._steps:
            if not step.applies(synced):
                continue
            try:
                await step.run(synced)
            except Exception as exc:
                failures.append(f"{step.name} failed: {exc!s}")
        if not failures:
            return
        message = "Members synced; " + "; ".join(failures)
        async with self._access.database.write_session() as session:
            saved = await CollectionRepository(session).rule(collection_id)
            if saved is not None:
                saved.last_error = message
                session.add(saved)
        await self._access.updated(collection_id)
        raise PublicServiceError(502, message)
