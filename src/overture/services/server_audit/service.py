"""Server audit route-facing service operations."""

lazy from collections.abc import Mapping, Sequence
lazy from pathlib import Path

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.session import Database
lazy from ...integrations.proxy import ProxyClientManager
lazy from ...media_servers.registry import ProviderRegistry
lazy from ...schemas.common import StatusResponse
lazy from ...schemas.server_audit import (
    FixAuditRequest,
    ServerAuditRefreshTarget,
    ServerAuditRequest,
    ServerAuditThemeDeleteTarget,
)
lazy from ...ws.state import BackgroundJobRegistry
lazy from ..art.phash import PhashService
lazy from ..job_snapshots import patch_snapshot, require_snapshot_keys
lazy from ..local_assets.service import LocalAssets
lazy from ..storage.trusted_roots import validate_folders_under_trusted_roots
lazy from .compare import AuditContext, run_server_audit
lazy from .fix import (
    AuditRowKey,
    RowFix,
    audit_row_key,
    patch_audit_snapshot,
    run_audit_fix,
)


class ServerAuditService:
    """Consolidated server audit domain service."""

    def __init__(
        self,
        *,
        background_jobs: BackgroundJobRegistry,
        provider_registry: ProviderRegistry,
        local_assets: LocalAssets,
        phash: PhashService,
        image_clients: ProxyClientManager,
        publisher: protocols.EventPublisher,
        app_config: Settings,
        database: Database,
        config_dir: Path,
    ) -> None:
        self._jobs = background_jobs
        self._provider_registry = provider_registry
        self._local_assets = local_assets
        self._phash = phash
        self._image_clients = image_clients
        self._publisher = publisher
        self._config = app_config
        self._database = database
        self._config_dir = config_dir

    def _audit_context(self) -> AuditContext:
        return AuditContext(
            provider_registry=self._provider_registry,
            asset_storage=self._local_assets.asset_storage,
            local_assets=self._local_assets,
            phash=self._phash,
            image_clients=self._image_clients,
            app_config=self._config,
            database=self._database,
            config_dir=self._config_dir,
        )

    async def start(
        self,
        body: ServerAuditRequest,
    ) -> StatusResponse:
        """Start an audit comparing local assets to media-server state."""
        await validate_folders_under_trusted_roots(
            self._database, body.movie_folders + body.show_folders
        )

        audit_context = self._audit_context()
        return StatusResponse.start(
            self._jobs.library_gate.start(
                "audit",
                self._jobs.server_audit,
                lambda context: run_server_audit(
                    body, context, audit_context=audit_context
                ),
            )
        )

    def stop(self) -> StatusResponse:
        """Stop a running server audit."""
        return StatusResponse.stop(self._jobs.server_audit.request_stop())

    async def fix(self, body: FixAuditRequest) -> StatusResponse:
        """Start fixing selected findings in one run, then verify each.

        Images are unlocked and refreshed; themes have their server theme
        deleted before their item is refreshed.
        """
        await self._require_current_snapshot(
            body.snapshot_finished_at, [*body.targets, *body.themes]
        )
        return self._start_fix(
            body.snapshot_finished_at, art=body.targets, themes=body.themes
        )

    def stop_fix(self) -> StatusResponse:
        """Stop fixing audit findings; rows not yet settled keep no outcome."""
        return StatusResponse.stop(self._jobs.server_audit_fix.request_stop())

    async def _require_current_snapshot(
        self,
        snapshot_finished_at: str,
        targets: Sequence[ServerAuditRefreshTarget | ServerAuditThemeDeleteTarget],
    ) -> None:
        """Reject actions not present in the named server-audit result view."""
        await require_snapshot_keys(
            self._jobs.server_audit,
            snapshot_finished_at,
            collection="results",
            database=self._database,
            requested=(audit_row_key(target) for target in targets),
            row_key=audit_row_key,
            stale_message="Server audit results are stale; reopen the popup",
        )

    def _start_fix(
        self,
        snapshot_finished_at: str,
        *,
        art: Sequence[ServerAuditRefreshTarget],
        themes: Sequence[ServerAuditThemeDeleteTarget],
    ) -> StatusResponse:
        """Fix findings in the background, marking rows of the named snapshot."""

        async def mark(fixes: Mapping[AuditRowKey, RowFix]) -> None:
            if fixes:
                await patch_snapshot(
                    self._jobs.server_audit,
                    snapshot_finished_at,
                    collection="results",
                    database=self._database,
                    publisher=self._publisher,
                    patcher=lambda payload: patch_audit_snapshot(payload, fixes),
                )

        audit_context = self._audit_context()
        return StatusResponse.start(
            self._jobs.library_gate.start(
                "audit",
                self._jobs.server_audit_fix,
                lambda context: run_audit_fix(
                    art, themes, context, audit_context=audit_context, mark=mark
                ),
            )
        )
