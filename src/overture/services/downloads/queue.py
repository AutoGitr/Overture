"""What a download job targets, and queuing one inside the caller's transaction."""

lazy from dataclasses import asdict, dataclass
lazy from typing import Self

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...db.models.download_job import DownloadJob
lazy from ...domain import ArtType, JobType, MediaType
lazy from ...repositories.downloads import DownloadJobRepository
lazy from ...repositories.seasons import SeasonRepository
lazy from ...utils.time import utc_now


@dataclass(slots=True, frozen=True)
class AssetScope:
    """The assets of one item or collection that download jobs write.

    A field left ``None`` matches every value, so a season poster scope
    without a season covers every season of the item.
    """

    media_item_id: int | None = None
    collection_server_id: str | None = None
    job_type: JobType | None = None
    art_type: ArtType | None = None
    season_id: int | None = None

    @property
    def lock_key(self) -> int | str:
        """The asset lock that writing these assets takes."""
        if self.media_item_id is not None:
            return self.media_item_id
        return f"collection:{self.collection_server_id}"


@dataclass(slots=True, frozen=True)
class JobTarget:
    """The one asset a download job writes, and where its content comes from.

    Build targets with :meth:`art`, :meth:`theme` or :meth:`collection_theme`,
    so a target always names exactly what its job type needs.
    """

    job_type: JobType
    target_url: str
    media_item_id: int | None = None
    art_type: ArtType | None = None
    season_id: int | None = None
    collection_server_id: str | None = None
    collection_media_type: MediaType | None = None
    collection_title: str | None = None

    @classmethod
    def art(
        cls,
        media_item_id: int,
        art_type: ArtType,
        url: str,
        *,
        season_id: int | None = None,
    ) -> Self:
        """Target one artwork slot of an item, or of one of its seasons.

        Raises:
            ValueError: When a season slot names no season, or an item slot one.
        """
        if art_type.owned_by_season != (season_id is not None):
            raise ValueError("Season artwork requires a season belonging to the item")
        return cls(
            JobType.ART,
            url,
            media_item_id=media_item_id,
            art_type=art_type,
            season_id=season_id,
        )

    @classmethod
    def theme(cls, media_item_id: int, youtube_id: str) -> Self:
        """Target an item's theme."""
        return cls(JobType.THEME, youtube_id, media_item_id=media_item_id)

    @classmethod
    def collection_theme(
        cls, server_id: str, media_type: MediaType, title: str, youtube_id: str
    ) -> Self:
        """Target the theme of a media-server collection."""
        return cls(
            JobType.COLLECTION_THEME,
            youtube_id,
            collection_server_id=server_id,
            collection_media_type=media_type,
            collection_title=title,
        )

    @property
    def slot(self) -> AssetScope:
        """The asset slot this target writes, whatever its source."""
        return AssetScope(
            media_item_id=self.media_item_id,
            collection_server_id=self.collection_server_id,
            job_type=self.job_type,
            art_type=self.art_type,
            season_id=self.season_id,
        )


async def add_job(
    session: AsyncSession, target: JobTarget, *, supersede: bool = True
) -> tuple[str, bool, list[tuple[DownloadJob, str]]]:
    """Stage a job for *target* unless its slot already has one for it.

    An active job for the same source is reused. A job for another source is
    cancelled in favour of this one, or reused without *supersede*.

    Returns:
        The job's ID, whether it is new, and the jobs it cancelled with their
        titles.

    Raises:
        ValueError: When a season slot names a season of another item.
    """
    if (
        target.season_id is not None
        and target.media_item_id is not None
        and not await SeasonRepository(session).get_for_item(
            target.season_id, target.media_item_id
        )
    ):
        raise ValueError("Season does not belong to the media item")

    repository = DownloadJobRepository(session)
    active = await repository.list_active_with_titles(scope=target.slot)
    for existing, _ in active:
        if existing.target_url == target.target_url or not supersede:
            return existing.id, False, []

    now = utc_now()
    repository.cancel((job for job, _ in active), now=now)
    job = repository.create(created_at=now, **asdict(target))
    await session.flush()
    return job.id, True, active
