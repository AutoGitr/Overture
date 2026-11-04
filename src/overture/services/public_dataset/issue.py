"""Prefilled OvertureDB issues that contribute one entry each."""

lazy from typing import Any, cast
lazy from urllib.parse import urlencode

lazy from sqlalchemy.orm import QueryableAttribute, selectinload
lazy from sqlmodel import col, select

lazy from ...dataset_contract.contract import (
    ISSUE_FORM_FIELDS,
    ISSUE_FORMS,
    validate_entry,
)
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...db.session import Database
lazy from ...repositories.public_dataset import PublicDatasetRepository
lazy from ...schemas.public_dataset import ContributionIssue
lazy from ...utils.errors import PublicServiceError
lazy from .browse import catalog_collection_entry, catalog_item_entry
lazy from .catalog import PUBLIC_DATASET_REPO_URL
lazy from .export import collection_entry, item_entry, refused_art
lazy from .lookup import find_public_item

#: The kind each issue form's title starts with, as its template writes it.
_TITLE_KINDS = {"movie": "Movie", "show": "Show", "collection": "Collection"}
#: How the reason for a modification names each field the issue replaces.
_REPLACED = {
    "title": "title",
    "year": "year",
    "tmdb_id": "TMDB ID",
    "tvdb_id": "TVDB ID",
    "imdb_id": "IMDb ID",
    "poster_url": "poster",
    "background_url": "background",
    "youtube_id_overturedb": "theme",
}


def _value(field: str, value: Any) -> str | None:
    if value is None or value is False:
        return None
    if field == "seasons":
        return (
            "\n".join(
                f"{season['season_num']}={season['poster_url']}" for season in value
            )
            or None
        )
    return str(value)


def _season_posters(entry: dict[str, Any]) -> dict[int, str]:
    seasons: list[dict[str, Any]] = entry.get("seasons") or []
    return {int(season["season_num"]): str(season["poster_url"]) for season in seasons}


def _replaced(entry: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """What *entry* changes that OvertureDB already holds, in form order."""
    changed = [
        label
        for field, label in _REPLACED.items()
        if None not in {current.get(field), entry.get(field)}
        and entry.get(field) != current.get(field)
    ]
    held = _season_posters(current)
    numbers = [
        str(number)
        for number, url in _season_posters(entry).items()
        if held.get(number) not in {None, url}
    ]
    if numbers:
        changed.append(f"season {', '.join(numbers)} posters")
    return changed


def contribution_issue(
    entry: dict[str, Any] | None,
    left_out: list[str],
    *,
    current: dict[str, Any] | None = None,
) -> ContributionIssue:
    """Return the issue that contributes *entry*, or why there is none.

    *current* is the entry OvertureDB holds, whose values the issue names as
    replaced. GitHub cannot tick an issue form's checkboxes from a link, so a
    draft that records no theme says so instead.
    """
    if entry is None:
        return ContributionIssue(reason="Nothing is selected to contribute")
    try:
        validate_entry(entry)
    except ValueError as exc:
        return ContributionIssue(reason=str(exc))
    media_type = entry["media_type"]
    title = entry["title"] + (f" ({entry['year']})" if entry.get("year") else "")
    query = {
        "template": ISSUE_FORMS[media_type],
        "title": f"[{_TITLE_KINDS[media_type]}]: {title}",
    }
    for field, form_field in ISSUE_FORM_FIELDS.items():
        if field != "no_theme" and (value := _value(field, entry.get(field))):
            query[form_field] = value
    notes = list(left_out)
    if replaced := _replaced(entry, current or {}):
        query["modification_reason"] = (
            f"Replaces the {', '.join(replaced)} OvertureDB holds, because: "
        )
        notes.append("Finish the reason for modification")
    if entry.get("no_theme"):
        notes.append("Tick No theme on the form")
    return ContributionIssue(
        url=f"{PUBLIC_DATASET_REPO_URL}/issues/new?{urlencode(query)}", notes=notes
    )


async def item_issue(item_id: int, *, database: Database) -> ContributionIssue:
    """Return the issue contributing a library item's saved selections."""
    async with database.read_session() as session:
        item = (
            await session.exec(
                select(MediaItem)
                .where(col(MediaItem.id) == item_id)
                .options(
                    selectinload(
                        cast("QueryableAttribute[list[Season]]", MediaItem.seasons)
                    )
                )
            )
        ).first()
        if item is None:
            raise PublicServiceError(404, "Item not found")
        current = None
        if (public := await find_public_item(session, item)) is not None:
            seasons = await PublicDatasetRepository(session).list_seasons(
                public.id or 0
            )
            current = catalog_item_entry(
                public,
                {
                    season.season_num: season.poster_url
                    for season in seasons
                    if season.poster_url
                },
            )
    return contribution_issue(
        item_entry(item), refused_art(item.title, item), current=current
    )


async def collection_issue(
    collection_id: int, *, database: Database
) -> ContributionIssue:
    """Return the issue contributing a library collection's art and theme."""
    async with database.read_session() as session:
        row = await session.get(MediaCollection, collection_id)
        if row is None:
            raise PublicServiceError(404, "Collection not found")
        if row.tmdb_collection_id is None:
            return ContributionIssue(
                reason="Only collections matched to a TMDB collection are in OvertureDB"
            )
        catalog = await PublicDatasetRepository(session).collections_by_tmdb_id(
            {row.tmdb_collection_id}
        )
    held = catalog.get(row.tmdb_collection_id)
    return contribution_issue(
        collection_entry(row, held),
        refused_art(row.title, row),
        current=catalog_collection_entry(held) if held else None,
    )
