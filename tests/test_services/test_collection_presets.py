"""Portable collection files: the gallery, files read from disk, and exports.

Each collection and set of a file fills the create form, which saves it as any
other; these tests save every OvertureDB preset the way the form sends it.
"""

lazy import os
lazy from pathlib import Path
lazy from typing import Any
lazy from unittest.mock import AsyncMock, patch

lazy import pytest

lazy from overture.domain import (
    FilterField,
    FilterOperator,
    Integration,
    MediaType,
    PresetCategory,
    SetDimension,
    SourceType,
)
lazy from overture.schemas.collection_presets import (
    CollectionPresetFile,
    PortableCollection,
    PortableGroup,
    PortableSet,
    PresetArt,
    PresetExportRequest,
    PresetImage,
    PresetMetadata,
    PresetPoster,
)
lazy from overture.schemas.collections import (
    CollectionCreate,
    CollectionGenerator,
    CollectionGroupPolicy,
    CollectionLibraryCriteria,
    CollectionOptions,
    CollectionRuleWrite,
    FilterGroup,
)
lazy from overture.services.collections.sources import source_integration
lazy from tests.collection_helpers import library_rule
lazy from tests.sync_helpers import RecordedReport
lazy from tests.test_services import test_collection_management as management
lazy from tests.test_services.test_collection_management import (
    Manager,
    where,
)

#: The collections service of the management tests, with the TMDB and MDBList
#: keys its sources need; pytest finds fixtures by their name in the module.
app_config = management.app_config
manager = management.manager

ROOT = Path(__file__).resolve().parents[2]
OVERTUREDB = Path(os.environ.get("OVERTUREDB_DIR", ROOT.parent / "OvertureDB"))
POSTER = "https://image.tmdb.org/t/p/original/poster.jpg"
BACKGROUND = "https://image.tmdb.org/t/p/original/background.jpg"
ACTION = where(FilterField.GENRE, FilterOperator.IS, "Action")
#: The Plex libraries of the management tests, by the media type each holds.
LIBRARIES = {MediaType.MOVIE: "1:movies", MediaType.SHOW: "1:shows"}


def holidays(**changes: Any) -> CollectionPresetFile:
    """A file adding a seasonal collection and a set of decades."""
    fields: dict[str, Any] = {
        "preset": PresetMetadata(
            id="holidays",
            title="Holidays",
            description="Holiday titles.",
            category=PresetCategory.SEASONAL,
            media_types=[MediaType.MOVIE],
        ),
        "groups": [
            PortableGroup(
                name="Decades",
                minimum_items=1,
                generator=PortableSet(
                    dimension=SetDimension.DECADE,
                    media_types=[MediaType.MOVIE],
                    title_format="{value}s",
                ),
            )
        ],
        "collections": [
            PortableCollection(
                title="Action Night",
                collection_group="Holidays",
                active_start_mmdd="12-01",
                active_end_mmdd="12-26",
                criteria={MediaType.MOVIE: ACTION},
                art=PresetArt(
                    poster=PresetPoster(url=POSTER),
                    background=PresetImage(url=BACKGROUND),
                ),
            )
        ],
    }
    return CollectionPresetFile(**fields | changes)


async def test_an_export_is_a_file_another_install_can_add(
    manager: Manager,
) -> None:
    service = manager.service
    await service.groups.save_policy(
        "Decades",
        CollectionGroupPolicy(
            minimum_items=2,
            generator=CollectionGenerator(
                dimension=SetDimension.DECADE, library_ids=["1:movies"]
            ),
        ),
        new_set=True,
    )
    await service.groups.sync("Decades", RecordedReport())
    action = await service.editor.create(
        CollectionCreate(
            title="Action",
            collection_group="Decades",
            rule=library_rule(criteria=ACTION, minimum_items=1, request_missing=True),
        )
    )
    local = await service.editor.create(
        CollectionCreate(
            collection_group="Films",
            title="Local",
            rule=library_rule(
                criteria=where(FilterField.FOLDER, FilterOperator.CONTAINS, "/media")
            ),
        )
    )
    labelled = await service.editor.create(
        CollectionCreate(
            collection_group="Films",
            title="Labelled",
            rule=library_rule(
                criteria=where(FilterField.LABEL, FilterOperator.IS, "x")
            ),
        )
    )
    generated = [
        row for row in await service.reader.listed() if row.generated_value is not None
    ]
    assert generated

    exported = await service.presets.export(
        PresetExportRequest(
            groups=["decades", "Missing"],
            collection_ids=[local.id, labelled.id, generated[0].id],
        )
    )
    assert exported.file is not None
    assert [group.name for group in exported.file.groups] == ["Decades"]
    assert exported.file.groups[0].generator == PortableSet(
        dimension=SetDimension.DECADE, media_types=[MediaType.MOVIE]
    )
    assert exported.file.groups[0].minimum_items == 2
    assert [collection.title for collection in exported.file.collections] == [
        "Action",
        "Labelled",
    ]
    [first, _] = exported.file.collections
    assert first.criteria == {MediaType.MOVIE: ACTION}
    assert first.policy.request_missing is True
    assert first.policy.minimum_items == 1
    assert {(refusal.title, refusal.reason) for refusal in exported.refused} == {
        ("Missing", "No such group"),
        ("Local", "It tests folder, which only this install has"),
        (generated[0].title, "Its group's set makes it; export the group"),
    }
    assert exported.warnings == [
        (
            "Action: requests titles or writes labels or tags, which OvertureDB "
            "presets leave to the person adding them"
        ),
        "Labelled: tests labels another install may lack",
    ]
    assert action.title not in {refusal.title for refusal in exported.refused}

    assert exported.issue is not None
    assert exported.issue.url is not None
    assert exported.issue.url.startswith(
        "https://github.com/AutoGitr/OvertureDB/issues/new?template=preset.yml"
    )
    round_trip = CollectionPresetFile.model_validate_json(
        exported.file.model_dump_json()
    )
    assert round_trip == exported.file


async def test_an_export_of_nothing_portable_has_no_file(
    manager: Manager,
) -> None:
    exported = await manager.service.presets.export(
        PresetExportRequest(groups=["Nothing here"])
    )
    assert exported.file is None
    assert [refusal.reason for refusal in exported.refused] == ["No such group"]


def _published(**changes: Any) -> dict[str, Any]:
    return holidays(**changes).model_dump(mode="json")


async def test_the_gallery_lists_presets_by_category_with_what_keeps_them_from_use(
    manager: Manager,
) -> None:
    newer = _published() | {"preset": {"id": "newer"}, "future": True}
    charts = _published(
        preset=PresetMetadata(
            id="charts",
            title="Charts",
            description="Popular titles.",
            category=PresetCategory.CHARTS,
            media_types=[MediaType.MOVIE],
        ),
        groups=[],
        collections=[
            PortableCollection(
                title="Trending",
                criteria={MediaType.MOVIE: ACTION},
            )
        ],
    )
    bundle = (
        {"generated_at": "2026-11-01T00:00:00Z", "source_revision": "a" * 40},
        [newer, _published(), "not a preset", charts],
    )
    with patch(
        "overture.services.collections.presets.fetch_presets",
        AsyncMock(return_value=bundle),
    ):
        gallery = await manager.service.presets.gallery()
    assert gallery.error is None
    # Charts come before Seasonal; what cannot be read comes last.
    first, second, third, fourth = gallery.presets
    assert first.id == "charts"
    assert second.id == "holidays"
    assert second.file == holidays()
    assert second.setup == []
    assert second.preview_url == "https://image.tmdb.org/t/p/w342/poster.jpg"
    assert {(third.id, third.problem), (fourth.id, fourth.problem)} == {
        ("newer", "Needs a newer version of Overture"),
        ("unknown", "Needs a newer version of Overture"),
    }

    with patch(
        "overture.services.collections.presets.fetch_presets",
        AsyncMock(
            side_effect=ValueError("OvertureDB's presets could not be downloaded")
        ),
    ):
        failed = await manager.service.presets.gallery()
    assert failed.error == "OvertureDB's presets could not be downloaded"
    assert failed.presets == []


def test_a_file_tests_only_what_another_install_has() -> None:
    with pytest.raises(ValueError, match="Folder names something only one install"):
        holidays(
            collections=[
                PortableCollection(
                    title="Local",
                    criteria={
                        MediaType.MOVIE: where(
                            FilterField.FOLDER, FilterOperator.IS, "/media"
                        )
                    },
                )
            ]
        )
    with pytest.raises(ValueError, match="holds shows it does not list"):
        holidays(
            collections=[
                PortableCollection(title="Shows", criteria={MediaType.SHOW: ACTION})
            ]
        )
    with pytest.raises(ValueError, match="Add a condition for each media type"):
        PortableCollection(title="Empty", criteria={MediaType.MOVIE: FilterGroup()})
    with pytest.raises(ValueError, match="Give each collection its own title"):
        holidays(collections=holidays().collections * 2)
    with pytest.raises(ValueError, match="Add a collection or a set"):
        CollectionPresetFile()


def test_sources_name_the_integration_they_read() -> None:
    assert source_integration(SourceType.TMDB_ITEM) is None
    assert source_integration(SourceType.TMDB_CHART) is Integration.TMDB
    assert source_integration(SourceType.MDBLIST) is Integration.MDBLIST
    assert source_integration(SourceType.RADARR_TAG) is Integration.RADARR
    assert source_integration(SourceType.SONARR_TAG) is Integration.SONARR


async def test_a_file_read_from_disk_is_listed_as_a_preset_is(
    manager: Manager,
) -> None:
    listing = manager.service.presets.read_file(holidays(preset=None))
    assert (listing.id, listing.preset, listing.file) == (
        "file",
        None,
        holidays(preset=None),
    )
    assert listing.setup == []


def _form_bodies(
    file: CollectionPresetFile,
) -> tuple[list[tuple[str, CollectionGroupPolicy, bool]], list[CollectionCreate]]:
    """The groups and collections the create form saves for each item of *file*.

    A set and a group's defaults are saved as the group; each collection takes
    every library of the media types it has criteria for, and its group, or
    one picked when it names none.
    """
    groups = [
        (
            group.name,
            CollectionGroupPolicy(
                **group.model_dump(exclude={"name", "generator"}),
                generator=CollectionGenerator(
                    **group.generator.model_dump(exclude={"media_types"}),
                    library_ids=[
                        LIBRARIES[kind] for kind in group.generator.media_types
                    ],
                )
                if group.generator
                else None,
            ),
            group.generator is not None,
        )
        for group in file.groups
    ]
    collections = [
        CollectionCreate(
            **collection.model_dump(
                include=set(CollectionOptions.model_fields) - {"collection_group"},
                exclude_unset=True,
            ),
            # A preset may leave the group to the person adding it, who picks one.
            collection_group=collection.collection_group or "Picked",
            rule=CollectionRuleWrite(
                **collection.policy.model_dump(exclude_unset=True),
                smart=collection.smart,
                limit=collection.limit,
                libraries=[
                    CollectionLibraryCriteria(
                        library_id=LIBRARIES[kind], criteria=criteria
                    )
                    for kind, criteria in collection.criteria.items()
                ],
            ),
        )
        for collection in file.collections
    ]
    return groups, collections


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(path.read_text(), id=path.stem)
        for path in sorted((OVERTUREDB / "data/presets").glob("*.json"))
    ]
    or [pytest.param("", marks=pytest.mark.skip(reason="No OvertureDB checkout"))],
)
async def test_every_overturedb_preset_saves_on_plex(
    manager: Manager, text: str
) -> None:
    """Each published preset fills a form a Plex server with both media types saves."""
    groups, collections = _form_bodies(CollectionPresetFile.model_validate_json(text))
    for name, policy, new_set in groups:
        await manager.service.groups.save_policy(name, policy, new_set=new_set)
    for body in collections:
        await manager.service.editor.create(body)
