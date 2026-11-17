"""The media server's libraries, as syncs record them."""

lazy from collections.abc import Collection, Sequence
lazy from datetime import datetime
lazy from typing import Protocol

lazy from sqlmodel import col, func, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.models.library import Library
lazy from ..db.models.media_item import MediaItem
lazy from ..db.models.media_item_copy import MediaItemCopy
lazy from ..domain import MediaType


class ListedLibrary(Protocol):
    """What a sync records of each library a server lists."""

    @property
    def library_id(self) -> str: ...

    @property
    def title(self) -> str: ...

    @property
    def media_type(self) -> MediaType: ...


class LibraryRepository:
    """Record and read the servers' libraries."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self, server_id: int, sections: Sequence[ListedLibrary], now: datetime
    ) -> None:
        """Store the libraries a server lists; mark its others removed at *now*."""
        listed = {
            (section.library_id, section.media_type): section for section in sections
        }
        for library in (
            await self.session.exec(
                select(Library).where(col(Library.server_id) == server_id)
            )
        ).all():
            section = listed.pop((library.id, library.media_type), None)
            if section is None:
                library.removed_at = library.removed_at or now
            else:
                library.title = section.title
                library.removed_at = None
            self.session.add(library)
        # A key listed with the other type is marked removed before it is
        # added again, since the server lists each key once.
        await self.session.flush()
        self.session.add_all(
            Library(
                id=section.library_id,
                server_id=server_id,
                title=section.title,
                media_type=section.media_type,
            )
            for section in listed.values()
        )

    async def listed(self, ids: Collection[str] | None = None) -> list[Library]:
        """Return the libraries servers list, all or those of *ids*."""
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
            .select_from(MediaItemCopy)
            .join(MediaItem, col(MediaItem.id) == col(MediaItemCopy.media_item_id))
            .where(
                col(MediaItemCopy.library_id) == col(Library.id),
                col(MediaItemCopy.media_type) == col(Library.media_type),
                col(MediaItemCopy.removed_at).is_(None),
                col(MediaItem.server_removed_at).is_(None),
            )
            .scalar_subquery()
        )
        stmt = select(Library, visible).where(col(Library.removed_at).is_(None))
        if media_type is not None:
            stmt = stmt.where(col(Library.media_type) == media_type)
        return [(library, count) for library, count in (await self.session.exec(stmt))]
