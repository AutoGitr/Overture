"""Server-audit comparison of a title's theme with its local file."""

lazy import logging
lazy from dataclasses import dataclass
lazy from pathlib import Path

lazy from ...db.ledger import (
    FileFacts,
    local_file,
    read_asset,
)
lazy from ...db.models.media_item import MediaItem
lazy from ...domain import ServerAsset
lazy from ...media_servers.adapters import ServerTheme
lazy from ...media_servers.registry import Provider
lazy from ...schemas.server_audit import (
    AuditStatus,
    ServerAuditResult,
)
lazy from ...utils.audio import audio_hash, ffprobe_duration
lazy from ...utils.threads import owned_thread
lazy from ..server_copies import READ_ERRORS
lazy from ..server_identity import resolve_owners
lazy from .context import AuditContext, finding, for_server
lazy from .work import (
    AuditTarget,
)

logger = logging.getLogger(__name__)


THEME_AUDIO_DURATION_TOLERANCE_SECONDS = 3


async def audit_item_theme(
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
            finding(result, AuditStatus.LOCAL_MISSING, "Local theme file is missing")
        ]
    result.local_path = str(local_path)
    local = _LocalTheme(local_path, local_file(read_asset(item, ServerAsset.THEME)))

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
            finding(
                result,
                AuditStatus.UNRESOLVED_SERVER_ID,
                "Could not resolve media-server item ID",
                local_duration=await local.duration(),
            )
        ]
    results: list[ServerAuditResult] = []
    for server_copy in owners:
        on_server = for_server(result, server_copy.provider)
        on_server.server_item_id = server_copy.server_item_id
        server_themes = await server_copy.provider.get_theme_songs(
            server_copy.server_item_id
        )
        if not server_themes:
            results.append(
                finding(
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
    known: FileFacts | None
    _audio_hash: str | None = None
    _hashed: bool = False
    _duration: float | None = None
    _probed: bool = False

    async def _current_known(self) -> FileFacts | None:
        """Return *known* when the file on disk still has the same size and mtime."""
        known = self.known
        if known is None:
            return None
        try:
            stat = await owned_thread(self.path.stat)
        except OSError:
            return None
        if (stat.st_mtime_ns, stat.st_size) == (
            known.file_mtime_ns,
            known.file_size,
        ):
            return known
        return None

    async def audio_hash(self) -> str | None:
        """Return the hash of the file's audio, reusing a current fingerprint."""
        if not self._hashed:
            self._hashed = True
            known = await self._current_known()
            if known is not None and known.fingerprint is not None:
                self._audio_hash = known.fingerprint
            else:
                self._audio_hash = await audio_hash(self.path)
        return self._audio_hash

    async def duration(self) -> float | None:
        """Return the file's duration: the recorded one if current, else probed once."""
        if not self._probed:
            self._probed = True
            known = await self._current_known()
            if known is not None and known.duration is not None:
                self._duration = known.duration
            else:
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
        return finding(
            result,
            AuditStatus.THEME_UNKNOWN,
            "Media server did not report the theme's file",
            local_duration=await local.duration(),
        )
    if Path(theme.path) == local.path:
        return finding(result, AuditStatus.THEME_MATCH, "Same file")
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
        return finding(
            result, AuditStatus.THEME_UNKNOWN, "Could not read the local theme audio"
        )
    try:
        served = await context.server_copies.served_theme(
            provider, url, compared_with=local_hash
        )
    except READ_ERRORS as exc:
        logger.debug("Could not download the server theme: %s", exc)
        return finding(
            result,
            AuditStatus.THEME_UNKNOWN,
            "Could not download the media-server theme",
            local_duration=await local.duration(),
        )
    if served.audio_hash is None:
        return finding(
            result,
            AuditStatus.THEME_UNKNOWN,
            "Could not read the media-server theme audio",
            local_duration=await local.duration(),
        )
    if served.audio_hash == local_hash:
        return finding(result, AuditStatus.THEME_MATCH, "Same audio")
    server_duration = served.duration
    return await _different_file(result, server_duration, local)


async def _different_file(
    result: ServerAuditResult,
    server_duration: float | None,
    local: _LocalTheme,
) -> ServerAuditResult:
    """Return the mismatch for a server theme that is not the local file."""
    local_duration = await local.duration()
    return finding(
        result,
        AuditStatus.THEME_MISMATCH,
        different_file_reason(server_duration, local_duration),
        local_duration=local_duration,
        server_duration=server_duration,
    )


def different_file_reason(
    server_duration: float | None, local_duration: float | None
) -> str:
    """Describe a server theme whose bytes differ from the local file."""
    if server_duration is None or local_duration is None:
        return "Media server plays a different file"
    delta = abs(server_duration - local_duration)
    if delta <= THEME_AUDIO_DURATION_TOLERANCE_SECONDS:
        return "Media server plays a different file of the same length"
    return f"Media server plays a different file; duration differs by {delta:.1f}s"
