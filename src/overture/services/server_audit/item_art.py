"""Server-audit comparison of a title's or season's images with its local files."""

lazy from pathlib import Path

lazy from ...db.ledger import (
    FileFacts,
    local_file,
    read_asset,
)
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...domain import ArtType
lazy from ...repositories.seasons import SeasonRepository
lazy from ...schemas.server_audit import (
    AuditStatus,
    ServerAuditResult,
)
lazy from ...utils.threads import owned_thread
lazy from ..art.targets import target_label
lazy from ..server_copies import READ_ERRORS
lazy from ..server_identity import ServerCopy, resolve_art_owners
lazy from ..storage.assets import require_folder_path
lazy from .context import AuditContext, finding, for_server, image_finding
lazy from .work import (
    AuditTarget,
)


async def audit_item_art(
    target: AuditTarget, art_type: ArtType, *, context: AuditContext
) -> list[ServerAuditResult]:
    """Audit one local artwork file against each media server holding it."""
    result = ServerAuditResult(
        kind="art",
        item_id=target.item_id,
        season_id=target.season_id,
        art_type=art_type.server_asset,
        status=AuditStatus.ERROR,
        title="",
        server_image_present=False,
    )

    async with context.database.read_session() as session:
        item = await session.get(MediaItem, target.item_id)
        if not item:
            return [result.model_copy(update={"reason": "Item not found"})]
        owner = await SeasonRepository(session).art_owner(
            item, art_type, target.season_id
        )
    season = owner if isinstance(owner, Season) else None
    result.title = target_label(item, season=season)
    local_path = await owned_thread(
        context.asset_storage.find_local_art_path,
        art_type,
        item=item,
        season=season,
    )
    if local_path is None:
        return [finding(result, AuditStatus.LOCAL_MISSING, "Local art file is missing")]
    result.local_path = str(local_path)
    known = local_file(read_asset(season or item, art_type.server_asset))

    owners = [
        server_copy
        for server_copy in await resolve_art_owners(
            target.item_id,
            art_type,
            target.season_id,
            database=context.database,
            provider_registry=context.provider_registry,
        )
        if context.compared(server_copy.provider)
    ]
    if not owners:
        return [
            finding(
                result,
                AuditStatus.UNRESOLVED_SERVER_ID,
                "Could not resolve media-server item ID",
            )
        ]
    try:
        local_phash = await local_fingerprint(
            local_path,
            Path(require_folder_path(item)),
            known,
            context,
        )
    except (OSError, ValueError) as exc:
        return [result.model_copy(update={"reason": str(exc)})]
    return [
        await _compare_server_art(
            for_server(result, server_copy.provider),
            server_copy,
            art_type,
            local_phash,
            context=context,
        )
        for server_copy in owners
    ]


async def _compare_server_art(
    result: ServerAuditResult,
    server_copy: ServerCopy,
    art_type: ArtType,
    local_phash: str,
    *,
    context: AuditContext,
) -> ServerAuditResult:
    """Compare the image one server shows for a slot with the local file."""
    result.server_item_id = server_copy.server_item_id
    server_url = await context.provider_registry.fetch_server_active_art_url(
        server_copy.provider.server_id, server_copy.server_item_id, art_type
    )
    if not server_url:
        return finding(
            result,
            AuditStatus.SERVER_MISSING,
            f"{server_copy.provider.server.title} has no {art_type.label} for it",
        )
    result.server_image_present = True
    copies = context.server_copies
    try:
        server_phash = await copies.item_image(server_copy.provider, server_url)
    except READ_ERRORS as exc:
        return result.model_copy(update={"reason": str(exc)})
    return image_finding(result, copies, local_phash, server_phash)


async def local_fingerprint(
    path: Path, root: Path, known: FileFacts | None, context: AuditContext
) -> str:
    """Return the fingerprint of the local file at *path* inside *root*.

    The recorded one is reused if it is current.

    Raises:
        OSError: The file changed or could not be read while it was inspected.
    """
    facts = await context.local_assets.inspector.inspect(path, root, known)
    if not isinstance(facts, FileFacts):
        raise OSError("Local art file changed while it was read")
    if facts.fingerprint is None:
        return await context.phash.compute_from_file(str(path))
    return facts.fingerprint
