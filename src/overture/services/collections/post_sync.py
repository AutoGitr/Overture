"""What a sync does beyond membership, as independent steps.

Each step decides from the synced collection whether it applies, so a new
step is a new :class:`PostSyncStep`, not a change to the sync itself.
"""

lazy from collections.abc import Mapping, Sequence
lazy from dataclasses import dataclass
lazy from typing import Protocol

lazy from ...db.art_slots import read_art_slot, saved_art
lazy from ...db.models.collection_rule import CollectionRule
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.settings import AppSettings, get_app_settings
lazy from ...domain import ArtStyle, ArtType, CollectionKind, MediaType
lazy from ...repositories.collections import CollectionRepository
lazy from ...schemas.art import SaveArtRequest
lazy from ...schemas.collections import SetCollectionThemeRequest
lazy from ...utils.collection_formats import format_arr_tag, format_member_tag
lazy from ...utils.errors import PublicServiceError
lazy from ..art.collection_art import CollectionArtService
lazy from .access import CollectionAccess
lazy from .arr_requests import CollectionArr
lazy from .member_effects import MemberEffects
lazy from .membership import Membership
lazy from .policy import CollectionPolicy, resolve_policy
lazy from .reader import catalog_collections
lazy from .rules import criteria_of
lazy from .sources import SourceResolver
lazy from .themes import CollectionThemes

#: The style a poster drawn automatically takes.
AUTOMATIC_ART_STYLE = ArtStyle.DARK


@dataclass(slots=True, frozen=True)
class SyncedCollection:
    """A collection whose members were just synced, with what its steps read."""

    row: MediaCollection
    rule: CollectionRule | None
    policy: CollectionPolicy
    members: list[MediaItem]
    library_items: Mapping[str, list[MediaItem]]
    settings: AppSettings
    plex: bool
    #: The sync made a server copy the collection's saved assets are not on yet.
    new_copies: bool = False

    @property
    def collection_id(self) -> int:
        return self.row.id or 0

    @property
    def on_server(self) -> bool:
        return bool(self.row.server_ids)

    def members_of(self, media_type: MediaType) -> list[MediaItem]:
        return [item for item in self.members if item.media_type is media_type]


class PostSyncStep(Protocol):
    """One thing a sync does after membership, whatever the other steps do."""

    @property
    def name(self) -> str: ...

    def applies(self, synced: SyncedCollection) -> bool: ...

    async def run(self, synced: SyncedCollection) -> None: ...


class AutoAssets:
    """Match or draw art, and match the catalog's theme.

    Art comes from the franchise or a listed person; a poster still missing is
    drawn from the title when the policy says so, and art drawn earlier is
    drawn again when the title or group it shows changed.
    """

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
        collection_id = synced.collection_id
        for art_type in (ArtType.POSTER, ArtType.BACKGROUND):
            slot = read_art_slot(row, art_type)
            saved = saved_art(slot)
            if slot.generated_style is not None:
                await self._art.redraw(
                    collection_id, art_type, resend=synced.new_copies
                )
            elif saved is not None:
                if synced.new_copies and saved.url:
                    await self._art.save(
                        collection_id, art_type, SaveArtRequest(url=saved.url)
                    )
                elif synced.new_copies:
                    await self._art.reupload(collection_id, art_type)
            elif policy.auto_match_art and (
                url := await self._matched(collection_id, art_type)
            ):
                await self._art.save(collection_id, art_type, SaveArtRequest(url=url))
            elif art_type is ArtType.POSTER and (
                policy.auto_generate_art or row.kind is CollectionKind.SEPARATOR
            ):
                await self._art.save(
                    collection_id,
                    art_type,
                    SaveArtRequest(generated=AUTOMATIC_ART_STYLE),
                )
        await self._theme(synced)

    async def _matched(self, collection_id: int, art_type: ArtType) -> str | None:
        """The best art a source offers for the slot."""
        sources = await self._art.found(collection_id, art_type)
        return next(
            (
                candidate.url
                for group in sources.sources.values()
                for candidate in group
            ),
            None,
        )

    async def _theme(self, synced: SyncedCollection) -> None:
        row, policy = synced.row, synced.policy
        if row.youtube_id:
            if synced.new_copies and self._themes.unavailable() is None:
                await self._themes.queue(
                    synced.collection_id,
                    SetCollectionThemeRequest(youtube_id=row.youtube_id),
                )
            return
        if not policy.auto_match_theme or not row.tmdb_collection_id:
            return
        async with self._access.database.read_session() as session:
            catalog = await catalog_collections(
                session, {row.tmdb_collection_id}, app_config=self._access.app_config
            )
        entry = catalog.get(row.tmdb_collection_id)
        if entry and entry.youtube_id_overturedb and self._themes.unavailable() is None:
            await self._themes.queue(
                synced.collection_id,
                SetCollectionThemeRequest(youtube_id=entry.youtube_id_overturedb),
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
            group=synced.row.group_name,
        )
        for part in synced.row.libraries:
            await self._membership.sync_label(
                part.library_id,
                part.media_type,
                label,
                {
                    member.id or 0
                    for member in synced.members
                    if member.library_id == part.library_id
                },
                synced.library_items[part.library_id],
            )


class MemberTag:
    """Tag the members in Radarr or Sonarr.

    Collections whose tags render alike share the tag, so it marks the members
    of all of them and none takes it from another's members.
    """

    name = "Member tag"

    def __init__(
        self,
        *,
        access: CollectionAccess,
        sources: SourceResolver,
        effects: MemberEffects,
    ) -> None:
        self._access = access
        self._sources = sources
        self._effects = effects

    def applies(self, synced: SyncedCollection) -> bool:
        return bool(synced.policy.arr_tag) and any(
            self._sources.arr(media_type).configured
            for media_type in synced.row.media_types
        )

    async def run(self, synced: SyncedCollection) -> None:
        tag = _arr_tag(synced.row, synced.policy.arr_tag or "")
        sharing = await self._sharing_members(synced.collection_id, tag)
        for media_type in synced.row.media_types:
            if self._sources.arr(media_type).configured:
                await self._effects.tag(
                    media_type,
                    tag,
                    [
                        *synced.members_of(media_type),
                        *(item for item in sharing if item.media_type is media_type),
                    ],
                )

    async def _sharing_members(self, collection_id: int, tag: str) -> list[MediaItem]:
        """The stored members of the other managed collections with *tag*."""
        server = self._access.server_type
        async with self._access.database.read_session() as session:
            repo = CollectionRepository(session)
            defaults = await get_app_settings(session)
            rules = {rule.collection_id: rule for rule in await repo.rules()}
            members: list[MediaItem] = []
            for row in await repo.list_listed():
                rule = rules.get(row.id or 0)
                if (
                    row.id == collection_id
                    or rule is None
                    or row.server_type is not server
                ):
                    continue
                template = resolve_policy(defaults, row.group, rule).arr_tag
                if template and _arr_tag(row, template) == tag:
                    members.extend(await repo.members(row.id or 0))
        return members


def _arr_tag(row: MediaCollection, template: str) -> str:
    return format_arr_tag(template, title=row.title, group=row.group_name)


class RequestMissing:
    """Ask Radarr or Sonarr for the titles the collection's lists hold."""

    name = "Request missing"

    def __init__(self, *, sources: SourceResolver, arr: CollectionArr) -> None:
        self._sources = sources
        self._arr = arr

    def applies(self, synced: SyncedCollection) -> bool:
        return (
            synced.policy.request_missing
            and synced.rule is not None
            and any(
                self._sources.arr(media_type).configured
                for media_type in synced.row.media_types
            )
        )

    async def run(self, synced: SyncedCollection) -> None:
        for part in synced.row.libraries:
            if self._sources.arr(part.media_type).configured:
                await self._arr.request(
                    part.media_type,
                    criteria_of(part),
                    synced.library_items[part.library_id],
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
        for part in synced.row.libraries:
            await self._order_library(part.library_id)

    async def _order_library(self, library_id: str) -> None:
        async with self._access.database.read_session() as session:
            repo = CollectionRepository(session)
            rules = {rule.collection_id: rule for rule in await repo.rules()}
            ordered: list[tuple[int, str, str]] = []
            for row in await repo.list_listed():
                held = next(
                    (
                        part.server_item_id
                        for part in row.libraries
                        if part.library_id == library_id and part.server_item_id
                    ),
                    None,
                )
                if held is None:
                    continue
                policy = await self._access.policy(
                    session, row.group, rules.get(row.id or 0)
                )
                if policy.home_order is not None and (
                    row.visible_home or row.visible_shared or row.visible_library
                ):
                    ordered.append((policy.home_order, row.title.casefold(), held))
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

    async def run(self, collection_id: int, *, new_copies: bool = False) -> None:
        """Run what a sync does beyond membership, each step whatever the others do.

        Members are already synced, so a failed step is recorded on the rule
        and reported rather than undone.
        """
        async with self._access.database.read_session() as session:
            repo = CollectionRepository(session)
            row = await self._access.require(session, collection_id)
            rule = await repo.rule(collection_id)
            synced = SyncedCollection(
                row=row,
                rule=rule,
                policy=await self._access.policy(session, row.group, rule),
                members=await repo.members(collection_id),
                library_items={
                    part.library_id: await repo.library_items(
                        part.media_type, part.library_id
                    )
                    for part in row.libraries
                },
                settings=await get_app_settings(session),
                plex=self._access.plex,
                new_copies=new_copies,
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
