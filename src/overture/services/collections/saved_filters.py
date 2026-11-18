"""Custom library filters saved under a name."""

lazy from ...db.models.saved_filter import SavedFilter
lazy from ...domain import MediaType
lazy from ...repositories.saved_filters import SavedFilterRepository
lazy from ...schemas.collections import FilterGroup
lazy from ...schemas.common import Status, StatusResponse
lazy from ...schemas.library_filters import SavedFilterRead, SavedFilterWrite
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.time import utc_now
lazy from .access import CollectionAccess
lazy from .validation import CollectionValidator

_NOT_FOUND = "Saved filter not found"


def _named_type(body: SavedFilterWrite) -> MediaType | None:
    """The media type the filter's TMDB IDs name, if it names titles by ID."""
    return body.media_type if body.criteria.names_titles() else None


class SavedFilters:
    """Keep custom filters by name, each offered where its conditions apply."""

    def __init__(
        self, *, access: CollectionAccess, validator: CollectionValidator
    ) -> None:
        self._access = access
        self._validator = validator

    async def list(self) -> list[SavedFilterRead]:
        """Every saved filter by name, with the media types it applies to."""
        async with self._access.database.read_session() as session:
            rows = await SavedFilterRepository(session).by_name()
        return [self._read(row) for row in rows]

    async def create(self, body: SavedFilterWrite) -> SavedFilterRead:
        """Save a custom filter.

        Raises:
            PublicServiceError: 409 when a filter has the name; 422 when no
                media type's titles can be tested by all its conditions.
        """
        self._require_applicable(body)
        now = utc_now()
        async with self._access.database.write_session() as session:
            repo = SavedFilterRepository(session)
            await self._require_free_name(repo, body)
            row = SavedFilter(
                name=body.name,
                media_type=_named_type(body),
                criteria=body.criteria.model_dump(mode="json"),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.flush()
            return self._read(row)

    async def update(self, filter_id: int, body: SavedFilterWrite) -> SavedFilterRead:
        """Rename a saved filter or change its criteria.

        Raises:
            PublicServiceError: 404 when there is no such filter; 409 and 422
                as :meth:`create` raises them.
        """
        self._require_applicable(body)
        async with self._access.database.write_session() as session:
            repo = SavedFilterRepository(session)
            row = await repo.get(filter_id)
            if row is None:
                raise PublicServiceError(404, _NOT_FOUND)
            await self._require_free_name(repo, body, exclude_id=filter_id)
            row.name = body.name
            row.media_type = _named_type(body)
            row.criteria = body.criteria.model_dump(mode="json")
            row.updated_at = utc_now()
            session.add(row)
            return self._read(row)

    async def delete(self, filter_id: int) -> StatusResponse:
        """Forget a saved filter.

        Raises:
            PublicServiceError: 404 when there is no such filter.
        """
        async with self._access.database.write_session() as session:
            row = await SavedFilterRepository(session).get(filter_id)
            if row is None:
                raise PublicServiceError(404, _NOT_FOUND)
            await session.delete(row)
        return StatusResponse(status=Status.OK)

    def _unavailable(
        self, criteria: FilterGroup, named: MediaType | None
    ) -> dict[MediaType, str]:
        """Why each media type's titles cannot be tested by the criteria."""
        servers = self._access.configured_types()
        unavailable: dict[MediaType, str] = {}
        for media_type in MediaType:
            if named is not None and named is not media_type:
                unavailable[media_type] = f"Its TMDB IDs name {named.plural}"
                continue
            try:
                self._validator.library_criteria(media_type, criteria, servers)
            except PublicServiceError as error:
                unavailable[media_type] = error.message
        return unavailable

    def _require_applicable(self, body: SavedFilterWrite) -> None:
        unavailable = self._unavailable(body.criteria, _named_type(body))
        if len(unavailable) == len(MediaType):
            raise PublicServiceError(422, "; ".join(unavailable.values()))

    def _read(self, row: SavedFilter) -> SavedFilterRead:
        criteria = FilterGroup.model_validate(row.criteria)
        unavailable = self._unavailable(criteria, row.media_type)
        return SavedFilterRead(
            id=row.id or 0,
            name=row.name,
            criteria=criteria,
            media_type=row.media_type,
            media_types=[
                media_type for media_type in MediaType if media_type not in unavailable
            ],
            unavailable=unavailable,
        )

    @staticmethod
    async def _require_free_name(
        repo: SavedFilterRepository,
        body: SavedFilterWrite,
        *,
        exclude_id: int | None = None,
    ) -> None:
        if await repo.name_exists(body.name, exclude_id=exclude_id):
            raise PublicServiceError(
                409, f"A saved filter is already named {body.name}"
            )
