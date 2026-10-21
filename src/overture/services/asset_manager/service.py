"""Asset manager route-facing service operations."""

lazy import logging
lazy from collections.abc import Iterable, Sequence
lazy from dataclasses import dataclass
lazy from pathlib import Path
lazy from typing import Any

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.session import Database
lazy from ...domain import ServerAsset
lazy from ...media_servers.errors import MediaServerError
lazy from ...media_servers.registry import ProviderRegistry
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...schemas.asset_manager import (
    AssetRenameResponse,
    AssetRenameResult,
    RenameItem,
    RenameRequest,
    RenameStatus,
    ScanRequest,
)
lazy from ...schemas.common import StatusResponse
lazy from ...utils.assets import (
    AUDIO_EXTENSIONS,
    IMAGE_EXTENSIONS,
    is_safe_asset_target,
)
lazy from ...utils.errors import public_error_message
lazy from ...utils.path import is_within_roots
lazy from ...utils.threads import owned_thread
lazy from ...ws.state import BackgroundJobRegistry
lazy from ..job_snapshots import patch_snapshot, require_snapshot_keys
lazy from ..local_assets.service import LocalAssets
lazy from ..storage.trusted_roots import (
    require_trusted_media_roots,
    validate_folders_under_trusted_roots,
)
lazy from .scan import run_scan

logger = logging.getLogger(__name__)


def _validate_rename(
    item: RenameItem, allowed_roots: Sequence[str | Path]
) -> tuple[Path, Path]:
    if not item.current_path or not item.suggested_path:
        raise ValueError("Missing paths")
    current = Path(item.current_path)
    suggested = Path(item.suggested_path)
    if current.is_symlink():
        raise ValueError("Symlink sources cannot be renamed")
    if not is_within_roots(current, allowed_roots):
        raise ValueError("Unauthorized current path")
    if not is_within_roots(suggested.parent, allowed_roots):
        raise ValueError("Unauthorized suggested path")
    if not is_safe_asset_target(suggested):
        raise ValueError("Suggested filename is not a canonical asset name")
    if current.parent.resolve() != suggested.parent.resolve():
        raise ValueError("Rename cannot move files between directories")
    if current.suffix.lower() not in IMAGE_EXTENSIONS | AUDIO_EXTENSIONS:
        raise ValueError("Unsupported source file extension")
    if not current.is_file():
        raise ValueError("Source not found")
    if any(_holds_other_file(path, current) for path in _slot_paths(suggested)):
        raise FileExistsError("Target already exists")
    return current, suggested


def _slot_paths(target: Path) -> list[Path]:
    """Return the target and, for an image, its names in other image formats.

    Overture reads ``poster.jpg`` and ``poster.png`` as the same slot, so a
    rename to one of them must not leave the other beside it.
    """
    if target.suffix.lower() not in IMAGE_EXTENSIONS:
        return [target]
    return [target, *(target.with_suffix(ext) for ext in sorted(IMAGE_EXTENSIONS))]


def _holds_other_file(path: Path, current: Path) -> bool:
    """Return whether *path* names a file other than the one being renamed.

    On a case-insensitive filesystem, ``poster.jpg`` exists when only
    ``Poster.jpg`` does: that is the source itself, so the case-only rename
    goes ahead. A hard link has another name, so it still counts as taken.
    """
    if path.is_symlink():
        return True
    if not path.exists():
        return False
    return not (
        path.name.casefold() == current.name.casefold() and path.samefile(current)
    )


def _rename_asset(
    item: RenameItem, allowed_roots: Sequence[str | Path]
) -> AssetRenameResult:
    try:
        current, suggested = _validate_rename(item, allowed_roots)
        current.rename(suggested)
        try:
            suggested.chmod(0o644)
        except OSError as exc:
            logger.warning("Could not set permissions after a rename: %s", exc)
        logger.info("Renamed asset %s to %s", current.name, suggested.name)
        return AssetRenameResult(
            current_path=item.current_path,
            suggested_path=item.suggested_path,
            status=RenameStatus.RENAMED,
        )
    except FileExistsError:
        return AssetRenameResult(
            current_path=item.current_path,
            status=RenameStatus.CONFLICT,
            reason="Target already exists",
        )
    except (OSError, ValueError) as exc:
        return AssetRenameResult(
            current_path=item.current_path,
            status=RenameStatus.ERROR,
            reason=public_error_message(exc),
        )


def patch_rename_snapshot(
    payload: dict[str, Any], results: list[AssetRenameResult]
) -> dict[str, Any]:
    """Persist row-level asset rename outcomes in the terminal scan snapshot."""
    status_by_path = {result.current_path: result for result in results}
    issues: list[dict[str, Any]] = payload.get("issues") or []
    for issue in issues:
        result = status_by_path.get(issue["current_path"])
        if not result:
            continue
        if result.status is RenameStatus.RENAMED:
            issue["renamed"] = True
            issue.pop("rename_error", None)
        elif result.status is RenameStatus.CONFLICT:
            issue["conflict"] = True
        else:
            issue["rename_error"] = result.reason or "Rename failed"
    return payload


#: The item asset each canonical file name in the item's own folder holds.
_ITEM_FOLDER_ASSETS = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        asset.value: asset
        for asset in (ServerAsset.POSTER, ServerAsset.BACKGROUND, ServerAsset.THEME)
    }
)


@dataclass(slots=True, frozen=True)
class _Owner:
    """The item a renamed file belongs to, if any."""

    item_id: int | None
    server_item_id: str | None
    #: The file is in the item's own folder rather than a season folder.
    item_folder: bool


class AssetManagerService:
    """Consolidated asset manager domain service."""

    def __init__(
        self,
        *,
        background_jobs: BackgroundJobRegistry,
        publisher: protocols.EventPublisher,
        app_config: Settings,
        local_assets: LocalAssets,
        provider_registry: ProviderRegistry,
        database: Database,
        config_dir: Path,
    ) -> None:
        self._jobs = background_jobs
        self._providers = provider_registry
        self._publisher = publisher
        self._config = app_config
        self._local_assets = local_assets
        self._asset_storage = local_assets.asset_storage
        self._database = database
        self._config_dir = config_dir

    async def start_scan(
        self,
        body: ScanRequest,
    ) -> StatusResponse:
        """Start an asset scan in the background."""
        await validate_folders_under_trusted_roots(
            self._database, body.movie_folders + body.show_folders
        )

        return StatusResponse.start(
            self._jobs.library_gate.start(
                "renamer",
                self._jobs.asset_scan,
                lambda context: run_scan(
                    body,
                    context,
                    app_config=self._config,
                    local_assets=self._local_assets,
                    database=self._database,
                    config_dir=self._config_dir,
                ),
            )
        )

    def stop_scan(self) -> StatusResponse:
        """Stop a running asset scan."""
        return StatusResponse.stop(self._jobs.asset_scan.request_stop())

    async def _owners(self, paths: Iterable[str]) -> dict[str, _Owner]:
        """Return the item whose folder, or a season folder of it, holds each file."""
        folders = {path: Path(path).parent for path in paths}
        async with self._database.read_session() as session:
            items = await MediaItemRepository(session).by_folder_paths(
                {str(f) for folder in folders.values() for f in (folder, folder.parent)}
            )
        owners: dict[str, _Owner] = {}
        for path, folder in folders.items():
            owner = _Owner(None, None, item_folder=False)
            for candidate in (folder, folder.parent):
                item = items.get(str(candidate))
                if item is not None and item.id is not None:
                    owner = _Owner(item.id, item.server_item_id, candidate == folder)
                    break
            owners[path] = owner
        return owners

    async def _rename_one(
        self, item: RenameItem, owner: _Owner, allowed_roots: Sequence[str | Path]
    ) -> tuple[_Owner, AssetRenameResult]:
        key = owner.item_id or f"folder:{Path(item.current_path).parent}"
        async with self._asset_storage.asset_locks.acquire(key):
            return owner, await owned_thread(_rename_asset, item, allowed_roots)

    async def _refresh_servers(
        self, renamed: Sequence[tuple[_Owner, AssetRenameResult]]
    ) -> None:
        """Ask the media server to reload each item whose files were renamed.

        Only the item-level assets that now carry their canonical name are
        unlocked; a season poster is the season's, so it unlocks nothing on
        the item. A refresh does not prove the server adopted the file.
        """
        assets: dict[str, set[ServerAsset]] = {}
        for owner, outcome in renamed:
            if owner.server_item_id is None:
                continue
            unlock = assets.setdefault(owner.server_item_id, set())
            stem = Path(outcome.suggested_path or "").stem
            if owner.item_folder and (asset := _ITEM_FOLDER_ASSETS.get(stem)):
                unlock.add(asset)
        for server_item_id, unlock in assets.items():
            try:
                await self._providers.provider.refresh_item(
                    server_item_id, unlock=unlock
                )
            except MediaServerError as exc:
                logger.warning(
                    "Could not refresh server item %s after a rename: %s",
                    server_item_id,
                    public_error_message(exc),
                )

    async def rename_assets(
        self,
        body: RenameRequest,
    ) -> AssetRenameResponse:
        """Rename selected assets and persist their outcomes in the scan snapshot."""
        stale_message = "Asset scan results are stale; reopen the popup"
        await require_snapshot_keys(
            self._jobs.asset_scan,
            body.snapshot_finished_at,
            collection="issues",
            database=self._database,
            requested=(
                (item.current_path, item.suggested_path) for item in body.renames
            ),
            row_key=lambda row: (row.get("current_path"), row.get("suggested_path")),
            stale_message=stale_message,
        )
        allowed_roots = await require_trusted_media_roots(self._database)
        owners = await self._owners(item.current_path for item in body.renames)
        outcomes = [
            await self._rename_one(item, owners[item.current_path], allowed_roots)
            for item in body.renames
        ]
        results = [result for _, result in outcomes]
        renamed = [
            (owner, result)
            for owner, result in outcomes
            if result.status is RenameStatus.RENAMED and owner.item_id is not None
        ]
        if renamed:
            await self._local_assets.reconcile(
                item_ids={owner.item_id for owner, _ in renamed if owner.item_id},
                source="assets.rename",
            )
            await self._refresh_servers(renamed)
        response = AssetRenameResponse(results=results)
        await patch_snapshot(
            self._jobs.asset_scan,
            body.snapshot_finished_at,
            collection="issues",
            database=self._database,
            publisher=self._publisher,
            patcher=lambda payload: patch_rename_snapshot(payload, results),
        )
        return response
