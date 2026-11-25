"""Export collections as portable files, and add such files to this install.

An OvertureDB preset and an export share one format. Adding one copies it
once: what it creates are ordinary collections, sets and groups.
"""

lazy from collections.abc import Iterable
lazy from dataclasses import dataclass, field
lazy from typing import Any, cast

lazy from pydantic import BaseModel, ValidationError

lazy from ...catalog_contract.contract import (
    PRESET_REFUSED_POLICY,
    preset_requires,
    validate_preset,
)
lazy from ...db.models.added_preset import AddedPreset
lazy from ...domain import (
    ArtType,
    CollectionPosterStyle,
    FilterField,
    Integration,
    MediaType,
)
lazy from ...repositories.collections import CollectionRepository
lazy from ...schemas.art import SaveCollectionArtRequest
lazy from ...schemas.collection_presets import (
    CollectionPresetFile,
    PortableCollection,
    PortableGroup,
    PortableSet,
    PresetArt,
    PresetExport,
    PresetExportRequest,
    PresetGallery,
    PresetImage,
    PresetImportPlan,
    PresetImportRequest,
    PresetImportResult,
    PresetListing,
    PresetPlanItem,
    PresetPoster,
    PresetRefusal,
)
lazy from ...schemas.collections import (
    CollectionCreate,
    CollectionDetail,
    CollectionGenerator,
    CollectionGroupPolicy,
    CollectionLibraryCriteria,
    CollectionOptions,
    CollectionPolicyBase,
    CollectionRuleWrite,
    FilterGroup,
)
lazy from ...utils.art_urls import art_preview_url
lazy from ...utils.collection_fields import FIELDS
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.text import spoken_list
lazy from ...utils.time import utc_now
lazy from ..art.collection_art import CollectionArtService
lazy from ..catalog.issue import preset_issue
lazy from ..catalog.presets import fetch_presets
lazy from .access import CollectionAccess
lazy from .editor import CollectionEditor, PresetSource
lazy from .groups import CollectionGroups
lazy from .reader import CollectionReader
lazy from .sources import SourceResolver

#: The policy a collection keeps in its own options rather than its rule.
_RULE_POLICY = frozenset(CollectionPolicyBase.model_fields) - frozenset(
    CollectionOptions.model_fields
)
_GROUP_EXISTS = "A group of this name exists; its settings stay as they are"
_UNCHANGED = "Unchanged since the preset was added"
_UPDATES = "Takes the preset's new criteria and settings, replacing changes made here"
_DROPPED = "No longer in the preset; it stays as it is"
_DELETED = "Deleted here since the preset added it"

type _Item = PortableGroup | PortableCollection


def _items(file: CollectionPresetFile) -> dict[str, _Item]:
    """Each group and collection of a file, by its kind and casefolded name."""
    return {
        **{f"group:{group.name.casefold()}": group for group in file.groups},
        **{
            f"collection:{collection.title.casefold()}": collection
            for collection in file.collections
        },
    }


def _key(item: _Item) -> str:
    if isinstance(item, PortableGroup):
        return f"group:{item.name.casefold()}"
    return f"collection:{item.title.casefold()}"


def _name(item: _Item) -> str:
    return item.name if isinstance(item, PortableGroup) else item.title


def preset_changes(
    earlier: CollectionPresetFile, current: CollectionPresetFile
) -> list[str]:
    """What *current* adds, changes and drops since *earlier*, by name."""
    before, after = _items(earlier), _items(current)
    return [
        *(
            f"{'Changes' if key in before else 'Adds'} {_name(item)}"
            for key, item in after.items()
            if before.get(key) != item
        ),
        *(f"Drops {_name(item)}" for key, item in before.items() if key not in after),
    ]


@dataclass(slots=True)
class _Added:
    """What an earlier version of a preset created here."""

    preset_id: str | None = None
    #: The version added; None when the preset never was, or the file is
    #: not a preset.
    file: CollectionPresetFile | None = None
    #: The collections it created, by their casefolded title in it.
    collections: dict[str, int] = field(default_factory=dict[str, int])
    #: The groups it created, their names here by their casefolded name in it.
    groups: dict[str, str] = field(default_factory=dict[str, str])

    def source(self, name: str) -> PresetSource | None:
        return (self.preset_id, name) if self.preset_id is not None else None

    def _here(self, item: _Item) -> bool:
        if isinstance(item, PortableGroup):
            return item.name.casefold() in self.groups
        return item.title.casefold() in self.collections

    def deleted(self, item: _Item) -> bool:
        """Whether the preset added *item* here and it has since been deleted."""
        return (
            self.file is not None
            and _key(item) in _items(self.file)
            and not self._here(item)
        )

    def unchanged(self, item: _Item) -> bool:
        """Whether the preset holds *item* as it did when it was added."""
        return self.file is not None and _items(self.file).get(_key(item)) == item

    def recorded(
        self, file: CollectionPresetFile, applied: set[str]
    ) -> CollectionPresetFile:
        """*file* as it now stands here, item by item.

        What the preset created here and was not updated keeps the version it
        was added at, so a skipped or refused update is offered again.
        """
        earlier = _items(self.file) if self.file is not None else {}

        def kept[T: _Item](items: list[T]) -> list[T]:
            return [
                version
                for item in items
                if (
                    version := item
                    if not self._here(item) or _key(item) in applied
                    else earlier.get(_key(item))
                )
                is not None
            ]  # pyright: ignore[reportReturnType] -- an earlier version has its kind

        return file.model_copy(
            update={"groups": kept(file.groups), "collections": kept(file.collections)}
        )

    def dropped(self, file: CollectionPresetFile) -> list[PresetPlanItem]:
        """What the preset created here that *file* no longer holds."""
        if self.file is None:
            return []
        kept = _items(file)
        return [
            PresetPlanItem(
                kind="group" if isinstance(item, PortableGroup) else "collection",
                name=_name(item),
                status="skip",
                reason=_DROPPED,
            )
            for key, item in _items(self.file).items()
            if key not in kept and self._here(item)
        ]


class _RefusedError(Exception):
    """Why a collection or group cannot be exported."""


def _require_portable(criteria: Iterable[FilterGroup]) -> None:
    for group in criteria:
        for condition in group.field_conditions():
            if not FIELDS[condition.field].portable:
                raise _RefusedError(
                    f"It tests {FIELDS[condition.field].label.lower()}, "
                    "which only this install has"
                )


def _tests_labels(criteria: Iterable[FilterGroup]) -> bool:
    return any(
        condition.field is FilterField.LABEL
        for group in criteria
        for condition in group.field_conditions()
    )


def _art(detail: CollectionDetail, warnings: list[str]) -> PresetArt | None:
    """The collection's art links; uploaded and generated art stays behind."""
    poster, background = detail.assets.poster, detail.assets.background
    if (poster.selected and poster.url is None) or (
        background.selected and background.url is None
    ):
        warnings.append(
            f"{detail.title}: uploaded and generated art stays on this install"
        )
    art = PresetArt(
        poster=PresetPoster(
            url=poster.url,
            style=poster.poster_style or CollectionPosterStyle.INDIVIDUAL,
        )
        if poster.url
        else None,
        background=PresetImage(url=background.url) if background.url else None,
    )
    return art if art.poster or art.background else None


class CollectionPresets:
    """Export and add portable collection files."""

    def __init__(
        self,
        *,
        access: CollectionAccess,
        sources: SourceResolver,
        reader: CollectionReader,
        editor: CollectionEditor,
        groups: CollectionGroups,
        art: CollectionArtService,
    ) -> None:
        self._access = access
        self._sources = sources
        self._reader = reader
        self._editor = editor
        self._groups = groups
        self._art = art

    # The gallery

    async def gallery(self) -> PresetGallery:
        """Return OvertureDB's presets, each with what keeps it from being added."""
        try:
            header, presets = await fetch_presets()
        except ValueError as exc:
            return PresetGallery(error=str(exc))
        async with self._access.database.read_session() as session:
            added = await CollectionRepository(session).added_presets()
        return PresetGallery(
            generated_at=header["generated_at"],
            presets=[self._listing(value, added) for value in presets],
        )

    def _listing(self, value: object, added: dict[str, AddedPreset]) -> PresetListing:
        """Read one preset; one this Overture cannot read is listed as such."""
        record = cast("dict[str, Any]", value) if isinstance(value, dict) else {}
        metadata: object = record.get("preset")
        identifier = (
            str(cast("dict[str, Any]", metadata).get("id", "unknown"))
            if isinstance(metadata, dict)
            else "unknown"
        )
        try:
            file = CollectionPresetFile.model_validate(
                validate_preset(record, published=True)
            )
        except ValueError, ValidationError:
            return PresetListing(
                id=identifier, problem="Needs a newer version of Overture"
            )
        poster = next(
            (
                collection.art.poster.url
                for collection in file.collections
                if collection.art and collection.art.poster
            ),
            None,
        )
        record = added.get(identifier)
        return PresetListing(
            id=identifier,
            preset=file.preset,
            file=file,
            unavailable=self._unavailable(file),
            preview_url=art_preview_url(poster, ArtType.POSTER) if poster else None,
            added_at=record.added_at if record else None,
            changes=preset_changes(
                CollectionPresetFile.model_validate(record.file), file
            )
            if record
            else [],
        )

    def _unavailable(self, file: CollectionPresetFile) -> list[Integration]:
        """The integrations the file needs that are not set up."""
        return [
            integration
            for need in preset_requires(file.model_dump(mode="json"))
            if not self._sources.configured(integration := Integration(need))
        ]

    # Exporting

    async def export(self, body: PresetExportRequest) -> PresetExport:
        """Return the chosen collections and groups as a portable file.

        A group brings its set and the collections it holds that its set does
        not make. What another install could not add is left out with why.
        """
        refused: list[PresetRefusal] = []
        warnings: list[str] = []
        known = {name.casefold(): name for name in await self._groups.names()}
        groups: list[PortableGroup] = []
        for requested in body.groups or []:
            name = known.get(requested.strip().casefold())
            if name is None:
                refused.append(PresetRefusal(title=requested, reason="No such group"))
                continue
            try:
                groups.append(await self._export_group(name))
            except _RefusedError as exc:
                refused.append(PresetRefusal(title=name, reason=str(exc)))
        chosen = set(body.collection_ids or [])
        names = {group.name.casefold() for group in groups}
        collections: list[PortableCollection] = []
        for row in await self._reader.listed():
            in_group = (
                row.collection_group is not None
                and row.collection_group.casefold() in names
                and row.generated_value is None
            )
            if row.id not in chosen and not in_group:
                continue
            try:
                if row.generated_value is not None:
                    raise _RefusedError("Its group's set makes it; export the group")
                detail = await self._reader.get(row.id)
                collections.append(await self._export_collection(detail, warnings))
            except _RefusedError as exc:
                refused.append(PresetRefusal(title=row.title, reason=str(exc)))
        if not groups and not collections:
            return PresetExport(refused=refused, warnings=warnings)
        try:
            file = CollectionPresetFile(
                preset=body.preset, groups=groups, collections=collections
            )
        except ValueError as exc:
            raise PublicServiceError(422, str(exc)) from exc
        return PresetExport(
            file=file,
            refused=refused,
            warnings=warnings,
            issue=preset_issue(body.preset),
        )

    async def _export_group(self, name: str) -> PortableGroup:
        policy = await self._groups.policy(name)
        portable_set: PortableSet | None = None
        if (generator := policy.generator) is not None:
            _require_portable(
                [
                    generator.criteria,
                    *(value.criteria for value in generator.custom_values),
                ]
            )
            types = await self._access.library_types(generator.library_ids)
            portable_set = PortableSet(
                **generator.model_dump(exclude={"library_ids"}),
                media_types=sorted(set(types.values())),
            )
        return PortableGroup(
            **policy.model_dump(exclude={"generator"}),
            name=name,
            generator=portable_set,
        )

    async def _export_collection(
        self, detail: CollectionDetail, warnings: list[str]
    ) -> PortableCollection:
        rule = detail.rule
        if rule is None:
            raise _RefusedError("Overture does not manage it")
        types = await self._access.library_types(
            library.library_id for library in rule.libraries
        )
        criteria: dict[MediaType, FilterGroup] = {}
        for library in rule.libraries:
            media_type = types[library.library_id]
            if criteria.setdefault(media_type, library.criteria) != library.criteria:
                raise _RefusedError(
                    f"Its {media_type.value} libraries select different titles"
                )
        _require_portable(criteria.values())
        if _tests_labels(criteria.values()):
            warnings.append(f"{detail.title}: tests labels another install may lack")
        if any(getattr(rule, key) is not None for key in PRESET_REFUSED_POLICY):
            warnings.append(
                f"{detail.title}: requests titles or writes labels or tags, "
                "which OvertureDB presets leave to the person adding them"
            )
        return PortableCollection(
            **detail.model_dump(include=set(CollectionOptions.model_fields)),
            policy=CollectionPolicyBase(**rule.model_dump(include=set(_RULE_POLICY))),
            smart=rule.smart,
            limit=rule.limit,
            criteria=criteria,
            art=_art(detail, warnings),
        )

    # Adding

    async def plan(self, body: PresetImportRequest) -> PresetImportPlan:
        """Return what adding the file would do, item by item, saving nothing.

        Adding a newer version of a preset added before updates what it
        created, where the preset changed it, and adds what is new.
        """
        added = await self._added(body.file)
        items = [
            *[await self._plan_group(group, body, added) for group in body.file.groups],
            *[
                await self._plan_collection(collection, body, added)
                for collection in body.file.collections
            ],
            *added.dropped(body.file),
        ]
        return PresetImportPlan(items=items, warnings=self._warnings(body.file))

    async def _added(self, file: CollectionPresetFile) -> _Added:
        """What an earlier version of the file's preset created here."""
        if file.preset is None:
            return _Added()
        async with self._access.database.read_session() as session:
            repo = CollectionRepository(session)
            record = (await repo.added_presets()).get(file.preset.id)
            return _Added(
                preset_id=file.preset.id,
                file=CollectionPresetFile.model_validate(record.file)
                if record
                else None,
                collections=await repo.preset_collections(file.preset.id),
                groups=await repo.preset_groups(file.preset.id),
            )

    def _warnings(self, file: CollectionPresetFile) -> list[str]:
        warnings: list[str] = []
        if missing := self._unavailable(file):
            names = spoken_list(sorted(need.value for need in missing))
            warnings.append(f"Set up {names} for every collection to find its titles")
        if any(
            getattr(item, key) is not None
            for item in (
                *file.groups,
                *(collection.policy for collection in file.collections),
            )
            for key in PRESET_REFUSED_POLICY
        ):
            warnings.append(
                "Some collections request missing titles, or write labels or tags"
            )
        return warnings

    def _skipped(self, name: str, body: PresetImportRequest) -> bool:
        return name.casefold() in {skipped.casefold() for skipped in body.skip}

    async def _plan_group(
        self, group: PortableGroup, body: PresetImportRequest, added: _Added
    ) -> PresetPlanItem:
        item = PresetPlanItem(kind="group", name=group.name, status="add")
        here = added.groups.get(group.name.casefold())
        if here is not None:
            if added.unchanged(group):
                return item.model_copy(update={"status": "skip", "reason": _UNCHANGED})
            item = item.model_copy(update={"status": "update", "reason": _UPDATES})
        elif added.deleted(group):
            item = item.model_copy(update={"reason": _DELETED, "chosen": False})
        if self._skipped(group.name, body):
            return item.model_copy(update={"status": "skip", "reason": None})
        if here is None and group.name.strip().casefold() in {
            name.casefold() for name in await self._groups.names()
        }:
            return item.model_copy(update={"status": "skip", "reason": _GROUP_EXISTS})
        try:
            await self._groups.check_policy(
                here or group.name, await self._group_policy(group, body, here)
            )
        except PublicServiceError as exc:
            return item.model_copy(update={"status": "refused", "reason": exc.message})
        return item

    async def _plan_collection(
        self, collection: PortableCollection, body: PresetImportRequest, added: _Added
    ) -> PresetPlanItem:
        item = PresetPlanItem(kind="collection", name=collection.title, status="add")
        here = added.collections.get(collection.title.casefold())
        if here is not None:
            if added.unchanged(collection):
                return item.model_copy(update={"status": "skip", "reason": _UNCHANGED})
            item = item.model_copy(update={"status": "update", "reason": _UPDATES})
        elif added.deleted(collection):
            item = item.model_copy(update={"reason": _DELETED, "chosen": False})
        if self._skipped(collection.title, body):
            return item.model_copy(update={"status": "skip", "reason": None})
        try:
            await self._editor.check(
                await self._collection_create(collection, body, here), replacing=here
            )
        except PublicServiceError as exc:
            return item.model_copy(update={"status": "refused", "reason": exc.message})
        return item

    async def import_(self, body: PresetImportRequest) -> PresetImportResult:
        """Add the file's groups, then its collections, each saved on its own.

        Something refused leaves the rest to be added; art a collection could
        not take is noted on it. What is recorded of the preset is what now
        stands here, so an update skipped or refused is offered again.
        """
        added = await self._added(body.file)
        plan = await self.plan(body)
        groups = {group.name: group for group in body.file.groups}
        collections = {
            collection.title: collection for collection in body.file.collections
        }
        items: list[PresetPlanItem] = []
        created: list[int] = []
        applied: set[str] = set()
        for item in plan.items:
            if item.status not in {"add", "update"}:
                items.append(item)
                continue
            try:
                if item.kind == "group":
                    await self._save_group(groups[item.name], body, added)
                    applied.add(_key(groups[item.name]))
                    items.append(item)
                    continue
                collection = collections[item.name]
                here = added.collections.get(collection.title.casefold())
                if here is not None:
                    await self._update_collection(here, collection, body)
                    applied.add(_key(collection))
                    items.append(item)
                    continue
                detail = await self._editor.create(
                    await self._collection_create(collection, body, None),
                    preset=added.source(collection.title),
                )
            except PublicServiceError as exc:
                items.append(
                    item.model_copy(update={"status": "refused", "reason": exc.message})
                )
                continue
            created.append(detail.id)
            applied.add(_key(collection))
            items.append(
                item.model_copy(
                    update={"reason": await self._apply_art(detail.id, collection.art)}
                )
            )
        if added.preset_id is not None:
            await self._record(added.preset_id, added.recorded(body.file, applied))
        return PresetImportResult(items=items, collection_ids=created)

    async def _save_group(
        self, group: PortableGroup, body: PresetImportRequest, added: _Added
    ) -> None:
        here = added.groups.get(group.name.casefold())
        await self._groups.save_policy(
            here or group.name,
            await self._group_policy(group, body, here),
            new_set=here is None and group.generator is not None,
            preset=added.source(group.name),
        )

    async def _update_collection(
        self,
        collection_id: int,
        collection: PortableCollection,
        body: PresetImportRequest,
    ) -> None:
        """Give a collection the preset's criteria and settings, keeping where it is."""
        create = await self._collection_create(collection, body, collection_id)
        await self._editor.update(
            collection_id,
            CollectionOptions(
                **create.model_dump(include=set(CollectionOptions.model_fields))
            ),
        )
        await self._editor.save_rule(collection_id, create.rule)

    async def _record(self, preset_id: str, file: CollectionPresetFile) -> None:
        async with self._access.database.write_session() as session:
            await session.merge(
                AddedPreset(
                    id=preset_id, file=file.model_dump(mode="json"), added_at=utc_now()
                )
            )

    async def _current_libraries(
        self, library_ids: Iterable[str]
    ) -> dict[MediaType, list[str]]:
        types = await self._access.library_types(library_ids)
        libraries: dict[MediaType, list[str]] = {}
        for library_id, media_type in types.items():
            libraries.setdefault(media_type, []).append(library_id)
        return libraries

    async def _group_policy(
        self, group: PortableGroup, body: PresetImportRequest, here: str | None
    ) -> CollectionGroupPolicy:
        """The group as this install saves it.

        A set takes the chosen libraries, or, when it updates a group the
        preset added, the libraries that group's set has.
        """
        generator = group.generator
        kept: dict[MediaType, list[str]] = {}
        if here is not None and (
            current := (await self._groups.policy(here)).generator
        ):
            kept = await self._current_libraries(current.library_ids)
        return _built(
            CollectionGroupPolicy,
            **group.model_dump(exclude={"name", "generator"}),
            generator=CollectionGenerator(
                **generator.model_dump(exclude={"media_types"}),
                library_ids=[
                    library
                    for media_type in generator.media_types
                    for library in kept.get(media_type) or _libraries(body, media_type)
                ],
            )
            if generator is not None
            else None,
        )

    async def _collection_create(
        self,
        collection: PortableCollection,
        body: PresetImportRequest,
        here: int | None,
    ) -> CollectionCreate:
        """The collection as this install creates it, in the chosen libraries.

        When it updates a collection the preset added, that collection keeps
        its title, group and libraries.
        """
        options = collection.model_dump(
            include=set(CollectionOptions.model_fields), exclude_unset=True
        )
        kept: dict[MediaType, list[str]] = {}
        if here is not None:
            detail = await self._reader.get(here)
            options |= {
                "title": detail.title,
                "collection_group": detail.collection_group,
            }
            if detail.rule is not None:
                kept = await self._current_libraries(
                    library.library_id for library in detail.rule.libraries
                )
        return _built(
            CollectionCreate,
            **options,
            rule=_built(
                CollectionRuleWrite,
                **collection.policy.model_dump(exclude_unset=True),
                libraries=[
                    CollectionLibraryCriteria(library_id=library, criteria=criteria)
                    for media_type, criteria in collection.criteria.items()
                    for library in kept.get(media_type) or _libraries(body, media_type)
                ],
                smart=collection.smart,
                limit=collection.limit,
            ),
        )

    async def _apply_art(self, collection_id: int, art: PresetArt | None) -> str | None:
        """Choose a new collection's art; return why it was not, if it was not."""
        if art is None:
            return None
        choices = [
            (
                ArtType.POSTER,
                SaveCollectionArtRequest(
                    url=art.poster.url, poster_style=art.poster.style
                ),
            )
            if art.poster
            else None,
            (ArtType.BACKGROUND, SaveCollectionArtRequest(url=art.background.url))
            if art.background
            else None,
        ]
        for choice in choices:
            if choice is None:
                continue
            art_type, request = choice
            try:
                await self._art.save(collection_id, art_type, request)
            except PublicServiceError as exc:
                return f"Its {art_type.value} was not set: {exc.message}"
        return None


def _built[T: BaseModel](model: type[T], **fields: object) -> T:
    """Build *model*, refusing what its rules refuse as a choice to correct.

    A file may combine choices its parts each allow and the whole does not,
    such as a smart collection in a custom order.
    """
    try:
        return model(**fields)
    except ValidationError as exc:
        reason = str(exc.errors()[0]["msg"]).removeprefix("Value error, ")
        raise PublicServiceError(422, reason) from exc


def _libraries(body: PresetImportRequest, media_type: MediaType) -> list[str]:
    libraries = body.libraries.get(media_type)
    if not libraries:
        raise PublicServiceError(422, f"Choose a library for {media_type.plural}")
    return libraries
