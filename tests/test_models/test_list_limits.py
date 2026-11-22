"""A list's length limit counts what is sent, as the schema states it."""

lazy from typing import Any

lazy import pytest
lazy from pydantic import TypeAdapter, ValidationError

lazy from overture.schemas.themes import SearchRequest
lazy from overture.schemas.validators import CollectionIds, LibraryIds


@pytest.mark.parametrize(
    ("list_type", "limit", "value"),
    [(CollectionIds, 1000, 7), (LibraryIds, 200, "1:1")],
)
def test_repeats_count_toward_the_limit_and_are_then_dropped(
    list_type: Any, limit: int, value: object
) -> None:
    adapter = TypeAdapter(list_type)

    assert adapter.validate_python([value] * limit) == [value]
    with pytest.raises(ValidationError, match="at most"):
        adapter.validate_python([value] * (limit + 1))


def test_repeated_video_ids_count_toward_the_search_limit() -> None:
    with pytest.raises(ValidationError, match="at most"):
        SearchRequest(video_ids=["abcdefghijk"] * 21)
