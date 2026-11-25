"""Portable collection files: exporting, planning and adding them, and the gallery."""

lazy import os
lazy from dataclasses import dataclass
lazy from pathlib import Path
lazy from typing import Any
lazy from unittest.mock import AsyncMock, patch

lazy import pytest

lazy from overture.domain import (
    ArtType,
    CollectionOrder,
    CollectionPosterStyle,
    FilterField,
    FilterOperator,
    Integration,
    MediaType,
    PresetCategory,
    SetDimension,
    SourceType,
    TmdbChart,
)
lazy from overture.schemas.art import SaveCollectionArtRequest
lazy from overture.schemas.collection_presets import (
    CollectionPresetFile,
    PortableCollection,
    PortableGroup,
    PortableSet,
    PresetArt,
    PresetExportRequest,
    PresetImage,
    PresetImportRequest,
    PresetMetadata,
    PresetPoster,
)
lazy from overture.schemas.collections import (
    CollectionCreate,
    CollectionGenerator,
    CollectionGroupPolicy,
    CollectionOptions,
    CollectionPolicyBase,
    FilterGroup,
    TmdbChartSource,
)
lazy from overture.schemas.common import Status, StatusResponse
lazy from overture.services.collections.service import CollectionsService
lazy from overture.services.collections.sources import source_integration
lazy from overture.utils.errors import PublicServiceError
lazy from tests.collection_helpers import library_rule
lazy from tests.sync_helpers import RecordedReport
lazy from tests.test_services import test_collection_management as management
lazy from tests.test_services.test_collection_management import (
    Manager,
    sources,
    where,
)

#: The collections service of the management tests, with the TMDB and MDBList
#: keys its sources need; pytest finds fixtures by their name in the module.
app_config = management.app_config
manager = management.manager

ROOT = Path(__file__).resolve().parents[2]
POSTER = "https://image.tmdb.org/t/p/original/poster.jpg"
BACKGROUND = "https://image.tmdb.org/t/p/original/background.jpg"
ACTION = where(FilterField.GENRE, FilterOperator.IS, "Action")


class SavedArt:
    """Records each art choice someone waits on, failing for one link."""

    def __init__(self) -> None:
        self.saved: list[tuple[int, ArtType, SaveCollectionArtRequest]] = []
        self.refused: str | None = None

    async def save(
        self, collection_id: int, art_type: ArtType, body: SaveCollectionArtRequest
    ) -> StatusResponse:
        if body.url == self.refused:
            raise PublicServiceError(503, "TMDB is pausing requests")
        self.saved.append((collection_id, art_type, body))
        return StatusResponse(status=Status.OK)


@dataclass(slots=True)
class Bed:
    service: CollectionsService
    art: SavedArt


@pytest.fixture
def bed(
    manager: Manager,
    monkeypatch: pytest.MonkeyPatch,
) -> Bed:
    """The collections service, with the art choices it makes recorded."""
    art = SavedArt()
    monkeypatch.setattr(manager.art, "save", art.save)
    return Bed(manager.service, art)


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


def request(file: CollectionPresetFile, **changes: Any) -> PresetImportRequest:
    return PresetImportRequest.model_validate(
        {
            "file": file.model_dump(mode="json"),
            "libraries": {"movie": ["1:movies"], "show": ["1:shows"]},
            **changes,
        }
    )


async def test_a_file_adds_its_groups_then_its_collections_once(
    bed: Bed,
) -> None:
    body = request(holidays())
    plan = await bed.service.presets.plan(body)
    assert [(item.kind, item.name, item.status) for item in plan.items] == [
        ("group", "Decades", "add"),
        ("collection", "Action Night", "add"),
    ]
    assert plan.warnings == []

    result = await bed.service.presets.import_(body)
    assert [item.status for item in result.items] == ["add", "add"]
    [created] = result.collection_ids
    detail = await bed.service.reader.get(created)
    assert detail.collection_group == "Holidays"
    assert (detail.active_start_mmdd, detail.active_end_mmdd) == ("12-01", "12-26")
    assert detail.rule is not None
    assert [(part.library_id, part.criteria) for part in detail.rule.libraries] == [
        ("1:movies", ACTION)
    ]
    assert [
        (kind, request.url, request.poster_style) for _, kind, request in bed.art.saved
    ] == [
        (ArtType.POSTER, POSTER, CollectionPosterStyle.INDIVIDUAL),
        (ArtType.BACKGROUND, BACKGROUND, None),
    ]
    policy = await bed.service.groups.policy("Decades")
    assert policy.minimum_items == 1
    assert policy.generator == CollectionGenerator(
        dimension=SetDimension.DECADE, library_ids=["1:movies"], title_format="{value}s"
    )

    again = await bed.service.presets.plan(body)
    assert [(item.status, item.reason) for item in again.items] == [
        ("skip", "Unchanged since the preset was added"),
        ("skip", "Unchanged since the preset was added"),
    ]
    exported = request(holidays(preset=None))
    assert [
        item.status for item in (await bed.service.presets.plan(exported)).items
    ] == [
        "skip",
        "refused",
    ]


async def test_a_plan_names_what_cannot_be_added_and_skips_what_is_asked(
    bed: Bed,
) -> None:
    file = holidays(
        preset=None,
        collections=[
            PortableCollection(title="Anime", criteria={MediaType.SHOW: ACTION}),
            PortableCollection(
                title="Charts",
                criteria={
                    MediaType.MOVIE: sources(
                        TmdbChartSource(chart=TmdbChart.AIRING_TODAY)
                    )
                },
            ),
            PortableCollection(title="Skipped", criteria={MediaType.MOVIE: ACTION}),
        ],
    )
    plan = await bed.service.presets.plan(
        request(file, libraries={"movie": ["1:movies"]}, skip=["skipped", "Decades"])
    )
    assert [(item.name, item.status, item.reason) for item in plan.items] == [
        ("Decades", "skip", None),
        ("Anime", "refused", "Choose a library for shows"),
        ("Charts", "refused", "TMDB has no airing today chart of movies"),
        ("Skipped", "skip", None),
    ]
    result = await bed.service.presets.import_(
        request(file, libraries={"movie": ["1:movies"]}, skip=["skipped", "Decades"])
    )
    assert result.collection_ids == []
    assert bed.art.saved == []


async def test_a_collection_keeps_its_place_when_its_art_is_refused(
    bed: Bed,
) -> None:
    bed.art.refused = POSTER
    result = await bed.service.presets.import_(request(holidays(groups=[])))
    [item] = result.items
    assert item.status == "add"
    assert item.reason == "Its poster was not set: TMDB is pausing requests"
    assert len(result.collection_ids) == 1


async def test_an_export_is_a_file_another_install_can_add(
    bed: Bed,
) -> None:
    service = bed.service
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
            title="Local",
            rule=library_rule(
                criteria=where(FilterField.FOLDER, FilterOperator.CONTAINS, "/media")
            ),
        )
    )
    labelled = await service.editor.create(
        CollectionCreate(
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


async def test_an_export_of_nothing_portable_has_no_file(bed: Bed) -> None:
    exported = await bed.service.presets.export(
        PresetExportRequest(groups=["Nothing here"])
    )
    assert exported.file is None
    assert [refusal.reason for refusal in exported.refused] == ["No such group"]


def _published(**changes: Any) -> dict[str, Any]:
    return holidays(**changes).model_dump(mode="json")


async def test_the_gallery_lists_each_preset_with_what_keeps_it_from_being_added(
    bed: Bed,
) -> None:
    newer = _published() | {"preset": {"id": "newer"}, "future": True}
    bundle = (
        {"generated_at": "2026-11-01T00:00:00Z", "source_revision": "a" * 40},
        [_published(), newer, "not a preset"],
    )
    with patch(
        "overture.services.collections.presets.fetch_presets",
        AsyncMock(return_value=bundle),
    ):
        gallery = await bed.service.presets.gallery()
    assert gallery.error is None
    first, second, third = gallery.presets
    assert first.id == "holidays"
    assert first.file == holidays()
    assert first.unavailable == []
    assert first.preview_url == "https://image.tmdb.org/t/p/w342/poster.jpg"
    assert (second.id, second.problem) == ("newer", "Needs a newer version of Overture")
    assert (third.id, third.file) == ("unknown", None)

    with patch(
        "overture.services.collections.presets.fetch_presets",
        AsyncMock(
            side_effect=ValueError("OvertureDB's presets could not be downloaded")
        ),
    ):
        failed = await bed.service.presets.gallery()
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


def _changed() -> CollectionPresetFile:
    """The holidays preset with its collection's criteria and group changed,
    its set dropped and a collection added."""
    file = holidays()
    night = file.collections[0].model_copy(
        update={
            "criteria": {
                MediaType.MOVIE: where(FilterField.YEAR, FilterOperator.GT, 2000)
            }
        }
    )
    return file.model_copy(
        update={
            "groups": [],
            "collections": [
                night,
                PortableCollection(
                    title="Classics", criteria={MediaType.MOVIE: ACTION}
                ),
            ],
        }
    )


async def test_a_newer_version_updates_what_the_preset_added_and_adds_the_rest(
    bed: Bed,
) -> None:
    service = bed.service
    [created] = (await service.presets.import_(request(holidays()))).collection_ids
    # Renamed and moved here; an update keeps both.
    detail = await service.reader.get(created)
    await service.editor.update(
        created,
        CollectionOptions.model_validate(
            detail.model_dump(include=set(CollectionOptions.model_fields))
            | {"title": "Movie Night", "collection_group": "Mine"}
        ),
    )

    newer = request(_changed())
    plan = await service.presets.plan(newer)
    assert [(item.kind, item.name, item.status) for item in plan.items] == [
        ("collection", "Action Night", "update"),
        ("collection", "Classics", "add"),
        ("group", "Decades", "skip"),
    ]
    assert plan.items[2].reason == "No longer in the preset; it stays as it is"

    result = await service.presets.import_(newer)
    assert [item.status for item in result.items] == ["update", "add", "skip"]
    updated = await service.reader.get(created)
    assert (updated.title, updated.collection_group) == ("Movie Night", "Mine")
    assert updated.rule is not None
    assert updated.rule.libraries[0].criteria == where(
        FilterField.YEAR, FilterOperator.GT, 2000
    )
    # Decades was dropped and is no longer the preset's to mention.
    assert [item.status for item in (await service.presets.plan(newer)).items] == [
        "skip",
        "skip",
    ]


async def test_a_skipped_update_is_offered_again(bed: Bed) -> None:
    service = bed.service
    await service.presets.import_(request(holidays()))
    newer = request(_changed(), skip=["Action Night"])
    result = await service.presets.import_(newer)
    assert [(item.name, item.status) for item in result.items][:2] == [
        ("Action Night", "skip"),
        ("Classics", "add"),
    ]
    again = await service.presets.plan(request(_changed()))
    assert [(item.name, item.status) for item in again.items] == [
        ("Action Night", "update"),
        ("Classics", "skip"),
    ]
    header = {"generated_at": "2026-11-01T00:00:00Z", "source_revision": "a" * 40}
    with patch(
        "overture.services.collections.presets.fetch_presets",
        AsyncMock(return_value=(header, [_changed().model_dump(mode="json")])),
    ):
        [listing] = (await service.presets.gallery()).presets
    assert listing.changes == ["Changes Action Night"]


async def test_the_gallery_names_what_a_newer_version_changes(bed: Bed) -> None:
    await bed.service.presets.import_(request(holidays()))
    header = {"generated_at": "2026-11-01T00:00:00Z", "source_revision": "a" * 40}
    for published, changes in (
        (holidays(), []),
        (
            _changed(),
            ["Changes Action Night", "Adds Classics", "Drops Decades"],
        ),
    ):
        with patch(
            "overture.services.collections.presets.fetch_presets",
            AsyncMock(return_value=(header, [published.model_dump(mode="json")])),
        ):
            [listing] = (await bed.service.presets.gallery()).presets
        assert listing.added_at is not None
        assert listing.changes == changes


async def test_what_was_deleted_since_is_offered_but_not_chosen(bed: Bed) -> None:
    service = bed.service
    [created] = (await service.presets.import_(request(holidays()))).collection_ids
    await service.editor.delete(created)
    plan = await service.presets.plan(request(_changed()))
    night = next(item for item in plan.items if item.name == "Action Night")
    assert (night.status, night.reason, night.chosen) == (
        "add",
        "Deleted here since the preset added it",
        False,
    )
    assert all(item.chosen for item in plan.items if item is not night)


async def test_choices_the_whole_refuses_are_refused_not_failed(bed: Bed) -> None:
    with pytest.raises(ValueError, match="Choose each library for one media type"):
        request(holidays(), libraries={"movie": ["1:movies"], "show": ["1:movies"]})
    smart_by_hand = holidays(
        preset=None,
        groups=[],
        collections=[
            PortableCollection(
                title="By hand",
                smart=True,
                policy=CollectionPolicyBase(order_type=CollectionOrder.CUSTOM),
                criteria={MediaType.MOVIE: ACTION},
            )
        ],
    )
    [item] = (await bed.service.presets.plan(request(smart_by_hand))).items
    assert item.status == "refused"
    assert item.reason is not None


async def test_every_overturedb_preset_plans_on_plex(bed: Bed) -> None:
    """Each published preset is one a Plex server with both media types can add."""
    folder = Path(os.environ.get("OVERTUREDB_DIR", ROOT.parent / "OvertureDB"))
    presets = sorted((folder / "data/presets").glob("*.json"))
    if not presets:
        pytest.skip(f"OvertureDB is not checked out at {folder}")
    refused = {
        f"{path.stem}: {item.name}: {item.reason}"
        for path in presets
        for item in (
            await bed.service.presets.plan(
                request(CollectionPresetFile.model_validate_json(path.read_text()))
            )
        ).items
        if item.status == "refused"
    }
    assert refused == set()
