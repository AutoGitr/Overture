"""Running one operation over many collections, each committed on its own."""

lazy from collections.abc import Awaitable, Callable, Mapping

lazy from ...db.models.collection_rule import CollectionRule
lazy from ...db.models.media_collection import MediaCollection
lazy from ...domain import UNMANAGED_REFUSAL
lazy from ...repositories.collections import CollectionRepository
lazy from ...schemas.collections import (
    BulkCollectionOperation,
    BulkCollectionOperationResult,
    CollectionAdoption,
    CollectionOptions,
)
lazy from ..art.collection_art import CollectionArtService
lazy from .access import CollectionAccess
lazy from .display import saved_options
lazy from .editor import CollectionEditor
lazy from .themes import CollectionThemes

type BulkHandler = Callable[[int, BulkCollectionOperation], Awaitable[object]]
type OptionEdit = Callable[[CollectionOptions, BulkCollectionOperation], None]


def _set_group(options: CollectionOptions, body: BulkCollectionOperation) -> None:
    options.collection_group = body.collection_group


def _set_order(options: CollectionOptions, body: BulkCollectionOperation) -> None:
    if body.order_type is not None:
        options.order_type = body.order_type


def _set_visibility(options: CollectionOptions, body: BulkCollectionOperation) -> None:
    if "collection_mode" in body.model_fields_set:
        options.collection_mode = body.collection_mode
    if body.visible_home is not None:
        options.visible_home = body.visible_home
    if body.visible_shared is not None:
        options.visible_shared = body.visible_shared
    if body.visible_library is not None:
        options.visible_library = body.visible_library


def _apply_sort_title_format(
    options: CollectionOptions, body: BulkCollectionOperation
) -> None:
    if body.sort_title_format is not None:
        options.sort_title = None
        options.sort_title_format = body.sort_title_format


#: Bulk operations that change one display option of each collection.
OPTION_EDITS: Mapping[str, OptionEdit] = {
    "set_group": _set_group,
    "set_order": _set_order,
    "set_visibility": _set_visibility,
    "apply_sort_title_format": _apply_sort_title_format,
}


def bulk_options(
    row: MediaCollection, body: BulkCollectionOperation, rule: CollectionRule | None
) -> CollectionOptions:
    """A collection's saved options with the bulk operation's change applied."""
    options = saved_options(row, rule)
    OPTION_EDITS[body.operation](options, body)
    return options


class CollectionBulk:
    """Apply one operation to many collections, one collection at a time."""

    def __init__(
        self,
        *,
        access: CollectionAccess,
        editor: CollectionEditor,
        art: CollectionArtService,
        themes: CollectionThemes,
    ) -> None:
        self._access = access
        self._editor = editor
        self._handlers: Mapping[str, BulkHandler] = {
            "delete": lambda i, body: editor.delete(i, target=body.delete_target),
            "remove_artwork": lambda i, body: art.remove(i, None, body.removal),
            "remove_themes": lambda i, body: themes.remove(i, body.removal),
            "adopt": lambda i, body: editor.adopt(
                i, CollectionAdoption(group=body.collection_group)
            ),
            "orphan": lambda i, _: editor.orphan(i),
            "set_monitored": lambda i, body: editor.set_monitored(
                i, bool(body.monitored)
            ),
            **dict.fromkeys(OPTION_EDITS, self._edit_options),
        }

    async def run(self, body: BulkCollectionOperation) -> BulkCollectionOperationResult:
        """Use the single-collection workflows, committing each target independently."""
        handler = self._handlers[body.operation]
        result = BulkCollectionOperationResult()
        async with self._access.database.read_session() as session:
            managed = await CollectionRepository(session).managed_ids(
                body.collection_ids
            )
        for collection_id in body.collection_ids:
            # Adoption is the one change a collection Overture does not manage accepts.
            if (collection_id in managed) == (body.operation == "adopt"):
                result.errors[collection_id] = (
                    "Overture already manages it"
                    if body.operation == "adopt"
                    else UNMANAGED_REFUSAL
                )
                continue
            try:
                await handler(collection_id, body)
                result.collection_ids.append(collection_id)
            except Exception as exc:
                result.errors[collection_id] = str(exc)
        return result

    async def _edit_options(
        self, collection_id: int, body: BulkCollectionOperation
    ) -> None:
        # Keep the read and update under the same asset locks.
        async with self._access.locked(collection_id):
            async with self._access.database.read_session() as session:
                row = await self._access.require(session, collection_id)
            await self._editor.update_locked(row, bulk_options(row, body, row.rule))
        await self._access.updated(collection_id)
