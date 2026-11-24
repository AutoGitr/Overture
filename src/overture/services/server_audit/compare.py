"""Server-audit runs: planning every target, auditing each, and reporting them."""

lazy from contextlib import aclosing
lazy from dataclasses import replace
lazy from datetime import date

lazy import httpx2
lazy from sqlalchemy.exc import SQLAlchemyError

lazy from ...jobs.runner import JobContext, run_managed_job
lazy from ...jobs.tally import ServerAuditTally
lazy from ...schemas.server_audit import (
    ServerAuditRequest,
    ServerAuditResult,
)
lazy from ...utils.concurrency import in_order
lazy from .collection_assets import audit_collection_art, audit_collection_theme
lazy from .context import AuditContext
lazy from .item_art import audit_item_art
lazy from .themes import audit_item_theme
lazy from .work import (
    AuditWork,
    CollectionAuditTarget,
    plan_audit,
    plan_collection_audit,
)

AUDIT_ERRORS = (httpx2.HTTPError, SQLAlchemyError, OSError, ValueError)


#: Targets audited at once. A target mostly waits on the media server, so a
#: few overlap well; fingerprinting stays bounded by ``PHASH_WORKERS``.
AUDIT_CONCURRENCY = 8


async def run_server_audit(
    params: ServerAuditRequest,
    job_context: JobContext,
    *,
    audit_context: AuditContext,
    today: date,
) -> None:
    """Compare local images and themes to active media-server assets.

    *today* is the date where Overture runs, which decides the collections in
    season.

    Every target is planned before the first comparison, so the total is fixed
    from the start.
    """
    tally = ServerAuditTally()

    async with run_managed_job(
        job_context,
        tally,
        database=audit_context.database,
        catch=AUDIT_ERRORS,
    ) as job:
        await job.started()
        # Servers down now are left out rather than reported for every target.
        audit_context = replace(
            audit_context,
            servers=frozenset(
                provider.server_id
                for provider in await audit_context.provider_registry.reachable()
            ),
        )
        targets: list[AuditWork] = list(
            await plan_audit(
                params,
                audit_context.local_assets,
                database=audit_context.database,
                read=job.read,
            )
        )
        if params.check_collections:
            collections = await plan_collection_audit(
                params, database=audit_context.database, today=today
            )
            targets.extend(collections)
            await job.read(len(collections))
        await job.planned(len(targets))
        async with aclosing(
            in_order(
                targets,
                lambda target: audit_target(target, context=audit_context),
                limit=AUDIT_CONCURRENCY,
            )
        ) as audited:
            async for target, results in audited:
                if job.stop_requested():
                    break
                # One line per server compared; the last one finishes the target.
                for index, result in enumerate(results, start=1):
                    await job.report(
                        result.status.outcome,
                        f"{result.title or _owner(target)} ({target.asset})",
                        result.reason or result.status,
                        finished=index == len(results),
                        server=result.log_server,
                        results=tally.collect(*differences([result])),
                    )


def _owner(target: AuditWork) -> str:
    """Name a target's owner when its title is unknown."""
    if isinstance(target, CollectionAuditTarget):
        return f"collection {target.collection_id}"
    return f"item {target.item_id}"


async def audit_target[T: AuditWork](
    target: T, *, context: AuditContext
) -> tuple[T, list[ServerAuditResult]]:
    """Audit one target; return it with one result per server asset compared.

    A target whose results all match is one the server shows exactly.
    """
    if isinstance(target, CollectionAuditTarget):
        if (art_type := target.asset.art_type) is None:
            return target, await audit_collection_theme(target, context=context)
        return target, await audit_collection_art(target, art_type, context=context)
    if target.art_type is None:
        return target, await audit_item_theme(target, context=context)
    return target, await audit_item_art(target, target.art_type, context=context)


def differences(results: list[ServerAuditResult]) -> list[ServerAuditResult]:
    """Return the results whose server asset differs from the local file."""
    return [result for result in results if not result.status.matched]
