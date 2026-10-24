"""The OvertureDB catalog as the catalog view browses and edits it."""

lazy from typing import Any

lazy from sqlmodel import col, func, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...config import Settings
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.public_dataset import (
    PublicDatasetCollection,
    PublicDatasetDraft,
    PublicDatasetItem,
)
lazy from ...db.session import Database
lazy from ...domain import ArtType, CatalogMediaType, MediaType
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...repositories.public_dataset import PublicDatasetRepository
lazy from ...repositories.public_dataset_drafts import PublicDatasetDraftRepository
lazy from ...schemas.public_dataset import (
    CatalogCounts,
    CatalogDraftUpdate,
    CatalogEntry,
    CatalogEntryDetail,
    CatalogEntryRow,
)
lazy from ...utils.art_urls import art_preview_url
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.time import utc_now
lazy from ..schedule_store import PUBLIC_DATASET_SCHEDULE, load_schedule
lazy from .schema.contract import (
    IDENTITY_FIELDS,
    catalog_art_url,
    entry_fields,
    entry_file_stem,
    parse_entry_file_stem,
    validate_entry,
)

type Entry = dict[str, Any]


def _item_entry(item: PublicDatasetItem, season_posters: dict[int, str]) -> Entry:
    """Return a stored movie or show as the contract spells the entry."""
    entry: Entry = {
        name: getattr(item, name)
        for name in entry_fields(item.media_type)
        if name != "seasons"
    }
    if item.media_type is MediaType.SHOW:
        entry["seasons"] = [
            {"season_num": number, "poster_url": url}
            for number, url in sorted(season_posters.items())
        ]
    return entry


def _collection_entry(collection: PublicDatasetCollection) -> Entry:
    """Return a stored collection as the contract spells the entry."""
    return {
        name: CatalogMediaType.COLLECTION.value
        if name == "media_type"
        else getattr(collection, name)
        for name in entry_fields(CatalogMediaType.COLLECTION)
    }


def _identities(entry: Entry) -> list[tuple[str, int | str]]:
    return [
        (field, value)
        for field in IDENTITY_FIELDS
        if (value := entry.get(field)) is not None
    ]


def _canonical_art(entry: Entry) -> Entry:
    """Return the entry with every artwork link in the catalog's form.

    Raises:
        PublicServiceError: When a link is not catalog artwork.
    """
    try:
        for name in ("poster_url", "background_url"):
            if entry.get(name):
                entry[name] = catalog_art_url(entry[name])
        seasons: list[dict[str, Any]] = entry.get("seasons") or []
        for season in seasons:
            season["poster_url"] = catalog_art_url(season["poster_url"])
    except ValueError as exc:
        raise PublicServiceError(422, str(exc)) from exc
    return entry


class CatalogBrowser:
    """List, read and draft changes to the whole catalog."""

    def __init__(self, *, database: Database, app_config: Settings) -> None:
        self._database = database
        self._config = app_config

    async def counts(self) -> CatalogCounts:
        """Count catalog entries and every draft in one database round trip."""
        async with self._database.read_session() as session:
            await self._require_enabled(session)

            def items(kind: MediaType):
                return (
                    select(func.count())
                    .select_from(PublicDatasetItem)
                    .where(col(PublicDatasetItem.media_type) == kind)
                    .scalar_subquery()
                )

            movies, shows, collections, drafts = (
                await session.exec(
                    select(
                        items(MediaType.MOVIE),
                        items(MediaType.SHOW),
                        select(func.count())
                        .select_from(PublicDatasetCollection)
                        .scalar_subquery(),
                        select(func.count())
                        .select_from(PublicDatasetDraft)
                        .scalar_subquery(),
                    )
                )
            ).one()
        return CatalogCounts(
            movies=movies, shows=shows, collections=collections, drafts=drafts
        )

    async def _require_enabled(self, session: AsyncSession) -> None:
        schedule = await load_schedule(
            session, PUBLIC_DATASET_SCHEDULE, timezone=self._config.TZ
        )
        if not schedule.enabled:
            raise PublicServiceError(409, "OvertureDB is disabled")

    async def list_entries(self, media_type: CatalogMediaType) -> list[CatalogEntryRow]:
        """Return every catalog entry of a media type with its library links."""
        async with self._database.read_session() as session:
            await self._require_enabled(session)
            catalog = PublicDatasetRepository(session)
            if media_type is CatalogMediaType.COLLECTION:
                entries = [
                    _collection_entry(row) for row in await catalog.list_collections()
                ]
            else:
                items = await catalog.list_items(MediaType(media_type))
                posters = await catalog.season_posters_by_item_ids(
                    {item.id for item in items if item.id is not None}
                )
                entries = [
                    _item_entry(item, posters.get(item.id or 0, {})) for item in items
                ]
            drafts = await PublicDatasetDraftRepository(session).list_all()
            links = await self._library_links(session, media_type)
        drafted = {
            (field, value): draft.entry
            for draft in drafts
            if draft.media_type is media_type
            for field in IDENTITY_FIELDS
            if (value := getattr(draft, field)) is not None
        }
        return sorted(
            (self._row(entry, links, drafted) for entry in entries),
            key=lambda row: (row.title.casefold(), row.year or 0, row.entry_key),
        )

    @staticmethod
    def _row(
        entry: Entry,
        links: dict[tuple[str, int | str], int],
        drafted: dict[tuple[str, int | str], Entry],
    ) -> CatalogEntryRow:
        identities = _identities(entry)
        link = next((links[key] for key in identities if key in links), None)
        effective = next((drafted[key] for key in identities if key in drafted), entry)
        poster = effective.get("poster_url")
        return CatalogEntryRow(
            **{
                name: value
                for name, value in effective.items()
                if name not in {"seasons", "poster_url"}
            },
            entry_key=entry_file_stem(entry),
            poster_url=poster,
            poster_preview_url=art_preview_url(poster, ArtType.POSTER)
            if poster
            else None,
            season_posters=len(effective.get("seasons") or []),
            has_draft=any(key in drafted for key in identities),
            library_item_id=link
            if entry["media_type"] != CatalogMediaType.COLLECTION
            else None,
            library_collection_id=link
            if entry["media_type"] == CatalogMediaType.COLLECTION
            else None,
        )

    @staticmethod
    async def _library_links(
        session: AsyncSession, media_type: CatalogMediaType, entry: Entry | None = None
    ) -> dict[tuple[str, int | str], int]:
        """Return what the library holds for each identity: an item or collection."""
        if media_type is not CatalogMediaType.COLLECTION:
            ids = await MediaItemRepository(session).visible_ids_by_identity(
                MediaType(media_type), _identities(entry) if entry else None
            )
            return dict(ids)
        stmt = select(MediaCollection).where(
            col(MediaCollection.last_synced_at).is_not(None)
        )
        if entry is not None:
            stmt = stmt.where(
                col(MediaCollection.tmdb_collection_id) == entry["tmdb_id"]
            )
        return {
            ("tmdb_id", row.tmdb_collection_id): row.id
            for row in await session.exec(stmt)
            if row.tmdb_collection_id is not None and row.id is not None
        }

    async def _entry(
        self, session: AsyncSession, media_type: CatalogMediaType, entry_key: str
    ) -> Entry:
        """Return the catalog entry an entry name identifies.

        Raises:
            PublicServiceError: When the name is malformed or nothing matches.
        """
        await self._require_enabled(session)
        try:
            field, value = parse_entry_file_stem(entry_key)
        except ValueError as exc:
            raise PublicServiceError(404, "Catalog entry not found") from exc
        catalog = PublicDatasetRepository(session)
        if media_type is CatalogMediaType.COLLECTION:
            found = (
                await catalog.collections_by_tmdb_id({value})
                if field == "tmdb_id" and isinstance(value, int)
                else {}
            )
            if found:
                return _collection_entry(next(iter(found.values())))
        elif item := await catalog.find_item(MediaType(media_type), field, value):
            seasons = await catalog.list_seasons(item.id or 0)
            return _item_entry(
                item,
                {s.season_num: s.poster_url for s in seasons if s.poster_url},
            )
        raise PublicServiceError(404, "Catalog entry not found")

    async def _detail(
        self, session: AsyncSession, media_type: CatalogMediaType, entry: Entry
    ) -> CatalogEntryDetail:
        draft = await PublicDatasetDraftRepository(session).find(
            media_type, _identities(entry)
        )
        links = await self._library_links(session, media_type, entry)
        row = self._row(entry, links, {})
        return CatalogEntryDetail(
            entry_key=row.entry_key,
            entry=CatalogEntry.model_validate(entry),
            draft=CatalogEntry.model_validate(draft.entry) if draft else None,
            library_item_id=row.library_item_id,
            library_collection_id=row.library_collection_id,
        )

    async def get_entry(
        self, media_type: CatalogMediaType, entry_key: str
    ) -> CatalogEntryDetail:
        """Return one catalog entry with its draft and library links."""
        async with self._database.read_session() as session:
            entry = await self._entry(session, media_type, entry_key)
            return await self._detail(session, media_type, entry)

    async def save_draft(
        self, media_type: CatalogMediaType, entry_key: str, body: CatalogDraftUpdate
    ) -> CatalogEntryDetail:
        """Apply changes to an entry's draft; a draft equal to the entry goes away.

        Raises:
            PublicServiceError: When the changed entry breaks the contract.
        """
        changes = body.model_dump(exclude_unset=True)
        fields = entry_fields(media_type)
        if unknown := sorted(set(changes) - set(fields)):
            raise PublicServiceError(
                422, f"A {media_type} entry has no {', '.join(unknown)}"
            )
        async with self._database.write_session() as session:
            entry = await self._entry(session, media_type, entry_key)
            repository = PublicDatasetDraftRepository(session)
            draft = await repository.find(media_type, _identities(entry))
            proposed = _canonical_art({**(draft.entry if draft else entry), **changes})
            try:
                validate_entry(proposed)
            except ValueError as exc:
                raise PublicServiceError(422, str(exc)) from exc
            conflicting = await repository.find(media_type, _identities(proposed))
            if conflicting is not None and (
                draft is None or conflicting.id != draft.id
            ):
                raise PublicServiceError(
                    422, "Another draft already uses this identity"
                )
            if proposed == entry:
                if draft is not None:
                    await session.delete(draft)
            else:
                draft = draft or PublicDatasetDraft(
                    media_type=media_type, entry=proposed, updated_at=utc_now()
                )
                draft.sqlmodel_update(
                    {
                        "entry": proposed,
                        # Lookup identities belong to the original entry, even
                        # when the contribution corrects an identifier.
                        "tmdb_id": entry.get("tmdb_id"),
                        "tvdb_id": entry.get("tvdb_id"),
                        "imdb_id": entry.get("imdb_id"),
                        "updated_at": utc_now(),
                    }
                )
                session.add(draft)
            await session.flush()
            return await self._detail(session, media_type, entry)

    async def discard_draft(
        self, media_type: CatalogMediaType, entry_key: str
    ) -> CatalogEntryDetail:
        """Remove an entry's draft."""
        async with self._database.write_session() as session:
            entry = await self._entry(session, media_type, entry_key)
            draft = await PublicDatasetDraftRepository(session).find(
                media_type, _identities(entry)
            )
            if draft is not None:
                await session.delete(draft)
                await session.flush()
            return await self._detail(session, media_type, entry)
