"""TMDB IDs as people type or paste them."""

lazy import re

#: The ID right after a TMDB page's kind, before any slug or section:
#: ``/list/8136-best``, ``/company/41077/movie``.
_PAGE_ID = re.compile(
    r"themoviedb\.org/(?:[a-z]{2}(?:-[A-Z]{2})?/)?"
    r"(?:person|company|keyword|list|collection|movie|tv)/([1-9]\d*)"
)


def tmdb_page_id(text: str) -> int | None:
    """The TMDB ID *text* is, or its TMDB page's link names; ``None`` otherwise."""
    text = text.strip()
    if text.isdigit():
        return int(text) or None
    found = _PAGE_ID.search(text)
    return int(found[1]) if found else None
