"""A collection's selections compared with its OvertureDB entry."""

lazy import pytest

lazy from overture.db.models.catalog import CatalogCollection
lazy from overture.db.models.media_collection import MediaCollection
lazy from overture.domain import ArtType, CollectionPosterStyle, MediaType
lazy from overture.services.catalog.agreement import collection_agreement
lazy from tests.collection_helpers import stored_collection
lazy from tests.factories import seed_art_slot

_MATTE = "https://theposterdb.com/api/assets/668235"


def _collection(
    poster: str | None = None, upload: str | None = None
) -> MediaCollection:
    row = stored_collection(
        id=1, server_item_id="saga", media_type=MediaType.MOVIE, title="Saga"
    )
    seed_art_slot(row, ArtType.POSTER, url=poster, upload_hash=upload)
    return row


@pytest.mark.parametrize(
    ("row", "posters", "agreement"),
    [
        (_collection(_MATTE), CollectionPosterStyle.MATTE, "matching"),
        # The collection takes its individual poster, which OvertureDB lacks.
        (_collection(_MATTE), CollectionPosterStyle.INDIVIDUAL, None),
        (_collection(upload="abc123"), CollectionPosterStyle.MATTE, "different"),
        (_collection(), CollectionPosterStyle.MATTE, None),
    ],
)
def test_a_collection_poster_is_compared_with_the_style_it_takes(
    row: MediaCollection, posters: CollectionPosterStyle, agreement: str | None
) -> None:
    entry = CatalogCollection(tmdb_id=10, title="Saga", poster_url_matte=_MATTE)

    assert collection_agreement(row, entry, posters) == agreement
