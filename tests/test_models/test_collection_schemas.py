"""Collection theme request validation."""

lazy import pytest
lazy from pydantic import ValidationError

lazy from overture.domain import MediaType
lazy from overture.schemas.collections import SetCollectionThemeRequest


def test_set_collection_theme_request_validates_youtube_id() -> None:
    assert (
        SetCollectionThemeRequest(
            youtube_id="abcDEF123_4",
            media_type=MediaType.MOVIE,
        ).youtube_id
        == "abcDEF123_4"
    )

    with pytest.raises(ValidationError):
        SetCollectionThemeRequest(youtube_id="bad", media_type=MediaType.MOVIE)
