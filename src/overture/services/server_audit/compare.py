"""Server-audit comparison and lifecycle services."""

lazy import logging
lazy from contextlib import aclosing
lazy from dataclasses import dataclass
lazy from pathlib import Path

lazy import httpx2
lazy from sqlalchemy.exc import SQLAlchemyError

lazy from ...config import Settings
lazy from ...db.art_slots import ArtFileFacts, art_file_facts, find_art_slot
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...db.session import Database
lazy from ...domain import ArtType, ServerAsset
lazy from ...integrations.proxy import ProxyClientManager
lazy from ...jobs.progress_log import JobLogEntry, log_entry
lazy from ...jobs.runner import JobContext, run_managed_job
lazy from ...jobs.tally import ServerAuditTally
lazy from ...media_servers.adapters import ServerTheme
lazy from ...media_servers.registry import ProviderRegistry
lazy from ...repositories.seasons import SeasonRepository
lazy from ...schemas.server_audit import (
    AuditStatus,
    ServerAuditRequest,
    ServerAuditResult,
)
lazy from ...utils.audio import audio_hash, downloaded_audio, ffprobe_duration
lazy from ...utils.concurrency import in_order
lazy from ...utils.errors import public_error_message
lazy from ...utils.image import fetch_image
lazy from ...utils.threads import owned_thread
lazy from ..art.phash import PhashService
lazy from ..art.targets import target_label
lazy from ..local_assets.service import LocalAssets
lazy from ..server_identity import resolve_owner_server_id, resolve_server_item_id
lazy from ..storage.assets import AssetStorage
lazy from .work import AuditTarget, plan_audit

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


def _finding(
    result: ServerAuditResult, status: AuditStatus, reason: str, **fields: object
) -> ServerAuditResult:
    """Return *result* with what the audit found, and why."""
    return result.model_copy(update={"status": status, "reason": reason, **fields})


async def _audit_art_one(
    target: AuditTarget, art_type: ArtType, *, context: AuditContext
) -> ServerAuditResult:
    """Audit one local artwork file against the media server."""
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
            return result.model_copy(update={"reason": "Item not found"})
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
        return _finding(result, AuditStatus.LOCAL_MISSING, "Local art file is missing")
    result.local_path = str(local_path)
    slot = find_art_slot(season or item, art_type)

    server_id = await resolve_server_item_id(
        target.item_id,
        art_type,
        target.season_id,
        database=context.database,
        provider_registry=context.provider_registry,
    )
    if not server_id:
        return _finding(
            result,
            AuditStatus.UNRESOLVED_SERVER_ID,
            "Could not resolve media-server item ID",
        )

    server_url = await context.provider_registry.fetch_server_active_art_url(
        server_id,
        art_type,
    )
    if not server_url:
        return _finding(
            result,
            AuditStatus.SERVER_MISSING,
            "Media server has no active image for this art type",
        )
    result.server_image_present = True

    try:
        local_phash = await local_fingerprint(
            local_path, art_file_facts(slot) if slot is not None else None, context
        )
        image = await fetch_image(
            server_url,
            await context.image_clients.get_client(server_url),
            allow_generic_image=True,
            allow_private=True,
            headers=context.provider_registry.provider.get_download_headers(server_url),
        )
        server_phash = await context.phash.compute_from_bytes(image.data)
        distance = context.phash.hamming_distance(local_phash, server_phash)
    except (httpx2.HTTPError, OSError, ValueError) as exc:
        return result.model_copy(update={"reason": public_error_message(exc)})
    if distance == 0:
        return _finding(result, AuditStatus.PHASH_MATCH, "d=0 visual match", hamming=0)
    return _finding(
        result, AuditStatus.PHASH_MISMATCH, f"d={distance}", hamming=distance
    )


async def local_fingerprint(
    path: Path, known: ArtFileFacts | None, context: AuditContext
) -> str:
    """Return the local file's fingerprint, reusing the recorded one if current.

    Raises:
        OSError: The file changed or could not be read while it was inspected.
    """
    facts = await context.local_assets.inspector.inspect(path, known)
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
    local = _LocalTheme(local_path)

    server_item_id = await resolve_owner_server_id(
        target.item_id,
        None,
        database=context.database,
        provider_registry=context.provider_registry,
    )
    if not server_item_id:
        return [
            _finding(
                result,
                AuditStatus.UNRESOLVED_SERVER_ID,
                "Could not resolve media-server item ID",
                local_duration=await local.duration(),
            )
        ]
    result.server_item_id = server_item_id

    server_themes = await context.provider_registry.provider.get_theme_songs(
        server_item_id
    )
    if not server_themes:
        return [
            _finding(
                result,
                AuditStatus.THEME_SERVER_MISSING,
                "Media server has no theme; refresh can pick up local theme.mp3",
                local_duration=await local.duration(),
            )
        ]
    return [
        await _compare_theme(result, theme, local, context=context)
        for theme in server_themes
    ]


@dataclass(slots=True)
class _LocalTheme:
    """The local theme file, read only as far as a comparison needs it."""

    path: Path
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
        """Return the file's duration, probing it once."""
        if not self._probed:
            self._probed = True
            self._duration = await ffprobe_duration(self.path)
        return self._duration


async def _compare_theme(
    base: ServerAuditResult,
    theme: ServerTheme,
    local: _LocalTheme,
    *,
    context: AuditContext,
) -> ServerAuditResult:
    """Compare one server theme with the local file by what the server plays.

    Plex keeps its own copy of a theme, so the audio it serves is compared
    with the local file's, leaving out tags and other container metadata that
    need not survive the copy. Jellyfin and Emby play the file at the path
    they report, and Overture sees media at the server's paths, so that path
    is compared with the local one. Durations only describe a difference.
    """
    result = base.model_copy(
        update={
            "server_duration": theme.duration,
            "theme_id": theme.id,
            "theme_title": theme.title,
        }
    )
    if theme.url is not None:
        return await _compare_served_theme(result, theme.url, local, context=context)
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
            context.provider_registry.provider.get_download_headers(url),
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
        targets = await plan_audit(
            params, audit_context.local_assets, database=audit_context.database
        )
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
                if result.status is AuditStatus.ERROR:
                    tally.errors += 1

                tally.done += 1
                await job.progress(
                    results=tally.collect(*differences(results)),
                    log=_audit_log_entry(target, result),
                )


async def audit_target(
    target: AuditTarget, *, context: AuditContext
) -> tuple[AuditTarget, list[ServerAuditResult]]:
    """Audit one target; return it with one result per server asset compared.

    A target whose results all match is one the server shows exactly.
    """
    if target.art_type is None:
        return target, await _audit_theme_one(target, context=context)
    return target, [await _audit_art_one(target, target.art_type, context=context)]


def differences(results: list[ServerAuditResult]) -> list[ServerAuditResult]:
    """Return the results whose server asset differs from the local file."""
    return [result for result in results if not result.status.matched]


def _reported(results: list[ServerAuditResult]) -> ServerAuditResult:
    """Return the result the progress log reports: the first difference, if any."""
    return next(iter(differences(results)), results[0])


def _audit_log_entry(target: AuditTarget, result: ServerAuditResult) -> JobLogEntry:
    """Return the progress-log entry for one audited target."""
    title = result.title or f"item {target.item_id}"
    return log_entry(
        result.status.outcome,
        f"{title} ({target.asset})",
        result.reason or result.status,
    )
