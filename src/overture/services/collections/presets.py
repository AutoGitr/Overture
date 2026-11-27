"""OvertureDB's presets, and collections exported as portable files.

An OvertureDB preset and an export share one format. Each collection and set
in one fills the create form, so what it creates is ordinary.
"""

lazy from collections.abc import Iterable
lazy from typing import Any, cast

lazy from pydantic import ValidationError

lazy from ...catalog_contract.contract import (
    preset_requires,
    preset_text,
    validate_preset,
)
lazy from ...domain import (
    ArtType,
    CollectionPosterStyle,
    FilterField,
    Integration,
    MediaType,
    PresetCategory,
)
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
    PresetListing,
    PresetPoster,
    PresetRefusal,
)
lazy from ...schemas.collections import (
    CollectionContent,
    CollectionContentPolicy,
    CollectionDetail,
    FilterGroup,
)
lazy from ...utils.art_urls import art_preview_url
lazy from ...utils.collection_fields import FIELDS
lazy from ...utils.errors import PublicServiceError
lazy from ..catalog.issue import preset_issue
lazy from ..catalog.presets import fetch_presets
lazy from .access import CollectionAccess
lazy from .groups import CollectionGroups
lazy from .reader import CollectionReader
lazy from .sources import SourceResolver

#: What a collection's detail holds as it chose it; its summary and sort title
#: are shown as its templates render them, and its order as it inherits it, so
#: they come from its templates and its rule instead.
_OWN_CONTENT = frozenset(CollectionContent.model_fields) - {
    "summary",
    "sort_title",
    "order_type",
}


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
    """List OvertureDB's presets and export portable collection files."""

    def __init__(
        self,
        *,
        access: CollectionAccess,
        sources: SourceResolver,
        reader: CollectionReader,
        groups: CollectionGroups,
    ) -> None:
        self._access = access
        self._sources = sources
        self._reader = reader
        self._groups = groups

    # The gallery

    async def gallery(self) -> PresetGallery:
        """Return OvertureDB's presets, each with what keeps it from being added.

        They come by category, in the order categories are declared, then by
        title; one this Overture cannot read comes last.
        """
        try:
            header, presets = await fetch_presets()
        except ValueError as exc:
            return PresetGallery(error=str(exc))
        categories = list(PresetCategory)
        return PresetGallery(
            generated_at=header["generated_at"],
            presets=sorted(
                (self._listing(value) for value in presets),
                key=lambda listing: (
                    categories.index(listing.preset.category)
                    if listing.preset
                    else len(categories),
                    (listing.preset.title if listing.preset else listing.id).casefold(),
                ),
            ),
        )

    def read_file(self, file: CollectionPresetFile) -> PresetListing:
        """Return a file read from disk as the gallery lists a preset."""
        return PresetListing(
            id=file.preset.id if file.preset else "file",
            preset=file.preset,
            file=file,
            setup=self._setup(file),
        )

    def _listing(self, value: object) -> PresetListing:
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
        return PresetListing(
            id=identifier,
            preset=file.preset,
            file=file,
            setup=self._setup(file),
            preview_url=art_preview_url(poster, ArtType.POSTER) if poster else None,
        )

    def _setup(self, file: CollectionPresetFile) -> list[str]:
        """What to set up for the integrations the file needs."""
        return [
            setup
            for need in preset_requires(file.model_dump(mode="json"))
            if (setup := self._sources.setup(Integration(need))) is not None
        ]

    # Exporting

    async def export(self, body: PresetExportRequest) -> PresetExport:
        """Return the chosen collections and groups as a portable file.

        A group brings its set and the collections it holds that its set does
        not make. What another install could not add is left out with why, and
        the file holds only what each collection is.
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
            text=preset_text(file.model_dump(mode="json")),
            count=len(groups) + len(collections),
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
            **policy.model_dump(include=set(CollectionContentPolicy.model_fields)),
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
        return PortableCollection(
            **detail.model_dump(include=set(_OWN_CONTENT)),
            order_type=rule.order_type,
            minimum_items=rule.minimum_items,
            smart=rule.smart,
            limit=rule.limit,
            criteria=criteria,
            art=_art(detail, warnings),
        )
