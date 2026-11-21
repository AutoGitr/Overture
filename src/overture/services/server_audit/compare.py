"""Server-audit comparison and lifecycle services."""

lazy import logging
lazy from collections.abc import Callable
lazy from contextlib import aclosing
lazy from dataclasses import dataclass, replace
lazy from pathlib import Path

lazy import httpx2
lazy from sqlalchemy.exc import SQLAlchemyError

lazy from ... import protocols
lazy from ...db.ledger import (
    Destination,
    Evidence,
    FileFacts,
    delivery,
    file_facts,
    local_file,
    observe,
    read_asset,
    record_file,
)
lazy from ...db.models.asset import Asset
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...db.session import Database
lazy from ...domain import ArtType, DeliveryChannel, ServerAsset
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
lazy from ...utils.assets import THEME_FILENAME
lazy from ...utils.audio import audio_hash, ffprobe_duration
lazy from ...utils.concurrency import in_order
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.threads import owned_thread
lazy from ...utils.time import utc_now
lazy from ..art.collection_art import CollectionArtService
lazy from ..art.phash import PhashService
lazy from ..art.targets import target_label
lazy from ..collections.destinations import collection_destinations
lazy from ..collections.theme_files import collection_folder, inspect_theme_file
lazy from ..downloads.collection_theme import copy_part
lazy from ..downloads.theme import DownloadThemeHandler
lazy from ..local_assets.service import LocalAssets
lazy from ..server_copies import READ_ERRORS, ServerCopies
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
    server_copies: ServerCopies
    database: Database
    collection_art: CollectionArtService
    theme_handler: DownloadThemeHandler
    publisher: protocols.EventPublisher
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
            known,
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
            f"{server_copy.provider.server.title} has no {art_type.label} for it",
        )
    result.server_image_present = True
    copies = context.server_copies
    try:
        server_phash = await copies.item_image(server_copy.provider, server_url)
    except READ_ERRORS as exc:
        return result.model_copy(update={"reason": str(exc)})
    return _image_finding(result, copies, local_phash, server_phash)


def _image_finding(
    result: ServerAuditResult, copies: ServerCopies, expected: str, shown: str
) -> ServerAuditResult:
    """What comparing a copy's image with the one expected there found."""
    if copies.same_image(expected, shown):
        return _finding(result, AuditStatus.PHASH_MATCH, "d=0 visual match", hamming=0)
    distance = copies.distance(expected, shown)
    return _finding(
        result, AuditStatus.PHASH_MISMATCH, f"d={distance}", hamming=distance
    )


async def _audit_collection_art(
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
            _finding(
                result, AuditStatus.LOCAL_MISSING, "Overture has uploaded no image"
            )
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
            _finding(
                result,
                AuditStatus.UNRESOLVED_SERVER_ID,
                "The collection has no server copy",
            )
        ]
    return [
        await _compare_collection_copy(
            _on(result, provider),
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
        return _finding(
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
    found = _image_finding(result, copies, phash, server_phash)
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
            "collection.updated", {"collection_id": collection_id}
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


async def _audit_collection_theme(
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
            _finding(
                result, AuditStatus.LOCAL_MISSING, "Overture holds no theme for it"
            )
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
            _finding(
                result,
                AuditStatus.UNRESOLVED_SERVER_ID,
                "The collection has no server copy",
            )
        ]
    results: list[ServerAuditResult] = []
    for destination in destinations:
        provider = context.provider_registry.get(destination.server_id or 0)
        on_server = _on(result, provider)
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
        return _finding(
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
        return _finding(
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
        return _finding(
            result,
            AuditStatus.THEME_UNKNOWN,
            "Could not download the media-server theme",
            local_duration=asset.duration,
        )
    if served.audio_hash is None:
        return _finding(
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
        return _finding(result, AuditStatus.THEME_MATCH, "Same audio")
    await _record(
        context,
        result,
        destination,
        Evidence.DIFFERENT,
        expected_hash=expected_hash,
        ref=theme.id,
    )
    return _finding(
        result,
        AuditStatus.THEME_MISMATCH,
        _different_file_reason(served.duration, asset.duration),
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
        return _finding(result, AuditStatus.ERROR, str(exc))
    theme_path = folder / THEME_FILENAME
    result.local_path = str(theme_path)
    try:
        facts = await owned_thread(
            inspect_theme_file, folder, file_facts(delivery(asset, destination))
        )
    except (OSError, ValueError) as exc:
        return _finding(
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
        return _finding(
            result,
            AuditStatus.THEME_SERVER_MISSING,
            f"{provider.server.title} has no theme file in {folder.name}",
            local_duration=asset.duration,
        )
    if facts.file_hash == expected_hash:
        return _finding(result, AuditStatus.THEME_MATCH, "Same file")
    server_duration = (
        facts.duration
        if facts.duration is not None
        else await ffprobe_duration(theme_path)
    )
    return _finding(
        result,
        AuditStatus.THEME_MISMATCH,
        _different_file_reason(server_duration, asset.duration),
        local_duration=asset.duration,
        server_duration=server_duration,
    )


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
        served = await context.server_copies.served_theme(
            provider, url, compared_with=local_hash
        )
    except READ_ERRORS as exc:
        logger.debug("Could not download the server theme: %s", exc)
        return _finding(
            result,
            AuditStatus.THEME_UNKNOWN,
            "Could not download the media-server theme",
            local_duration=await local.duration(),
        )
    if served.audio_hash is None:
        return _finding(
            result,
            AuditStatus.THEME_UNKNOWN,
            "Could not read the media-server theme audio",
            local_duration=await local.duration(),
        )
    if served.audio_hash == local_hash:
        return _finding(result, AuditStatus.THEME_MATCH, "Same audio")
    server_duration = served.duration
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
            return target, await _audit_collection_theme(target, context=context)
        return target, await _audit_collection_art(target, art_type, context=context)
    if target.art_type is None:
        return target, await _audit_theme_one(target, context=context)
    return target, await _audit_art_one(target, target.art_type, context=context)


def differences(results: list[ServerAuditResult]) -> list[ServerAuditResult]:
    """Return the results whose server asset differs from the local file."""
    return [result for result in results if not result.status.matched]
