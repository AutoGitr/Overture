"""Inspect local artwork files and record what they contain.

Every slot's file columns are written from an :class:`ArtFileFacts` taken here
or by a finished download, never assembled field by field elsewhere. An
unchanged stat revision reuses the recorded facts, so a refresh only reads a
file that has changed.
"""

lazy import logging
lazy import os
lazy from dataclasses import dataclass
lazy from pathlib import Path

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...db.art_slots import (
    ArtFileColumns,
    ArtFileFacts,
    art_file_columns,
    art_file_facts,
    find_art_slot,
    record_art_file,
)
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...db.session import Database
lazy from ...domain import ITEM_ART_TYPES, ArtType
lazy from ...repositories.seasons import SeasonRepository
lazy from ...utils.image import get_local_image_size_async
lazy from ...utils.path import same_revision
lazy from ...utils.threads import owned_thread
lazy from ..art.phash import PhashService
lazy from ..library.completion import auto_unmonitor_completed
lazy from ..storage.assets import AssetStorage, FolderListing

logger = logging.getLogger(__name__)


class _Unreadable:
    """Marker for a file that exists but changed or failed while being read."""


UNREADABLE = _Unreadable()


@dataclass(frozen=True, slots=True)
class _SlotProbe:
    owner: MediaItem | Season
    art_type: ArtType
    path: Path | None
    stat: os.stat_result | None


@dataclass(frozen=True, slots=True)
class _SlotChange:
    owner_type: type[MediaItem | Season]
    owner_id: int
    art_type: ArtType
    before: ArtFileColumns
    after: ArtFileFacts | None


class LocalArtInspector:
    """Read local artwork files into the facts their slots record."""

    def __init__(self, asset_storage: AssetStorage, phash: PhashService) -> None:
        self._asset_storage = asset_storage
        self._phash = phash

    async def inspect(
        self, path: Path, known: ArtFileFacts | None
    ) -> ArtFileFacts | _Unreadable:
        """Return the facts of the file at *path*.

        Returns:
            The facts, reusing *known* while the stat revision is unchanged, or
            ``UNREADABLE`` when the file changed or failed while being read,
            so the caller keeps the previous record and tries again later.
        """
        try:
            before = await owned_thread(path.stat)
        except OSError:
            return UNREADABLE
        if known is not None and self._unchanged(known, before):
            return known

        file_hash = await self._asset_storage.file_hash_async(path)
        if file_hash is None:
            return UNREADABLE

        phash = (
            known.phash
            if known is not None
            and known.file_hash == file_hash
            and self._phash.is_valid_fingerprint(known.phash)
            else None
        )
        if phash is None:
            try:
                phash = await self._phash.compute_from_file(str(path))
            except (OSError, ValueError, RuntimeError) as exc:
                # The file exists and its bytes are known; only the image could
                # not be decoded. Record that rather than pretending it is gone.
                logger.warning("Could not fingerprint %s: %s", path, exc)
        width: int | None = None
        height: int | None = None
        try:
            width, height = await get_local_image_size_async(path)
        except (OSError, ValueError, RuntimeError) as exc:
            logger.debug("Could not read dimensions of %s: %s", path, exc)

        try:
            after = await owned_thread(path.stat)
        except OSError:
            return UNREADABLE
        if not same_revision(before, after):
            return UNREADABLE
        return ArtFileFacts(
            file_hash=file_hash,
            phash=phash,
            width=width or None,
            height=height or None,
            file_mtime_ns=before.st_mtime_ns,
            file_size=before.st_size,
        )

    def _unchanged(self, known: ArtFileFacts, stat: os.stat_result) -> bool:
        """Return whether *known* still describes a file with this stat."""
        return (
            known.file_mtime_ns == stat.st_mtime_ns
            and known.file_size == stat.st_size
            and self._phash.is_valid_fingerprint(known.phash)
        )

    def _locate(
        self,
        art_type: ArtType,
        item: MediaItem,
        season: Season | None,
        listing: FolderListing,
    ) -> _SlotProbe:
        """Find one slot's file and stat it, on a worker thread."""
        path = self._asset_storage.find_local_art_path(
            art_type, item=item, season=season, listing=listing
        )
        try:
            stat = path.stat() if path is not None else None
        except OSError:
            stat = None
        return _SlotProbe(season or item, art_type, path, stat)

    def _probe(
        self, item: MediaItem, seasons: list[Season], listing: FolderListing
    ) -> tuple[dict[int, tuple[str | None, str | None]], list[_SlotProbe]]:
        """Locate and stat every slot of an item in one worker-thread call.

        A season whose recorded folder lies outside the show is probed for its
        folder first, and its poster is looked for there.
        """
        slots = [
            self._locate(art_type, item, None, listing) for art_type in ITEM_ART_TYPES
        ]
        folders: dict[int, tuple[str | None, str | None]] = {}
        for season in seasons:
            if season.id is None:
                continue
            if (probed := self._moved_season_folder(item, season, listing)) is not None:
                folders[season.id] = (season.folder_path, probed)
                season.folder_path = probed
            slots.append(self._locate(ArtType.SEASON_POSTER, item, season, listing))
        return folders, slots

    async def _observe(self, probe: _SlotProbe) -> _SlotChange | None:
        """Return the change one probed slot records, reading only a changed file."""
        owner = probe.owner
        if owner.id is None:
            return None
        slot = find_art_slot(owner, probe.art_type)
        before = art_file_columns(slot)
        known = art_file_facts(slot) if slot is not None else None
        if probe.path is None:
            after = None
        elif (
            probe.stat is not None
            and known is not None
            and self._unchanged(known, probe.stat)
        ):
            after = known
        else:
            after = await self.inspect(probe.path, known)
        if isinstance(after, _Unreadable) or art_file_columns(after) == before:
            return None
        return _SlotChange(type(owner), owner.id, probe.art_type, before, after)

    async def refresh_item(
        self,
        item: MediaItem,
        seasons: list[Season],
        database: Database,
        *,
        listing: FolderListing,
    ) -> bool:
        """Record the current files of an item's artwork and season posters.

        *item* and *seasons* are the rows as read before the files are. Files
        are read with no transaction open, and every unchanged slot costs one
        stat in a single worker-thread call. A slot is written only if its
        recorded facts are still the ones inspected, so a download or another
        refresh that finished meanwhile is never overwritten.

        Returns:
            Whether any recorded fact or season folder changed.
        """
        if item.id is None:
            return False
        folders, probes = await owned_thread(self._probe, item, seasons, listing)
        changes = [change for probe in probes if (change := await self._observe(probe))]
        if not changes and not folders:
            return False
        async with database.write_session() as session:
            parent = await session.get(MediaItem, item.id)
            if parent is None or parent.folder_path != item.folder_path:
                return False
            changed = await _apply(session, parent, folders, changes)
            if changed:
                await auto_unmonitor_completed(session, parent)
        return changed

    def _moved_season_folder(
        self, item: MediaItem, season: Season, listing: FolderListing
    ) -> str | None:
        """Return a season's probed folder when its recorded one is outside the show."""
        if not item.folder_path or (
            season.folder_path
            and Path(season.folder_path).is_relative_to(item.folder_path)
        ):
            return None
        probed = self._asset_storage.probe_season_folder(
            item.folder_path, season.season_num, listing=listing
        )
        return probed if probed != season.folder_path else None


async def _apply(
    session: AsyncSession,
    parent: MediaItem,
    folders: dict[int, tuple[str | None, str | None]],
    changes: list[_SlotChange],
) -> bool:
    """Write inspected changes whose rows still hold what was inspected."""
    seasons: dict[int | None, Season] = (
        {
            season.id: season
            for season in await SeasonRepository(session).list_for_item(parent.id)
        }
        if parent.id is not None
        and (folders or any(change.owner_type is Season for change in changes))
        else {}
    )
    changed = False
    moved: set[int] = set()
    for season_id, (expected, probed) in folders.items():
        current = seasons.get(season_id)
        if current is None or current.folder_path != expected:
            moved.add(season_id)
            continue
        current.folder_path = probed
        session.add(current)
        changed = True
    for change in changes:
        if change.owner_type is Season and change.owner_id in moved:
            continue
        owner = seasons.get(change.owner_id) if change.owner_type is Season else parent
        if owner is None or (
            art_file_columns(find_art_slot(owner, change.art_type)) != change.before
        ):
            continue
        record_art_file(owner, change.art_type, change.after)
        session.add(owner)
        changed = True
    return changed
