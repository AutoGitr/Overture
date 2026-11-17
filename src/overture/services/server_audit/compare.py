"""Server-audit comparison and lifecycle services."""

lazy import logging
lazy from contextlib import aclosing
lazy from dataclasses import dataclass, replace
lazy from pathlib import Path

lazy import httpx2
lazy from sqlalchemy.exc import SQLAlchemyError

lazy from ...config import Settings
lazy from ...db.art_slots import ArtFileFacts, art_file_facts, find_art_slot
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...db.session import Database
lazy from ...db.theme_file import ThemeFileFacts, theme_file_facts
lazy from ...domain import ArtType, ServerAsset
lazy from ...integrations.proxy import ProxyClientManager
lazy from ...jobs.runner import JobContext, run_managed_job
lazy from ...jobs.tally import ServerAuditTally
lazy from ...media_servers.adapters import ServerTheme
lazy from ...media_servers.registry import Provider, ProviderRegistry
lazy from ...repositories.collections import CollectionRepository
lazy from ...repositories.seasons import SeasonRepository
lazy from ...schemas.server_audit import (
    AuditStatus,
    ServerAuditRequest,
    ServerAuditResult,
)
lazy from ...utils.audio import audio_hash, downloaded_audio, ffprobe_duration
lazy from ...utils.concurrency import in_order
lazy from ...utils.image import fetch_image
lazy from ...utils.threads import owned_thread
lazy from ..art.collection_art import CollectionArtService
lazy from ..art.phash import PhashService
lazy from ..art.targets import target_label
lazy from ..local_assets.service import LocalAssets
lazy from ..server_identity import ServerCopy, resolve_art_owners, resolve_owners
lazy from ..storage.assets import AssetStorage, require_folder_path
lazy from .work import (
    AuditTarget,
    AuditWork,
    CollectionAuditTarget,
    plan_audit,
    plan_collection_audit,
)

logger = logging.getLogger(__name__)

THEME_AUDIO_DURATION_TOLERANCE_SECONDS = 3

AUDIT_ERRORS = (httpx2.HTTPError, SQLAlchemyError, OSError, ValueError)

#: Targets audited at once. A target mostly waits on the media server, so a
#: few overlap well; fingerprinting stays bounded by ``PHASH_WORKERS``.
AUDIT_CONCURRENCY = 8


@dataclass(slots=True, frozen=True)
class AuditContext:
    """Collaborator container for server audit execution."""

    provider_registry: ProviderRegistry
    asset_storage: AssetStorage
    local_assets: LocalAssets
    phash: PhashService
    image_clients: ProxyClientManager
    app_config: Settings
    database: Database
    config_dir: Path
    collection_art: CollectionArtService
    #: The database's numbers of the servers a run compares with, those that
    #: answered when it started; every configured server when ``None``.
    servers: frozenset[int] | None = None

    def compared(self, provider: Provider) -> bool:
        return self.servers is None or provider.server_id in self.servers


def _on(result: ServerAuditResult, provider: Provider) -> ServerAuditResult:
    """*result*, about the copy on *provider*'s server."""
    return result.model_copy(
        update={"server_id": provider.server_id, "server": provider.server.title}
    )


def _finding(
    result: ServerAuditResult, status: AuditStatus, reason: str, **fields: object
) -> ServerAuditResult:
    """Return *result* with what the audit found, and why."""
    return result.model_copy(update={"status": status, "reason": reason, **fields})


async def _audit_art_one(
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
        return [
            _finding(result, AuditStatus.LOCAL_MISSING, "Local art file is missing")
        ]
    result.local_path = str(local_path)
    slot = find_art_slot(season or item, art_type)

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
            _finding(
                result,
                AuditStatus.UNRESOLVED_SERVER_ID,
                "Could not resolve media-server item ID",
            )
        ]
    try:
        local_phash = await local_fingerprint(
            local_path,
            Path(require_folder_path(item)),
            art_file_facts(slot) if slot is not None else None,
            context,
        )
    except (OSError, ValueError) as exc:
        return [result.model_copy(update={"reason": str(exc)})]
    return [
        await _compare_server_art(
            _on(result, server_copy.provider),
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
        return _finding(
            result,
            AuditStatus.SERVER_MISSING,
            "Media server has no active image for this art type",
        )
    result.server_image_present = True
    try:
        image = await fetch_image(
            server_url,
            await context.image_clients.get_client(server_url),
            allow_generic_image=True,
            allow_private=True,
            headers=server_copy.provider.get_download_headers(server_url),
        )
        server_phash = await context.phash.compute_from_bytes(image.data)
        distance = context.phash.hamming_distance(local_phash, server_phash)
    except (httpx2.HTTPError, OSError, ValueError) as exc:
        return result.model_copy(update={"reason": str(exc)})
    if distance == 0:
        return _finding(result, AuditStatus.PHASH_MATCH, "d=0 visual match", hamming=0)
    return _finding(
        result, AuditStatus.PHASH_MISMATCH, f"d={distance}", hamming=distance
    )


async def _audit_collection_art(
    target: CollectionAuditTarget, *, context: AuditContext
) -> list[ServerAuditResult]:
    """Audit the image Overture uploaded to a collection against each server copy."""
    art_type = target.art_type
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
    slot = find_art_slot(row, art_type)
    if slot is None or slot.file_hash is None:
        return [
            _finding(
                result, AuditStatus.LOCAL_MISSING, "Overture has uploaded no image"
            )
        ]
    if slot.phash is None:
        return [
            result.model_copy(
                update={"reason": "The uploaded image has no fingerprint"}
            )
        ]
    copies = [
        (context.provider_registry.get(part.server_id), part.server_item_id or "")
        for part in row.copies
        if context.provider_registry.configured_server_id(part.server_id)
    ]
    copies = [
        (provider, copy) for provider, copy in copies if context.compared(provider)
    ]
    if not copies:
        return [
            _finding(
                result,
                AuditStatus.UNRESOLVED_SERVER_ID,
                "The collection has no server copy",
            )
        ]
    return [
        await _compare_collection_copy(
            _on(result, provider), provider, server_item_id, slot.phash, context=context
        )
        for provider, server_item_id in copies
    ]


async def _compare_collection_copy(
    result: ServerAuditResult,
    provider: Provider,
    server_item_id: str,
    phash: str,
    *,
    context: AuditContext,
) -> ServerAuditResult:
    """Compare one server copy's image with the one Overture uploaded."""
    art_type = ArtType(result.art_type)
    result.server_item_id = server_item_id
    server_url = await provider.get_collection_image_url(server_item_id, art_type)
    if not server_url:
        return _finding(
            result,
            AuditStatus.SERVER_MISSING,
            "Media server has no image for this art type",
        )
    result.server_image_present = True
    try:
        request = await provider.build_collection_image_request(
            server_item_id, art_type, None, current_url=server_url
        )
        image = await fetch_image(
            request.url,
            await context.image_clients.get_client(request.url),
            allow_generic_image=True,
            allow_private=True,
            headers=request.headers,
            params=request.params,
        )
        server_phash = await context.phash.compute_from_bytes(image.data)
        distance = context.phash.hamming_distance(phash, server_phash)
    except (httpx2.HTTPError, OSError, ValueError) as exc:
        return result.model_copy(update={"reason": str(exc)})
    if distance == 0:
        return _finding(result, AuditStatus.PHASH_MATCH, "d=0 visual match", hamming=0)
    return _finding(
        result, AuditStatus.PHASH_MISMATCH, f"d={distance}", hamming=distance
    )


async def local_fingerprint(
    path: Path, root: Path, known: ArtFileFacts | None, context: AuditContext
) -> str:
    """Return the fingerprint of the local file at *path* inside *root*.

    The recorded one is reused if it is current.

    Raises:
        OSError: The file changed or could not be read while it was inspected.
    """
    facts = await context.local_assets.inspector.inspect(path, root, known)
    if not isinstance(facts, ArtFileFacts):
        raise OSError("Local art file changed while it was read")
    if facts.phash is None:
        return await context.phash.compute_from_file(str(path))
    return facts.phash


async def _audit_theme_one(
    target: AuditTarget, *, context: AuditContext
) -> list[ServerAuditResult]:
    """Audit one local theme file against each theme the media server plays."""
    result = ServerAuditResult(
        kind="theme",
        item_id=target.item_id,
        art_type=ServerAsset.THEME,
        status=AuditStatus.ERROR,
        title="",
    )

    async with context.database.read_session() as session:
        item = await session.get(MediaItem, target.item_id)

    if not item:
        return [result.model_copy(update={"reason": "Item not found"})]
    result.title = item.title
    local_path = await owned_thread(context.asset_storage.local_theme_path, item)
    if local_path is None:
        return [
            _finding(result, AuditStatus.LOCAL_MISSING, "Local theme file is missing")
        ]
    result.local_path = str(local_path)
    local = _LocalTheme(local_path, theme_file_facts(item))

    owners = [
        server_copy
        for server_copy in await resolve_owners(
            target.item_id,
            None,
            database=context.database,
            provider_registry=context.provider_registry,
        )
        if context.compared(server_copy.provider)
    ]
    if not owners:
        return [
            _finding(
                result,
                AuditStatus.UNRESOLVED_SERVER_ID,
                "Could not resolve media-server item ID",
                local_duration=await local.duration(),
            )
        ]
    results: list[ServerAuditResult] = []
    for server_copy in owners:
        on_server = _on(result, server_copy.provider)
        on_server.server_item_id = server_copy.server_item_id
        server_themes = await server_copy.provider.get_theme_songs(
            server_copy.server_item_id
        )
        if not server_themes:
            results.append(
                _finding(
                    on_server,
                    AuditStatus.THEME_SERVER_MISSING,
                    "Media server has no theme; refresh can pick up local theme.mp3",
                    local_duration=await local.duration(),
                )
            )
            continue
        results += [
            await _compare_theme(
                on_server, theme, local, server_copy.provider, context=context
            )
            for theme in server_themes
        ]
    return results


@dataclass(slots=True)
class _LocalTheme:
    """The local theme file, read only as far as a comparison needs it."""

    path: Path
    #: What was recorded about the file, reused while it is the same revision.
    known: ThemeFileFacts | None
    _audio_hash: str | None = None
    _hashed: bool = False
    _duration: float | None = None
    _probed: bool = False

    async def audio_hash(self) -> str | None:
        """Return the hash of the file's audio, hashing it once."""
        if not self._hashed:
            self._hashed = True
            self._audio_hash = await audio_hash(self.path)
        return self._audio_hash

    async def duration(self) -> float | None:
        """Return the file's duration: the recorded one if current, else probed once."""
        if not self._probed:
            self._probed = True
            known = self.known
            if known is not None and known.duration is not None:
                try:
                    stat = await owned_thread(self.path.stat)
                except OSError:
                    stat = None
                if stat is not None and (stat.st_mtime_ns, stat.st_size) == (
                    known.file_mtime_ns,
                    known.file_size,
                ):
                    self._duration = known.duration
                    return self._duration
            self._duration = await ffprobe_duration(self.path)
        return self._duration


async def _compare_theme(
    base: ServerAuditResult,
    theme: ServerTheme,
    local: _LocalTheme,
    provider: Provider,
    *,
    context: AuditContext,
) -> ServerAuditResult:
    """Compare one server theme with the local file by what the server plays.

    Plex keeps its own copy of a theme, so the audio it serves is compared
    with the local file's, leaving out tags and other container metadata that
    need not survive the copy. Jellyfin and Emby play the file at the path
    they report, which the server's PATH_MAP gives as Overture sees it, so that
    path is compared with the local one. Durations only describe a difference.
    """
    result = base.model_copy(
        update={
            "server_duration": theme.duration,
            "theme_id": theme.id,
            "theme_title": theme.title,
        }
    )
    if theme.url is not None:
        return await _compare_served_theme(
            result, theme.url, local, provider, context=context
        )
    if theme.path is None:
        return _finding(
            result,
            AuditStatus.THEME_UNKNOWN,
            "Media server did not report the theme's file",
            local_duration=await local.duration(),
        )
    if Path(theme.path) == local.path:
        return _finding(result, AuditStatus.THEME_MATCH, "Same file")
    return await _different_file(result, theme.duration, local)


async def _compare_served_theme(
    result: ServerAuditResult,
    url: str,
    local: _LocalTheme,
    provider: Provider,
    *,
    context: AuditContext,
) -> ServerAuditResult:
    """Compare the audio a server serves for a theme with the local file's."""
    local_hash = await local.audio_hash()
    if local_hash is None:
        return _finding(
            result, AuditStatus.THEME_UNKNOWN, "Could not read the local theme audio"
        )
    try:
        async with downloaded_audio(
            await context.image_clients.get_client(url),
            url,
            provider.get_download_headers(url),
            config_dir=context.config_dir,
        ) as path:
            server_hash = await audio_hash(path)
            if server_hash is None:
                return _finding(
                    result,
                    AuditStatus.THEME_UNKNOWN,
                    "Could not read the media-server theme audio",
                    local_duration=await local.duration(),
                )
            if server_hash == local_hash:
                return _finding(result, AuditStatus.THEME_MATCH, "Same audio")
            server_duration = await ffprobe_duration(path)
    except (httpx2.HTTPError, OSError, ValueError) as exc:
        logger.debug("Could not download the server theme: %s", exc)
        return _finding(
            result,
            AuditStatus.THEME_UNKNOWN,
            "Could not download the media-server theme",
            local_duration=await local.duration(),
        )
    return await _different_file(result, server_duration, local)


async def _different_file(
    result: ServerAuditResult,
    server_duration: float | None,
    local: _LocalTheme,
) -> ServerAuditResult:
    """Return the mismatch for a server theme that is not the local file."""
    local_duration = await local.duration()
    return _finding(
        result,
        AuditStatus.THEME_MISMATCH,
        _different_file_reason(server_duration, local_duration),
        local_duration=local_duration,
        server_duration=server_duration,
    )


def _different_file_reason(
    server_duration: float | None, local_duration: float | None
) -> str:
    """Describe a server theme whose bytes differ from the local file."""
    if server_duration is None or local_duration is None:
        return "Media server plays a different file"
    delta = abs(server_duration - local_duration)
    if delta <= THEME_AUDIO_DURATION_TOLERANCE_SECONDS:
        return "Media server plays a different file of the same length"
    return f"Media server plays a different file; duration differs by {delta:.1f}s"


async def run_server_audit(
    params: ServerAuditRequest,
    job_context: JobContext,
    *,
    audit_context: AuditContext,
) -> None:
    """Compare local images and themes to active media-server assets.

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
        targets: list[AuditWork] = [
            *await plan_audit(
                params, audit_context.local_assets, database=audit_context.database
            ),
            *(
                await plan_collection_audit(params, database=audit_context.database)
                if params.check_collections
                else []
            ),
        ]
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
                result = _reported(results)
                await job.report(
                    result.status.outcome,
                    f"{result.title or _owner(target)} ({target.asset})",
                    result.reason or result.status,
                    results=tally.collect(*differences(results)),
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
        return target, await _audit_collection_art(target, context=context)
    if target.art_type is None:
        return target, await _audit_theme_one(target, context=context)
    return target, await _audit_art_one(target, target.art_type, context=context)


def differences(results: list[ServerAuditResult]) -> list[ServerAuditResult]:
    """Return the results whose server asset differs from the local file."""
    return [result for result in results if not result.status.matched]


def _reported(results: list[ServerAuditResult]) -> ServerAuditResult:
    """Return the result the progress log reports: the first difference, if any."""
    return next(iter(differences(results)), results[0])
