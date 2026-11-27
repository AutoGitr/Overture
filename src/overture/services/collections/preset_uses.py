"""The OvertureDB preset items collections and sets were saved from, and their updates.

Saving a preset's collection or set records the item as OvertureDB published
it. OvertureDB's current item is compared with that record, so a change it
makes shows as the parts it changed, and taking it applies those parts alone:
whatever the person changed elsewhere stays theirs.
"""

lazy from collections.abc import Mapping
lazy from typing import Any

lazy from sqlalchemy import ColumnElement
lazy from sqlmodel import col, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...db.models.collection_group import CollectionGroup
lazy from ...db.models.preset_use import PresetUse
lazy from ...repositories.collections import CollectionRepository
lazy from ...schemas.collection_presets import (
    CollectionPresetFile,
    PortableCollection,
    PortableGroup,
    PresetListing,
    PresetSubject,
    PresetUseCreate,
    PresetUseRead,
    PresetUseReview,
    PresetUses,
)
lazy from ...schemas.collections import (
    CollectionContent,
    CollectionContentPolicy,
    CollectionGenerator,
    CollectionLibraryCriteria,
    CollectionRuleWrite,
)
lazy from ...utils.errors import PublicServiceError
lazy from .access import CollectionAccess
lazy from .display import saved_options
lazy from .editor import CollectionEditor
lazy from .groups import CollectionGroups
lazy from .presets import CollectionPresets
lazy from .rules import rule_read

#: What a preset item's parts are called when OvertureDB changes them.
_PARTS: Mapping[str, str] = {
    "criteria": "criteria",
    "generator": "what the set makes",
    "minimum_items": "minimum",
    "smart": "smart",
    "limit": "limit",
    "order_type": "order",
    "sort_title": "sort title",
    "sort_title_format": "sort title",
    "summary": "summary",
    "summary_format": "summary",
    "tmdb_collection_id": "TMDB collection",
    "active_start_mmdd": "active dates",
    "active_end_mmdd": "active dates",
    "delete_when_inactive": "active dates",
}
#: A collection's options a preset decides, beside its rule.
_OPTIONS = frozenset(CollectionContent.model_fields) - {"title", "collection_group"}
#: A collection's rule fields a preset decides, beside its criteria.
_RULE = frozenset({"minimum_items", "smart", "limit"})


def _changed(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    """The parts of a preset item that differ, as the person reads them."""
    return [
        key
        for key in _PARTS
        if key in before.keys() | after.keys() and before.get(key) != after.get(key)
    ]


def _item(
    listing: PresetListing | None, name: str, *, group: bool
) -> PortableCollection | PortableGroup | None:
    """The preset's set (a *group*) or collection of *name*, if OvertureDB has it."""
    file: CollectionPresetFile | None = listing.file if listing else None
    if file is None:
        return None
    if group:
        return next((row for row in file.groups if row.name == name), None)
    return next((row for row in file.collections if row.title == name), None)


class PresetUseTracker:
    """Record the preset items collections and sets came from, and their updates."""

    def __init__(
        self,
        *,
        access: CollectionAccess,
        presets: CollectionPresets,
        editor: CollectionEditor,
        groups: CollectionGroups,
    ) -> None:
        self._access = access
        self._presets = presets
        self._editor = editor
        self._groups = groups

    async def list(self) -> PresetUses:
        """Return every use, each with what OvertureDB has changed in its item since."""
        async with self._access.database.read_session() as session:
            rows = list((await session.exec(select(PresetUse))).all())
            names = await self._group_names(session, rows)
        if not rows:
            return PresetUses()
        gallery = await self._presets.gallery()
        listings = {listing.id: listing for listing in gallery.presets}
        uses = [
            self._read(row, names, listings.get(row.preset_id), known=not gallery.error)
            for row in rows
        ]
        return PresetUses(uses=uses, error=gallery.error)

    async def record(self, body: PresetUseCreate) -> PresetUseRead:
        """Keep the item a collection or set was just saved from, as OvertureDB has it.

        Raises:
            PublicServiceError: 404 for a collection, group or preset item that
                does not exist; 502 when OvertureDB's presets cannot be read.
        """
        listing = await self._listing(body.preset_id)
        current = _item(listing, body.item, group=body.group is not None)
        if current is None:
            raise PublicServiceError(404, f"OvertureDB's preset has no {body.item}")
        async with self._access.database.write_session() as session:
            owner = await self._owner(session, body)
            row = (await session.exec(select(PresetUse).where(owner))).first()
            if row is None:
                row = PresetUse(preset_id=body.preset_id, item=body.item)
                if body.collection_id is not None:
                    row.collection_id = body.collection_id
                else:
                    row.group_id = await self._group_id(session, body.group or "")
            row.preset_id, row.item = body.preset_id, body.item
            row.definition = current.model_dump(mode="json")
            session.add(row)
        return PresetUseRead(
            **body.model_dump(),
            preset_title=listing.preset.title if listing and listing.preset else None,
        )

    async def review(self, body: PresetUseReview) -> PresetUseRead | None:
        """Take OvertureDB's changes to the item, or keep what was saved.

        Either way the current item becomes the one compared from now on. A
        use whose item OvertureDB no longer publishes stops being tracked, and
        ``None`` says so.

        Raises:
            PublicServiceError: 404 for a collection or group saved from no
                preset; 502 when OvertureDB's presets cannot be read.
        """
        async with self._access.database.read_session() as session:
            row = (
                await session.exec(
                    select(PresetUse).where(await self._owner(session, body))
                )
            ).first()
        if row is None:
            raise PublicServiceError(404, "It was not saved from a preset")
        listing = await self._listing(row.preset_id)
        current = _item(listing, row.item, group=row.group_id is not None)
        if current is None:
            async with self._access.database.write_session() as session:
                stored = await session.get(PresetUse, row.id)
                if stored is not None:
                    await session.delete(stored)
            return None
        after = current.model_dump(mode="json")
        changed = _changed(row.definition, after)
        if body.take and changed:
            if isinstance(current, PortableGroup):
                await self._take_group(body.group or "", current, changed)
            else:
                await self._take_collection(body.collection_id or 0, current, changed)
        async with self._access.database.write_session() as session:
            stored = await session.get(PresetUse, row.id)
            if stored is not None:
                stored.definition = after
                session.add(stored)
        return PresetUseRead(
            **body.model_dump(exclude={"take"}),
            preset_id=row.preset_id,
            item=row.item,
            preset_title=listing.preset.title if listing and listing.preset else None,
        )

    async def _take_collection(
        self, collection_id: int, item: PortableCollection, changed: list[str]
    ) -> None:
        """Apply the item's changed parts to the collection; the rest stays."""
        options = {key: getattr(item, key) for key in changed if key in _OPTIONS}
        if options:
            async with self._access.database.read_session() as session:
                row = await self._access.require_managed(session, collection_id)
            await self._editor.update(
                collection_id, saved_options(row, row.rule).model_copy(update=options)
            )
        rule = {key: getattr(item, key) for key in changed if key in _RULE}
        if not rule and "criteria" not in changed:
            return
        async with self._access.database.read_session() as session:
            row = await self._access.require_managed(session, collection_id)
            saved = rule_read(row.rule, row)
        if saved is None:
            return
        if "criteria" in changed:
            types = await self._access.library_types(
                library.library_id for library in saved.libraries
            )
            rule["libraries"] = [
                CollectionLibraryCriteria(
                    library_id=library.library_id,
                    criteria=item.criteria.get(
                        types[library.library_id], library.criteria
                    ),
                )
                for library in saved.libraries
            ]
        await self._editor.save_rule(
            collection_id,
            CollectionRuleWrite(
                **saved.model_dump(include=set(CollectionRuleWrite.model_fields)),
            ).model_copy(update=rule),
        )

    async def _take_group(
        self, name: str, item: PortableGroup, changed: list[str]
    ) -> None:
        """Apply the item's changed parts to the group and its set; the rest stays."""
        policy = await self._groups.policy(name)
        update: dict[str, Any] = {
            key: getattr(item, key)
            for key in changed
            if key in CollectionContentPolicy.model_fields
        }
        if "generator" in changed and item.generator and policy.generator:
            update["generator"] = CollectionGenerator(
                **item.generator.model_dump(exclude={"media_types"}),
                library_ids=policy.generator.library_ids,
            )
        if update:
            await self._groups.save_policy(name, policy.model_copy(update=update))

    async def _listing(self, preset_id: str) -> PresetListing | None:
        gallery = await self._presets.gallery()
        if gallery.error:
            raise PublicServiceError(502, gallery.error)
        return next(
            (listing for listing in gallery.presets if listing.id == preset_id), None
        )

    @staticmethod
    def _read(
        row: PresetUse,
        names: Mapping[int, str],
        listing: PresetListing | None,
        *,
        known: bool,
    ) -> PresetUseRead:
        """A use as it reads: *known* says whether OvertureDB's presets were read."""
        current = (
            _item(listing, row.item, group=row.group_id is not None) if known else None
        )
        return PresetUseRead(
            preset_id=row.preset_id,
            item=row.item,
            collection_id=row.collection_id,
            group=names.get(row.group_id or 0),
            preset_title=listing.preset.title if listing and listing.preset else None,
            changes=list(
                dict.fromkeys(
                    _PARTS[key]
                    for key in _changed(row.definition, current.model_dump(mode="json"))
                )
            )
            if current
            else [],
            gone=known and current is None,
        )

    async def _owner(
        self, session: AsyncSession, subject: PresetSubject
    ) -> ColumnElement[bool]:
        """The condition naming the use of *subject*'s collection or group.

        Raises:
            PublicServiceError: 404 for a collection or group that does not exist.
        """
        if subject.collection_id is not None:
            await self._access.require_managed(session, subject.collection_id)
            return col(PresetUse.collection_id) == subject.collection_id
        return col(PresetUse.group_id) == await self._group_id(
            session, subject.group or ""
        )

    @staticmethod
    async def _group_id(session: AsyncSession, name: str) -> int:
        group = await CollectionRepository(session).group(name.strip())
        if group is None or group.id is None:
            raise PublicServiceError(404, "Collection group not found")
        return group.id

    @staticmethod
    async def _group_names(
        session: AsyncSession, rows: list[PresetUse]
    ) -> dict[int, str]:
        ids = [row.group_id for row in rows if row.group_id is not None]
        if not ids:
            return {}
        groups = await session.exec(
            select(CollectionGroup).where(col(CollectionGroup.id).in_(ids))
        )
        return {group.id: group.name for group in groups.all() if group.id is not None}
