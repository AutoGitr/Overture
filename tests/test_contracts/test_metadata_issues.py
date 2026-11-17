"""The metadata issues the library lists for titles and collections."""

lazy from overture.db.models.media_item import MediaItem
lazy from overture.domain import MediaType, MetadataIssue
lazy from overture.schemas.collections import collection_metadata_issues
lazy from overture.schemas.library import ItemCopyRead, item_metadata_issues
lazy from tests.collection_helpers import stored_collection
lazy from tests.media_servers import served_item


def test_a_title_lists_each_gap_and_a_catalog_id_conflict() -> None:
    bare = MediaItem(media_type=MediaType.SHOW, title="Bare")
    complete = served_item(
        media_type=MediaType.SHOW,
        title="Complete",
        tmdb_id=1,
        tvdb_id=2,
        imdb_id="tt3",
        folder_path="/tv/Complete",
        year=2020,
        server_item_id="9",
    )

    held = [ItemCopyRead(server_id=1, server_item_id="9", library_id="1:1")]
    assert item_metadata_issues(bare, None, []) == [
        MetadataIssue.NO_TMDB_ID,
        MetadataIssue.NO_TVDB_ID,
        MetadataIssue.NO_IMDB_ID,
        MetadataIssue.NO_LOCAL_PATH,
        MetadataIssue.NO_YEAR,
        MetadataIssue.NO_SERVER_ID,
    ]
    assert item_metadata_issues(complete, "mismatching", held) == [
        MetadataIssue.ID_MISMATCH
    ]
    # TVDB identifies shows, so a movie never lacks a TVDB ID.
    movie = MediaItem(media_type=MediaType.MOVIE, title="Movie")
    assert MetadataIssue.NO_TVDB_ID not in item_metadata_issues(movie, None, held)


def test_a_collection_lists_only_the_issues_collections_can_have() -> None:
    withheld = stored_collection(title="Saga")

    issues = collection_metadata_issues(withheld)

    assert issues == [MetadataIssue.NO_TMDB_ID, MetadataIssue.NO_SERVER_ID]
    assert all(issue.collections for issue in issues)
