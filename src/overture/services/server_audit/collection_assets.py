"""Server-audit comparison of the images and themes Overture holds for collections."""

lazy import logging
lazy from collections.abc import Callable

lazy from ...db.ledger import (
    Destination,
    Evidence,
    delivery,
    file_facts,
    observe,
    read_asset,
    record_file,
)
lazy from ...db.models.asset import Asset
lazy from ...db.models.media_collection import MediaCollection
lazy from ...domain import ArtType, DeliveryChannel, ServerAsset
lazy from ...media_servers.registry import Provider
lazy from ...repositories.collections import CollectionRepository
lazy from ...schemas.server_audit import (
    AuditStatus,
    ServerAuditResult,
)
lazy from ...utils.assets import THEME_FILENAME
lazy from ...utils.audio import ffprobe_duration
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.threads import owned_thread
lazy from ...utils.time import utc_now
lazy from ..collections.destinations import collection_destinations
lazy from ..collections.theme_files import collection_folder, inspect_theme_file
lazy from ..downloads.collection_theme import copy_part
lazy from ..server_copies import READ_ERRORS
lazy from .context import AuditContext, finding, for_server, image_finding
lazy from .themes import (
    different_file_reason,
)
lazy from .work import (
    CollectionAuditTarget,
)

logger = logging.getLogger(__name__)


async def audit_collection_art(
    target: CollectionAuditTarget,
    art_type: ArtType,
    *,
    context: AuditContext,
) -> list[ServerAuditResult]:
    """Audit the image Overture uploaded to a collection against each server copy."""
    result = ServerAuditResult(
        kind="art",
        collection_id=target.collection_id,
        art_type=art_type.server_asset,
        status=AuditStatus.ERROR,
        title="",
        server_image_present=False,
    )
    async with context.database.read_session() as session:
        row = await CollectionRepository(session).get_listed(target.collection_id)
    if row is None:
        return [result.model_copy(update={"reason": "Collection not found"})]
    result.title = row.title
    try:
        uploaded = await context.collection_art.uploaded(row, art_type)
    except PublicServiceError as exc:
        return [result.model_copy(update={"reason": exc.message})]
    except (OSError, ValueError) as exc:
        return [result.model_copy(update={"reason": str(exc)})]
    if uploaded is None:
        return [
            finding(result, AuditStatus.LOCAL_MISSING, "Overture has uploaded no image")
        ]
    if uploaded.fingerprint is None:
        return [
            result.model_copy(
                update={"reason": "The uploaded image could not be decoded"}
            )
        ]
    destinations = [
        (
            context.provider_registry.get(destination.server_id or 0),
            destination.server_item_id or "",
        )
        for destination in collection_destinations(
            row, target.asset, context.provider_registry
        )
        if context.compared(context.provider_registry.get(destination.server_id or 0))
    ]
    if not destinations:
        return [
            finding(
                result,
                AuditStatus.UNRESOLVED_SERVER_ID,
                "The collection has no server copy",
            )
        ]
    return [
        await _compare_collection_copy(
            for_server(result, provider),
            provider,
            server_item_id,
            uploaded.fingerprint,
            expected_hash=uploaded.content_hash,
            context=context,
        )
        for provider, server_item_id in destinations
    ]


async def _compare_collection_copy(
    result: ServerAuditResult,
    provider: Provider,
    server_item_id: str,
    phash: str,
    *,
    expected_hash: str,
    context: AuditContext,
) -> ServerAuditResult:
    """Compare one server copy's image with the one Overture uploaded, and record it.

    What the copy shows is recorded as a sync records it, so the collection's
    status follows what the audit found.
    """
    art_type = ArtType(result.art_type)
    result.server_item_id = server_item_id
    copy = Destination(provider.server_id, server_item_id, DeliveryChannel.UPLOAD)
    server_url = await provider.get_collection_image_url(server_item_id, art_type)
    if not server_url:
        await _record(
            context,
            result,
            copy,
            Evidence.DIFFERENT,
            expected_hash=expected_hash,
            ref=None,
        )
        return finding(
            result,
            AuditStatus.SERVER_MISSING,
            f"{provider.server.title} has no {art_type.label} for it",
        )
    result.server_image_present = True
    copies = context.server_copies
    try:
        server_phash = await copies.collection_image(
            provider, server_item_id, art_type, server_url
        )
    except READ_ERRORS as exc:
        return result.model_copy(update={"reason": str(exc)})
    found = image_finding(result, copies, phash, server_phash)
    evidence = (
        Evidence.SAME if found.status is AuditStatus.PHASH_MATCH else Evidence.DIFFERENT
    )
    await _record(
        context,
        result,
        copy,
        evidence,
        expected_hash=expected_hash,
        ref=server_url,
    )
    return found


def _asset_snapshot(asset: Asset) -> tuple[object, list[tuple[object, ...]]]:
    return (
        asset.status,
        [
            (
                d.server_id,
                d.channel,
                d.observed_hash,
                d.observed_ref,
                d.file_mtime_ns,
                d.file_size,
            )
            for d in asset.deliveries
        ],
    )


async def _record_collection(
    context: AuditContext,
    collection_id: int,
    kind: ServerAsset,
    *,
    expected_hash: str,
    apply: Callable[[MediaCollection], object],
) -> None:
    """Persist an observation on a collection's asset if its content is unchanged."""
    changed = False
    async with (
        context.asset_storage.asset_locks.acquire(f"collection:{collection_id}"),
        context.database.write_session() as session,
    ):
        row = await CollectionRepository(session).get(collection_id)
        if row is None:
            return
        asset = read_asset(row, kind)
        if asset.content_hash != expected_hash:
            return
        before = _asset_snapshot(asset)
        apply(row)
        after = _asset_snapshot(read_asset(row, kind))
        changed = after != before
        if changed:
            session.add(row)
    if changed:
        await context.publisher.broadcast(
            "collection.updated", {"collection_id": collection_id, "titles": False}
        )


async def _record(
    context: AuditContext,
    result: ServerAuditResult,
    copy: Destination,
    evidence: Evidence,
    *,
    expected_hash: str,
    ref: str | None,
) -> None:
    """Record what a collection's copy was found to show, if content is unchanged."""
    await _record_collection(
        context,
        result.collection_id or 0,
        result.art_type,
        expected_hash=expected_hash,
        apply=lambda row: observe(
            row, result.art_type, copy, evidence, ref=ref, at=utc_now()
        ),
    )


async def audit_collection_theme(
    target: CollectionAuditTarget, *, context: AuditContext
) -> list[ServerAuditResult]:
    """Audit the theme Overture holds for a collection against each server copy."""
    result = ServerAuditResult(
        kind="theme",
        collection_id=target.collection_id,
        art_type=ServerAsset.THEME,
        status=AuditStatus.ERROR,
        title="",
    )
    async with context.database.read_session() as session:
        row = await CollectionRepository(session).get_listed(target.collection_id)
    if row is None:
        return [result.model_copy(update={"reason": "Collection not found"})]
    result.title = row.title
    asset = read_asset(row, ServerAsset.THEME)
    expected_hash = asset.content_hash
    if expected_hash is None:
        return [
            finding(result, AuditStatus.LOCAL_MISSING, "Overture holds no theme for it")
        ]
    destinations = [
        destination
        for destination in collection_destinations(
            row, ServerAsset.THEME, context.provider_registry
        )
        if context.compared(context.provider_registry.get(destination.server_id or 0))
    ]
    if not destinations:
        return [
            finding(
                result,
                AuditStatus.UNRESOLVED_SERVER_ID,
                "The collection has no server copy",
            )
        ]
    results: list[ServerAuditResult] = []
    for destination in destinations:
        provider = context.provider_registry.get(destination.server_id or 0)
        on_server = for_server(result, provider)
        on_server.server_item_id = destination.server_item_id
        if destination.channel is DeliveryChannel.UPLOAD:
            found = await _audit_uploaded_collection_theme(
                on_server,
                asset,
                destination,
                provider,
                expected_hash=expected_hash,
                context=context,
            )
        else:
            found = await _audit_folder_collection_theme(
                on_server,
                row,
                asset,
                destination,
                provider,
                expected_hash=expected_hash,
                context=context,
            )
        results.append(found)
    return results


async def _audit_uploaded_collection_theme(
    result: ServerAuditResult,
    asset: Asset,
    destination: Destination,
    provider: Provider,
    *,
    expected_hash: str,
    context: AuditContext,
) -> ServerAuditResult:
    server_themes = await provider.get_theme_songs(destination.server_item_id or "")
    if not server_themes:
        await _record(
            context,
            result,
            destination,
            Evidence.DIFFERENT,
            expected_hash=expected_hash,
            ref=None,
        )
        return finding(
            result,
            AuditStatus.THEME_SERVER_MISSING,
            f"{provider.server.title} has no theme for it",
            local_duration=asset.duration,
        )
    theme = server_themes[0]
    result = result.model_copy(
        update={
            "server_duration": theme.duration,
            "theme_id": theme.id,
            "theme_title": theme.title,
        }
    )
    if theme.url is None or asset.fingerprint is None:
        reason = (
            "Media server did not report the theme's URL"
            if theme.url is None
            else "The uploaded theme has no audio fingerprint"
        )
        return finding(
            result,
            AuditStatus.THEME_UNKNOWN,
            reason,
            local_duration=asset.duration,
        )
    try:
        served = await context.server_copies.served_theme(
            provider, theme.url, compared_with=asset.fingerprint
        )
    except READ_ERRORS as exc:
        logger.debug("Could not download the collection theme: %s", exc)
        return finding(
            result,
            AuditStatus.THEME_UNKNOWN,
            "Could not download the media-server theme",
            local_duration=asset.duration,
        )
    if served.audio_hash is None:
        return finding(
            result,
            AuditStatus.THEME_UNKNOWN,
            "Could not read the media-server theme audio",
            local_duration=asset.duration,
        )
    if served.audio_hash == asset.fingerprint:
        await _record(
            context,
            result,
            destination,
            Evidence.SAME,
            expected_hash=expected_hash,
            ref=theme.id,
        )
        return finding(result, AuditStatus.THEME_MATCH, "Same audio")
    await _record(
        context,
        result,
        destination,
        Evidence.DIFFERENT,
        expected_hash=expected_hash,
        ref=theme.id,
    )
    return finding(
        result,
        AuditStatus.THEME_MISMATCH,
        different_file_reason(served.duration, asset.duration),
        local_duration=asset.duration,
        server_duration=served.duration,
    )


async def _audit_folder_collection_theme(
    result: ServerAuditResult,
    row: MediaCollection,
    asset: Asset,
    destination: Destination,
    provider: Provider,
    *,
    expected_hash: str,
    context: AuditContext,
) -> ServerAuditResult:
    part = copy_part(row, destination)
    try:
        folder = await owned_thread(
            collection_folder, provider.server, part.server_path
        )
    except (OSError, ValueError) as exc:
        return finding(result, AuditStatus.ERROR, str(exc))
    theme_path = folder / THEME_FILENAME
    result.local_path = str(theme_path)
    try:
        facts = await owned_thread(
            inspect_theme_file, folder, file_facts(delivery(asset, destination))
        )
    except (OSError, ValueError) as exc:
        return finding(
            result,
            AuditStatus.THEME_UNKNOWN,
            str(exc),
            local_duration=asset.duration,
        )
    await _record_collection(
        context,
        result.collection_id or 0,
        ServerAsset.THEME,
        expected_hash=expected_hash,
        apply=lambda current: record_file(
            current, ServerAsset.THEME, facts, destination=destination, at=utc_now()
        ),
    )
    if facts is None:
        return finding(
            result,
            AuditStatus.THEME_SERVER_MISSING,
            f"{provider.server.title} has no theme file in {folder.name}",
            local_duration=asset.duration,
        )
    if facts.file_hash == expected_hash:
        return finding(result, AuditStatus.THEME_MATCH, "Same file")
    server_duration = (
        facts.duration
        if facts.duration is not None
        else await ffprobe_duration(theme_path)
    )
    return finding(
        result,
        AuditStatus.THEME_MISMATCH,
        different_file_reason(server_duration, asset.duration),
        local_duration=asset.duration,
        server_duration=server_duration,
    )
