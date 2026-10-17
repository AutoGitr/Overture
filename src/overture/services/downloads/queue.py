"""What a download job targets, and queuing one inside the caller's transaction."""

lazy from collections.abc import Callable
lazy from dataclasses import asdict, dataclass
lazy from typing import Self

lazy from sqlalchemy import event
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...domain import ArtType, JobType, MediaType
lazy from ...repositories.downloads import DownloadJobRepository
lazy from ...repositories.seasons import SeasonRepository
lazy from ...utils.time import utc_now
lazy from .recovery import selection_state


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


def after_commit(session: AsyncSession, callback: Callable[[], None]) -> None:
    """Run *callback* once the session's transaction has committed."""

    def committed(_session: object) -> None:
        callback()

    event.listen(session.sync_session, "after_commit", committed, once=True)


async def add_job(session: AsyncSession, target: JobTarget) -> tuple[str, bool]:
    """Stage a job for *target* unless an equivalent one is active.

    Returns:
        The job's ID, and whether it is new.

    Raises:
        ValueError: When a season slot names a season of another item.
        RuntimeError: When another theme is already uploading to the collection.
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
    if existing := await repository.find_active_equivalent(target):
        if (
            target.job_type is JobType.COLLECTION_THEME
            and existing.target_url != target.target_url
        ):
            raise RuntimeError("A collection theme upload is already running")
        return existing.id, False

    job = repository.create(created_at=utc_now(), **asdict(target))
    if target.job_type is not JobType.COLLECTION_THEME:
        job.selection_state = await selection_state(session, job)
    await session.flush()
    return job.id, True
