"""The media server's libraries, as syncs record them."""

lazy from collections.abc import Collection, Sequence
lazy from datetime import datetime

lazy from sqlmodel import col, func, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.models.library import Library
lazy from ..db.models.media_item import MediaItem
lazy from ..domain import MediaType
lazy from ..media_servers.adapters import ServerSection


class LibraryRepository:
    """Record and read the server's libraries."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(self, sections: Sequence[ServerSection], now: datetime) -> None:
        """Store the libraries the server lists; mark the rest removed at *now*."""
        listed = {(section.key, section.media_type): section for section in sections}
        for library in (await self.session.exec(select(Library))).all():
            section = listed.pop((library.id, library.media_type), None)
            if section is None:
                library.removed_at = library.removed_at or now
            else:
                library.title = section.title
                library.removed_at = None
            self.session.add(library)
        # A key now listed with the other type is marked removed before it is
        # added again, since the server lists each key once.
        await self.session.flush()
        self.session.add_all(
            Library(id=section.key, title=section.title, media_type=section.media_type)
            for section in listed.values()
        )

    async def listed(self, ids: Collection[str] | None = None) -> list[Library]:
        """Return the libraries the server lists now, all or those of *ids*."""
        stmt = select(Library).where(col(Library.removed_at).is_(None))
        if ids is not None:
            stmt = stmt.where(col(Library.id).in_(ids))
        return list((await self.session.exec(stmt)).all())

    async def counts(
        self, media_type: MediaType | None = None
    ) -> list[tuple[Library, int]]:
        """Return the listed libraries with how many visible items each holds."""
        visible = (
            select(func.count())
            .where(
                col(MediaItem.library_id) == col(Library.id),
                col(MediaItem.media_type) == col(Library.media_type),
                col(MediaItem.server_removed_at).is_(None),
            )
            .scalar_subquery()
        )
        stmt = select(Library, visible).where(col(Library.removed_at).is_(None))
        if media_type is not None:
            stmt = stmt.where(col(Library.media_type) == media_type)
        return [(library, count) for library, count in (await self.session.exec(stmt))]
