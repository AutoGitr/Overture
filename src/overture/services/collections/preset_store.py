"""Presets: the saved ones, then the built-in ones the server can evaluate."""

lazy from ...config import Settings
lazy from ...db.models.collection_preset import CollectionPreset
lazy from ...domain import MediaType
lazy from ...repositories.collections import CollectionRepository
lazy from ...schemas.collections import CollectionPresetRead, CollectionPresetSave
lazy from ...schemas.common import Status, StatusResponse
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.time import utc_now
lazy from .access import CollectionAccess
lazy from .presets import available_presets, saved_preset_read


class PresetStore:
    """Keep collections and sets as presets, beside the built-in ones."""

    def __init__(self, *, access: CollectionAccess, app_config: Settings) -> None:
        self._access = access
        self._app_config = app_config

    async def available(self, media_type: MediaType) -> list[CollectionPresetRead]:
        """Saved presets, then the built-in ones the server can evaluate."""
        async with self._access.database.read_session() as session:
            saved = await CollectionRepository(session).presets(media_type)
        return [
            *(saved_preset_read(row) for row in saved),
            *available_presets(
                self._access.server_type,
                media_type,
                tmdb=self._app_config.tmdb_configured,
            ),
        ]

    async def save(self, body: CollectionPresetSave) -> CollectionPresetRead:
        """Keep a collection or set as a preset, replacing one of the same name."""
        async with self._access.database.write_session() as session:
            existing = next(
                (
                    row
                    for row in await CollectionRepository(session).presets(
                        body.media_type
                    )
                    if row.label.casefold() == body.label.casefold()
                ),
                None,
            )
            row = existing or CollectionPreset(
                media_type=body.media_type, label=body.label, payload_json=""
            )
            row.label = body.label
            row.description = body.description
            row.payload_json = body.model_dump_json()
            row.created_at = row.created_at or utc_now()
            session.add(row)
            await session.flush()
            return saved_preset_read(row)

    async def delete(self, preset_id: int) -> StatusResponse:
        """Forget a saved preset."""
        async with self._access.database.write_session() as session:
            row = await session.get(CollectionPreset, preset_id)
            if row is None:
                raise PublicServiceError(404, "Preset not found")
            await session.delete(row)
        return StatusResponse(status=Status.DELETED)
