"""Fix server-audit findings, then wait until the media server shows the fix.

A media server queues a refresh and answers at once, so an accepted request
says nothing about what the server shows. Each fixed file is audited again
until it matches, and only then is its row marked fixed.
"""

lazy import asyncio
lazy import time
lazy from collections import defaultdict
lazy from collections.abc import Awaitable, Callable, Mapping, Sequence
lazy from contextlib import aclosing, suppress
lazy from dataclasses import dataclass, field
lazy from typing import Any

lazy from sqlmodel import col, select

lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...db.session import Database
lazy from ...domain import ServerAsset
lazy from ...jobs.progress_log import JobOutcome
lazy from ...jobs.runner import JobContext, ManagedJob, run_managed_job
lazy from ...jobs.tally import ServerAuditFixTally
lazy from ...media_servers.errors import MediaServerError
lazy from ...schemas.server_audit import (
    ServerAuditRefreshTarget,
    ServerAuditThemeDeleteTarget,
)
lazy from ...utils.concurrency import in_order
lazy from ...utils.errors import public_error_message
lazy from ..art.targets import target_label
lazy from ..server_identity import resolve_owner_server_id
lazy from .compare import (
    AUDIT_CONCURRENCY,
    AUDIT_ERRORS,
    AuditContext,
    audit_target,
    differences,
)
lazy from .work import AuditTarget

#: Seconds between audits of the fixed files the server does not show yet.
CHECK_INTERVAL_SECONDS = 10.0
#: Seconds the server may go without showing another fixed file before the
#: rest are reported unchanged. A server works through its refresh queue one
#: item at a time, so a large selection keeps settling for as long as it
#: makes progress.
IDLE_TIMEOUT_SECONDS = 180.0

#: One audit result row: ``("art", item, season, type)`` or
#: ``("theme", item, server item, theme)``.
type AuditRowKey = tuple[str, object, object, object]


def audit_row_key(
    row: Mapping[str, Any] | ServerAuditRefreshTarget | ServerAuditThemeDeleteTarget,
) -> AuditRowKey:
    """Return the stable key shared by audit result rows and fix targets."""

    def value(name: str) -> object:
        if isinstance(row, dict):
            return row.get(name)
        return getattr(row, name, None)

    if value("theme_id") is not None or value("server_item_id") is not None:
        return ("theme", value("item_id"), value("server_item_id"), value("theme_id"))
    return ("art", value("item_id"), value("season_id"), value("art_type"))


@dataclass(slots=True, frozen=True)
class RowFix:
    """Where a fix of one audit row stands: under way, verified or failed."""

    verified: bool = False
    error: str | None = None


#: A fix is under way, so the row's earlier outcome no longer applies.
PENDING = RowFix()
VERIFIED = RowFix(verified=True)

#: Records fix outcomes on the audit rows they name.
type MarkRows = Callable[[Mapping[AuditRowKey, RowFix]], Awaitable[None]]


def patch_audit_snapshot(
    payload: dict[str, Any], fixes: Mapping[AuditRowKey, RowFix]
) -> dict[str, Any]:
    """Apply fix outcomes to the audit snapshot rows they name."""
    rows: list[dict[str, Any]] = payload.get("results") or []
    for row in rows:
        fix = fixes.get(audit_row_key(row))
        if fix is None:
            continue
        row.pop("refresh_error", None)
        if fix.verified:
            row["refreshed"] = True
        elif fix.error is not None:
            row["refresh_error"] = fix.error
    return payload


@dataclass(slots=True, eq=False)
class _Fix:
    """One audited file being fixed, and the result rows it settles."""

    item_id: int
    asset: ServerAsset
    season_id: int | None = None
    server_id: str | None = None
    theme_ids: list[str] = field(default_factory=list[str])
    rows: list[AuditRowKey] = field(default_factory=list[AuditRowKey])
    label: str = ""
    error: str | None = None
    #: How the latest audit found the server to differ.
    difference: str = ""

    @property
    def target(self) -> AuditTarget:
        """Return the audit target that checks this fix."""
        return AuditTarget(self.item_id, self.asset.art_type, self.season_id)


def _plan(
    art: Sequence[ServerAuditRefreshTarget],
    themes: Sequence[ServerAuditThemeDeleteTarget],
) -> list[_Fix]:
    """Return one fix per file; every server theme of an item is one fix."""
    fixes: dict[object, _Fix] = {}
    for target in art:
        key = audit_row_key(target)
        fixes[key] = _Fix(
            target.item_id, target.art_type.server_asset, target.season_id, rows=[key]
        )
    for target in themes:
        fix = fixes.setdefault(
            ("theme", target.item_id),
            _Fix(target.item_id, ServerAsset.THEME, server_id=target.server_item_id),
        )
        fix.rows.append(audit_row_key(target))
        if target.theme_id:
            fix.theme_ids.append(target.theme_id)
    return list(fixes.values())


async def _label(fixes: Sequence[_Fix], database: Database) -> None:
    """Name each fix for the log, and fail those whose item is gone."""
    async with database.read_session() as session:
        items = {
            item.id: item
            for item in await session.exec(
                select(MediaItem).where(
                    col(MediaItem.id).in_({fix.item_id for fix in fixes})
                )
            )
        }
        seasons = {
            season.id: season
            for season in await session.exec(
                select(Season).where(
                    col(Season.id).in_(
                        {fix.season_id for fix in fixes if fix.season_id is not None}
                    )
                )
            )
        }
    for fix in fixes:
        item = items.get(fix.item_id)
        if item is None:
            fix.label = f"item {fix.item_id} ({fix.asset})"
            fix.error = "Item not found"
            continue
        season = seasons.get(fix.season_id) if fix.season_id is not None else None
        fix.label = f"{target_label(item, season=season)} ({fix.asset})"


async def _apply(fixes: Sequence[_Fix], context: AuditContext) -> None:
    """Delete the selected server themes, then unlock and refresh each item once."""
    provider = context.provider_registry.provider
    refreshes: defaultdict[str, list[_Fix]] = defaultdict(list)
    for fix in fixes:
        if fix.error is not None:
            continue
        try:
            fix.server_id = fix.server_id or await resolve_owner_server_id(
                fix.item_id,
                fix.season_id if fix.asset is ServerAsset.SEASON_POSTER else None,
                database=context.database,
                provider_registry=context.provider_registry,
            )
            if fix.server_id is None:
                fix.error = "Could not resolve media-server item ID"
                continue
            for theme_id in fix.theme_ids:
                await provider.delete_theme(fix.server_id, theme_id)
        except MediaServerError as exc:
            fix.error = public_error_message(exc)
        if fix.error is None and fix.server_id is not None:
            refreshes[fix.server_id].append(fix)

    for server_id, group in refreshes.items():
        try:
            await provider.refresh_item(server_id, unlock={fix.asset for fix in group})
        except MediaServerError as exc:
            for fix in group:
                fix.error = public_error_message(exc)


async def _difference(fix: _Fix, context: AuditContext) -> tuple[_Fix, str | None]:
    """Audit the fixed file again; return how the server differs, or ``None``."""
    try:
        _, results = await audit_target(fix.target, context=context)
    except AUDIT_ERRORS as exc:
        return fix, public_error_message(exc)
    if not (differing := differences(results)):
        return fix, None
    return fix, differing[0].reason or differing[0].status


async def _pause(job: ManagedJob[ServerAuditFixTally], seconds: float) -> None:
    """Wait *seconds*, or until the run is asked to stop."""
    with suppress(TimeoutError):
        await asyncio.wait_for(job.context.stop_event.wait(), seconds)


async def _verify(
    fixes: list[_Fix],
    job: ManagedJob[ServerAuditFixTally],
    context: AuditContext,
    mark: MarkRows,
) -> None:
    """Audit the fixed files until the server shows them, or stops changing."""
    pending = fixes
    changed_at = time.monotonic()
    while pending:
        await _pause(job, CHECK_INTERVAL_SECONDS)
        if job.stop_requested():
            return
        verified: list[_Fix] = []
        differing: list[_Fix] = []
        async with aclosing(
            in_order(
                pending,
                lambda fix: _difference(fix, context),
                limit=AUDIT_CONCURRENCY,
            )
        ) as audited:
            async for fix, difference in audited:
                if difference is None:
                    verified.append(fix)
                    await job.report(
                        JobOutcome.MATCHED,
                        fix.label,
                        "media server now shows the local file",
                    )
                else:
                    fix.difference = difference
                    differing.append(fix)
        pending = differing
        if verified:
            changed_at = time.monotonic()
            await mark({row: VERIFIED for fix in verified for row in fix.rows})
        elif time.monotonic() - changed_at >= IDLE_TIMEOUT_SECONDS:
            break

    unchanged = {
        fix: f"Still differs after refresh: {fix.difference}" for fix in pending
    }
    for fix, reason in unchanged.items():
        await job.report(JobOutcome.MISMATCH, fix.label, reason)
    await mark(
        {
            row: RowFix(error=reason)
            for fix, reason in unchanged.items()
            for row in fix.rows
        }
    )


async def run_audit_fix(
    art: Sequence[ServerAuditRefreshTarget],
    themes: Sequence[ServerAuditThemeDeleteTarget],
    job_context: JobContext,
    *,
    audit_context: AuditContext,
    mark: MarkRows,
) -> None:
    """Fix the selected findings, then verify each against the media server.

    Every targeted row is first marked pending, so an outcome from an earlier
    fix stops showing; each then settles as verified, unchanged or failed.
    """
    tally = ServerAuditFixTally()
    async with run_managed_job(job_context, tally, catch=AUDIT_ERRORS) as job:
        await job.started()
        fixes = _plan(art, themes)
        await _label(fixes, audit_context.database)
        await job.planned(len(fixes))
        await mark({row: PENDING for fix in fixes for row in fix.rows})
        await _apply(fixes, audit_context)

        failed = {fix: fix.error for fix in fixes if fix.error is not None}
        for fix, error in failed.items():
            await job.report(JobOutcome.ERROR, fix.label, error)
        await mark(
            {
                row: RowFix(error=error)
                for fix, error in failed.items()
                for row in fix.rows
            }
        )
        await _verify(
            [fix for fix in fixes if fix.error is None], job, audit_context, mark
        )
