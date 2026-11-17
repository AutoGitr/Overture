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


def _read(row: SavedFilter) -> SavedFilterRead:
    return SavedFilterRead(
        id=row.id or 0,
        name=row.name,
        media_type=row.media_type,
        criteria=FilterGroup.model_validate(row.criteria),
    )


class SavedFilters:
    """Keep custom filters by name, each for one media type's titles."""

    def __init__(
        self, *, access: CollectionAccess, validator: CollectionValidator
    ) -> None:
        self._access = access
        self._validator = validator

    async def list(self, media_type: MediaType) -> list[SavedFilterRead]:
        """The media type's saved filters, by name."""
        async with self._access.database.read_session() as session:
            rows = await SavedFilterRepository(session).of_media_type(media_type)
        return [_read(row) for row in rows]

    async def create(self, body: SavedFilterWrite) -> SavedFilterRead:
        """Save a custom filter.

        Raises:
            PublicServiceError: 409 when the media type has a filter of the
                name; 422 for a condition the library cannot test.
        """
        self._validator.library_criteria(
            body.media_type, body.criteria, self._access.configured_types()
        )
        now = utc_now()
        async with self._access.database.write_session() as session:
            repo = SavedFilterRepository(session)
            await self._require_free_name(repo, body)
            row = SavedFilter(
                media_type=body.media_type,
                name=body.name,
                criteria=body.criteria.model_dump(mode="json"),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.flush()
            return _read(row)

    async def update(self, filter_id: int, body: SavedFilterWrite) -> SavedFilterRead:
        """Rename a saved filter or change its criteria.

        Raises:
            PublicServiceError: 404 when there is no such filter; 409 and 422
                as :meth:`create` raises them.
        """
        self._validator.library_criteria(
            body.media_type, body.criteria, self._access.configured_types()
        )
        async with self._access.database.write_session() as session:
            repo = SavedFilterRepository(session)
            row = await repo.get(filter_id)
            if row is None:
                raise PublicServiceError(404, _NOT_FOUND)
            await self._require_free_name(repo, body, exclude_id=filter_id)
            row.media_type = body.media_type
            row.name = body.name
            row.criteria = body.criteria.model_dump(mode="json")
            row.updated_at = utc_now()
            session.add(row)
            return _read(row)

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

    @staticmethod
    async def _require_free_name(
        repo: SavedFilterRepository,
        body: SavedFilterWrite,
        *,
        exclude_id: int | None = None,
    ) -> None:
        if await repo.name_exists(body.media_type, body.name, exclude_id=exclude_id):
            raise PublicServiceError(
                409, f"A saved filter is already named {body.name}"
            )
