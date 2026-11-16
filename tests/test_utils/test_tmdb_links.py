"""TMDB IDs as people type or paste them."""

lazy import pytest

lazy from overture.utils.tmdb_links import tmdb_page_id


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (" 8136 ", 8136),
        ("https://www.themoviedb.org/list/8136-best-of", 8136),
        ("https://www.themoviedb.org/person/31-tom-hanks?language=en", 31),
        ("https://www.themoviedb.org/company/41077/movie", 41077),
        ("https://www.themoviedb.org/de-DE/keyword/10051-heist", 10051),
        ("https://example.com/list/8136", None),
        ("Tom Hanks", None),
        ("0", None),
    ],
)
def test_an_id_is_read_from_a_number_or_a_tmdb_page_link(
    text: str, expected: int | None
) -> None:
    assert tmdb_page_id(text) == expected
