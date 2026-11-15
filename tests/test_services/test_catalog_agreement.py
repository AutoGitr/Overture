"""A collection's selections compared with its OvertureDB entry."""

lazy import pytest

lazy from overture.db.models.catalog import CatalogCollection
lazy from overture.db.models.media_collection import MediaCollection
lazy from overture.domain import ArtType, CollectionPosterStyle, MediaType
lazy from overture.schemas.catalog import CatalogSelections
lazy from overture.services.catalog.agreement import collection_agreement
lazy from tests.collection_helpers import stored_collection
lazy from tests.factories import seed_art_slot

_MATTE = "https://theposterdb.com/api/assets/668235"
_INDIVIDUAL = "https://image.tmdb.org/t/p/original/saga.jpg"


def _collection(
    poster: str | None = None,
    style: CollectionPosterStyle | None = None,
    upload: str | None = None,
) -> MediaCollection:
    row = stored_collection(
        id=1, server_item_id="saga", media_type=MediaType.MOVIE, title="Saga"
    )
    seed_art_slot(
        row, ArtType.POSTER, url=poster, poster_style=style, upload_hash=upload
    )
    return row


@pytest.mark.parametrize(
    ("row", "agreement"),
    [
        (_collection(_MATTE, CollectionPosterStyle.MATTE), "matching"),
        # Selected as an overlay poster, which OvertureDB lacks.
        (_collection(_MATTE, CollectionPosterStyle.OVERLAY), "different"),
        (_collection(_MATTE, CollectionPosterStyle.INDIVIDUAL), "different"),
        (_collection(upload="abc123"), "different"),
        # No poster, where OvertureDB has the matte one the collection takes.
        (_collection(), "different"),
    ],
)
def test_a_collection_poster_is_compared_with_the_style_it_was_selected_as(
    row: MediaCollection, agreement: str | None
) -> None:
    entry = CatalogCollection(
        tmdb_id=10,
        title="Saga",
        poster_url_individual=_INDIVIDUAL,
        poster_url_matte=_MATTE,
    )

    selections = collection_agreement(row, entry, CollectionPosterStyle.MATTE)

    assert selections is not None
    assert selections.poster == agreement


def test_each_collection_slot_is_compared_on_its_own() -> None:
    entry = CatalogCollection(
        tmdb_id=10, title="Saga", poster_url_matte=_MATTE, youtube_id_overturedb="t"
    )

    assert collection_agreement(
        _collection(_MATTE, CollectionPosterStyle.MATTE),
        entry,
        CollectionPosterStyle.INDIVIDUAL,
    ) == CatalogSelections(poster="matching", background="matching", theme="different")
    assert (
        collection_agreement(_collection(), None, CollectionPosterStyle.MATTE) is None
    )
