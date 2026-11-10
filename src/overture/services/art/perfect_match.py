"""Byte-for-byte comparison of remote artwork with the local file."""

lazy import asyncio
lazy import logging

lazy import httpx2

lazy from ...db.art_slots import ArtFileFacts
lazy from ...domain import PERFECT_MATCH_ONLY
lazy from ...schemas.art import ArtCandidate
lazy from ...utils.file import compute_bytes_hash
lazy from .matcher_cache import ArtMatcherCache

#: Previews can differ slightly from identical originals, so only candidates
#: this close are fetched in full and compared byte for byte.
PERFECT_MATCH_MAX_DISTANCE = 1

logger = logging.getLogger(__name__)


def comparison_threshold(threshold: int) -> int:
    """Return the pHash distance an Assets run with *threshold* compares within.

    Every run compares as far as a perfect match can sit, so a byte-identical
    original is found whatever distance the run accepts otherwise.
    """
    return max(threshold, PERFECT_MATCH_MAX_DISTANCE)


def accepts(threshold: int, *, distance: int | None, identical: bool) -> bool:
    """Whether an Assets run with *threshold* takes an image this close to the file.

    A perfect match is always accepted; any other only within *threshold*.
    """
    return identical or (
        threshold != PERFECT_MATCH_ONLY
        and distance is not None
        and distance <= threshold
    )


def accepted_matches(matches: list[ArtCandidate], threshold: int) -> list[ArtCandidate]:
    """Return the matches an Assets run with *threshold* accepts, in order."""
    return [
        match
        for match in matches
        if accepts(
            threshold, distance=match.hamming, identical=bool(match.perfect_match)
        )
    ]


async def remote_matches_file(
    url: str, facts: ArtFileFacts, *, cache: ArtMatcherCache
) -> bool:
    """Return whether the original image at *url* has the local file's bytes.

    Raises:
        httpx2.HTTPError: When the image cannot be fetched.
        OSError: When the image cannot be read.
        ValueError: When the response is not a usable image.
    """
    image = await cache.fetch(url)
    return (
        len(image.data) == facts.file_size
        and compute_bytes_hash(image.data) == facts.file_hash
    )


async def annotate_perfect_matches(
    facts: ArtFileFacts,
    matches: list[ArtCandidate],
    *,
    cache: ArtMatcherCache,
) -> list[str]:
    """Mark close matches whose original bytes equal the local file.

    Mutates *matches* in place; returns failures that prevented verification.
    """
    close = [
        match
        for match in matches
        if match.hamming is not None
        and match.hamming <= PERFECT_MATCH_MAX_DISTANCE
        and match.url
    ]
    outcomes = await asyncio.gather(
        *(remote_matches_file(match.url, facts, cache=cache) for match in close),
        return_exceptions=True,
    )
    errors: list[str] = []
    for match, outcome in zip(close, outcomes, strict=True):
        if isinstance(outcome, httpx2.HTTPError | OSError | ValueError):
            errors.append(f"perfect-match verification failed: {outcome!s}")
            logger.debug("Perfect match check failed: %s", outcome)
        elif isinstance(outcome, BaseException):
            raise outcome
        elif outcome:
            match.perfect_match = True
    return errors
