"""Coverage for trusted media-root derivation and folder validation."""

lazy from pathlib import Path

lazy import pytest
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.db.session import Database
lazy from overture.services.storage.trusted_roots import (
    require_trusted_media_roots,
    trusted_media_roots,
    validate_folders_under_trusted_roots,
)
lazy from overture.utils.errors import PublicServiceError
lazy from tests.factories import (
    MediaItemFactory,
)


async def test_trusted_media_roots_returns_empty_when_no_items(
    database: Database,
) -> None:
    assert await trusted_media_roots(database) == []


async def test_trusted_media_roots_are_the_distinct_item_parents(
    db_session: AsyncSession,
    database: Database,
    media_item_factory: MediaItemFactory,
    tmp_path: Path,
) -> None:
    movies = tmp_path / "Movies"
    for name in ("Some Movie (2024)", "Other Movie (2023)"):
        (movies / name).mkdir(parents=True)
        db_session.add(media_item_factory(id=None, folder_path=str(movies / name)))
    await db_session.commit()

    assert await trusted_media_roots(database) == [str(movies.resolve())]


async def test_trusted_media_roots_include_symlinked_item_targets(
    db_session: AsyncSession,
    database: Database,
    media_item_factory: MediaItemFactory,
    tmp_path: Path,
) -> None:
    movies = tmp_path / "Movies"
    movies.mkdir()
    elsewhere = tmp_path / "Elsewhere" / "Linked Movie (2022)"
    elsewhere.mkdir(parents=True)
    linked = movies / "Linked Movie (2022)"
    try:
        linked.symlink_to(elsewhere, target_is_directory=True)
    except OSError:
        pytest.skip("Filesystem does not allow symlink creation")
    db_session.add(media_item_factory(id=None, folder_path=str(linked)))
    await db_session.commit()

    roots = await trusted_media_roots(database)

    assert roots == sorted([str(movies.resolve()), str(elsewhere.resolve())])
    assert await validate_folders_under_trusted_roots(database, [str(linked)])


async def test_trusted_media_roots_ignores_null_folder_paths(
    db_session: AsyncSession,
    database: Database,
    media_item_factory: MediaItemFactory,
) -> None:
    item = media_item_factory(id=None, folder_path=None)
    db_session.add(item)
    await db_session.commit()

    assert await trusted_media_roots(database) == []


async def test_require_trusted_media_roots_raises_when_none_available(
    database: Database,
) -> None:
    with pytest.raises(PublicServiceError) as exc_info:
        await require_trusted_media_roots(database)

    assert exc_info.value.status_code == 403


async def test_require_trusted_media_roots_returns_roots_when_present(
    db_session: AsyncSession,
    database: Database,
    media_item_factory: MediaItemFactory,
    tmp_path: Path,
) -> None:
    movie_dir = tmp_path / "Movies" / "Another Movie (2020)"
    movie_dir.mkdir(parents=True)
    item = media_item_factory(id=None, folder_path=str(movie_dir))
    db_session.add(item)
    await db_session.commit()

    roots = await require_trusted_media_roots(database)

    assert roots


async def test_validate_folders_rejects_folder_outside_trusted_roots(
    db_session: AsyncSession,
    database: Database,
    media_item_factory: MediaItemFactory,
    tmp_path: Path,
) -> None:
    movie_dir = tmp_path / "Movies" / "Trusted Movie (2020)"
    movie_dir.mkdir(parents=True)
    item = media_item_factory(id=None, folder_path=str(movie_dir))
    db_session.add(item)
    await db_session.commit()

    outside_dir = tmp_path / "Outside"
    outside_dir.mkdir()

    with pytest.raises(PublicServiceError) as exc_info:
        await validate_folders_under_trusted_roots(database, [str(outside_dir)])

    assert exc_info.value.status_code == 403
    assert "Invalid, untrusted, or non-existent folder" in exc_info.value.message


async def test_validate_folders_rejects_nonexistent_folder(
    db_session: AsyncSession,
    database: Database,
    media_item_factory: MediaItemFactory,
    tmp_path: Path,
) -> None:
    movie_dir = tmp_path / "Movies" / "Trusted Movie (2021)"
    movie_dir.mkdir(parents=True)
    item = media_item_factory(id=None, folder_path=str(movie_dir))
    db_session.add(item)
    await db_session.commit()

    missing_dir = movie_dir.parent / "does-not-exist"

    with pytest.raises(PublicServiceError):
        await validate_folders_under_trusted_roots(database, [str(missing_dir)])


async def test_validate_folders_accepts_folder_under_trusted_root(
    db_session: AsyncSession,
    database: Database,
    media_item_factory: MediaItemFactory,
    tmp_path: Path,
) -> None:
    movies_root = tmp_path / "Movies"
    movie_dir = movies_root / "Trusted Movie (2022)"
    movie_dir.mkdir(parents=True)
    item = media_item_factory(id=None, folder_path=str(movie_dir))
    db_session.add(item)
    await db_session.commit()

    # The item folder lies inside its trusted parent, so it validates cleanly.
    allowed = await validate_folders_under_trusted_roots(database, [str(movie_dir)])

    assert allowed == [str(movies_root.resolve())]
