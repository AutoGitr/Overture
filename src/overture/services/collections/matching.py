"""Which TMDB collection a media-server collection is."""

lazy from collections import Counter
lazy from collections.abc import Sequence

lazy from ...db.models.media_collection import MediaCollection
lazy from ...domain import CollectionMatch, MediaType


def derive_tmdb_collection(
    provider_tmdb_id: int | None, member_collection_ids: Sequence[int | None]
) -> int | None:
    """Return the TMDB collection a server collection stands for, if clear.

    The server's own ID wins. Otherwise a strict majority of all members must
    belong to one TMDB collection, so a custom collection mixing franchises,
    or one whose members are mostly unknown, stays unmatched.
    """
    if provider_tmdb_id is not None:
        return provider_tmdb_id
    counts = Counter(value for value in member_collection_ids if value is not None)
    if not counts:
        return None
    tmdb_id, count = counts.most_common(1)[0]
    return tmdb_id if count * 2 > len(member_collection_ids) else None


def apply_match(
    collection: MediaCollection, member_collection_ids: Sequence[int | None]
) -> bool:
    """Recompute an automatic match; return whether it changed.

    A manual match or unmatch is the user's choice and is left alone.
    """
    if collection.media_type is not MediaType.MOVIE:
        return False
    if collection.tmdb_match is not CollectionMatch.AUTO:
        return False
    derived = derive_tmdb_collection(collection.provider_tmdb_id, member_collection_ids)
    if derived == collection.tmdb_collection_id:
        return False
    collection.tmdb_collection_id = derived
    return True
