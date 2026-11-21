"""What the sources of an Assets run offer one target.

Sources are asked in the run's order until one decides. A decision is a link
or video to download, or one to save as the selection of the content already
in place (an adoption). A source without one says why: it declined art that
differs from the local file, it failed, or it had nothing.
"""

lazy from dataclasses import dataclass, field

lazy import httpx2
lazy from sqlalchemy.exc import SQLAlchemyError

lazy from ...db.ledger import FileFacts, local_file
lazy from ...db.models.season import Season
lazy from ...domain import (
    MATCH_THRESHOLD_MAX,
    ArtBulkSource,
    CollectionPosterStyle,
    ThemeBulkSource,
)
lazy from ...schemas.art import ArtCandidate
lazy from ...schemas.bulk import BulkMatchArtRequest
lazy from ...utils.errors import PublicServiceError
lazy from ..art.collection_art import CollectionArtService, chosen_poster_style
lazy from ..art.matcher import ArtMatcher
lazy from ..art.perfect_match import accepted_matches, accepts, comparison_threshold
lazy from ..catalog.index import CatalogIndex
lazy from ..themes.youtube_resolver import DownloadError, YouTubeResolver
lazy from .plan import RunParams, Source, Target, Unusable, catalog_pick, triage
lazy from .support import no_match_reason

#: Errors a source reports as its own failure, leaving the rest to be asked.
SOURCE_ERRORS = (
    SQLAlchemyError,
    PublicServiceError,
    httpx2.HTTPError,
    OSError,
    ValueError,
    DownloadError,
)

#: What the comparison reference was, as said in a reason.
_REFERENCE_NOTES: frozendict[str, str] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        "media_server": "compared with the media server's image",
        "saved_url": "compared with the saved URL's image",
    }
)

#: What a reason adds when a download replaces the file in a title's folder.
REPLACES_LOCAL_FILE = "; replaces the local file"


@dataclass(frozen=True, slots=True)
class Decision:
    """What a source decided for a target."""

    #: The link, or the YouTube ID of a theme.
    value: str
    reason: str
    #: Save the value as the selection of the content in place; nothing is
    #: downloaded.
    adopt: bool = False
    #: The local file the link was verified identical to, for a title's adoption.
    verified: FileFacts | None = None
    #: Which OvertureDB poster a collection poster link is.
    poster_style: CollectionPosterStyle | None = None


@dataclass(slots=True, frozen=True)
class Notes:
    """Why the sources that were asked did not decide."""

    errors: list[str] = field(default_factory=list[str])
    declined: list[str] = field(default_factory=list[str])
    empty: list[str] = field(default_factory=list[str])

    def text(self) -> str:
        return "; ".join([*self.declined, *self.errors, *self.empty])


@dataclass(frozen=True, slots=True)
class BatchFacts:
    """What one batch's sources read once for all its targets."""

    index: CatalogIndex
    #: Themes that failed to download before, by owner ID.
    failed: dict[int, set[str]] = field(default_factory=dict[int, set[str]])
    #: How a title's theme is searched for on YouTube.
    search_format: str = "{title} theme"


def _sized(reason: str, candidate: ArtCandidate) -> str:
    """Add the artwork's size to *reason* when its source reported one."""
    if candidate.width and candidate.height:
        return f"{reason}; {candidate.width}x{candidate.height}"
    return reason


def _replaces(target: Target) -> str:
    """What a download's reason adds when it replaces a title's local file."""
    return REPLACES_LOCAL_FILE if local_file(target.asset) is not None else ""


@dataclass(frozen=True, slots=True)
class Sources:
    """The collaborators every source of one run asks."""

    params: RunParams
    art_matcher: ArtMatcher | None = None
    art: CollectionArtService | None = None
    youtube_resolver: YouTubeResolver | None = None

    async def ask(
        self, target: Target, facts: BatchFacts
    ) -> tuple[Decision | None, Notes]:
        """Ask the sources that can serve *target*, in order, until one decides."""
        notes = Notes()
        for source in triage(target, self.params):
            if isinstance(source, Unusable):
                notes.empty.append(source.reason)
                continue
            try:
                decision = await self._offer(source, target, facts, notes)
            except SOURCE_ERRORS as exc:
                notes.errors.append(f"{source.label}: {exc}")
                continue
            if decision is not None:
                return decision, notes
        return None, notes

    async def _offer(
        self, source: Source, target: Target, facts: BatchFacts, notes: Notes
    ) -> Decision | None:
        if source is ArtBulkSource.LOCAL_ART_MATCHING:
            if target.collection is not None:
                return await self._match_collection(target, notes)
            return await self._match_title(target, notes)
        if source is ThemeBulkSource.YOUTUBE_SEARCH:
            return await self._search(target, facts, notes)
        failed = facts.failed.get(target.owner.id or 0, set[str]())
        pick = catalog_pick(target, (source,), facts.index, failed=failed)
        if pick.value is None:
            notes.empty.extend(pick.notes)
            return None
        if source is ArtBulkSource.OVERTUREDB and target.collection is None:
            return await self._compare_title(target, pick.value, pick.label, notes)
        art_type = target.kind.art_type
        return Decision(
            pick.value,
            pick.label + (_replaces(target) if target.collection is None else ""),
            poster_style=facts.index.collection_poster_style(
                target.collection, art_type
            )
            if target.collection is not None and art_type is not None
            else None,
        )

    @property
    def _threshold(self) -> int:
        if not isinstance(self.params, BulkMatchArtRequest):
            raise TypeError("Only artwork runs compare images")
        return self.params.threshold

    async def _compare_title(
        self, target: Target, url: str, label: str, notes: Notes
    ) -> Decision | None:
        """Take OvertureDB's art for a title unless it differs from the local file."""
        local = local_file(target.asset)
        if local is None or self.params.overwrite_existing:
            return Decision(url, label + (REPLACES_LOCAL_FILE if local else ""))
        if self.art_matcher is None:
            raise ValueError("Artwork runs compare with an art matcher")
        compared = await self.art_matcher.compare_with_local(url, local)
        if compared.identical:
            return Decision(
                url,
                "OvertureDB artwork is identical to the local file",
                adopt=True,
                verified=local,
            )
        if accepts(self._threshold, distance=compared.distance, identical=False):
            return Decision(
                url, f"d={compared.distance} from OvertureDB{REPLACES_LOCAL_FILE}"
            )
        notes.declined.append(
            f"OvertureDB artwork is d={compared.distance} from the local file but "
            f"not the same file; a match threshold of {compared.distance} or more "
            "takes it"
            if compared.distance <= MATCH_THRESHOLD_MAX
            else f"OvertureDB artwork is a different picture, d={compared.distance}"
        )
        return None

    async def _match_title(self, target: Target, notes: Notes) -> Decision | None:
        """Compare the art sources' candidates with a title's art."""
        title, art_type = target.title, target.kind.art_type
        if self.art_matcher is None or title is None or art_type is None:
            raise ValueError("Local art matching compares a title's artwork")
        threshold = self._threshold
        outcome = await self.art_matcher.match_item_art(
            item_id=title.id or 0,
            art_type=art_type,
            threshold=comparison_threshold(threshold),
            season_id=target.owner.id if isinstance(target.owner, Season) else None,
            include_overturedb=False,
            refresh=False,
        )
        result = outcome.response
        errors = list(result.errors)
        if failed := result.failed:
            errors.append(f"could not compare {failed} artwork candidates")
        matches = accepted_matches(result.matches, threshold)
        if not matches:
            if errors:
                notes.errors.append(f"Local art matching: {'; '.join(errors)}")
            else:
                notes.empty.append(
                    f"Local art matching: {no_match_reason(result, threshold)}"
                )
            return None
        best = matches[0]
        source = best.source or "an enabled source"
        incomplete = f"; incomplete comparison: {'; '.join(errors)}" if errors else ""
        local = outcome.local_file
        if best.perfect_match and local is not None:
            return Decision(
                best.url,
                _sized(
                    f"perfect match from {source} is identical to the local file", best
                )
                + incomplete,
                adopt=True,
                verified=local,
            )
        reference = result.reference
        detail = (
            REPLACES_LOCAL_FILE.removeprefix("; ")
            if reference == "local_file"
            else _REFERENCE_NOTES.get(reference or "", "")
        )
        reason = _sized(f"d={best.hamming} from {source}", best)
        return Decision(
            best.url, reason + (f"; {detail}" if detail else "") + incomplete
        )

    async def _match_collection(self, target: Target, notes: Notes) -> Decision | None:
        """Compare TMDB's collection art with the image in place, and adopt a match."""
        row, art_type = target.collection, target.kind.art_type
        if self.art is None or row is None or art_type is None:
            raise ValueError("Local art matching compares a collection's artwork")
        threshold = self._threshold
        result = await self.art.match(
            row.id or 0, art_type, comparison_threshold(threshold)
        )
        matches = accepted_matches(result.matches, threshold)
        if not matches:
            notes.empty.append(
                f"Local art matching: {no_match_reason(result, threshold)}"
            )
            return None
        best = matches[0]
        return Decision(
            best.url,
            "matches the server's image",
            adopt=True,
            poster_style=chosen_poster_style(art_type, best),
        )

    async def _search(
        self, target: Target, facts: BatchFacts, notes: Notes
    ) -> Decision | None:
        """Take YouTube's top result for a title's theme."""
        title = target.title
        if self.youtube_resolver is None or title is None:
            raise ValueError("YouTube search looks for a title's theme")
        name = ThemeBulkSource.YOUTUBE_SEARCH.label
        query = (
            facts.search_format.replace("{title}", title.title)
            .replace("{year}", str(title.year) if title.year else "")
            .strip()
        )
        results = await self.youtube_resolver.search(query, limit=1)
        if not results or not (best_id := results[0].id):
            notes.empty.append(f"{name}: no result for {query!r}")
            return None
        if best_id in facts.failed.get(title.id or 0, set[str]()):
            notes.empty.append(
                f"{name}: top result {best_id} failed to download before"
            )
            return None
        found = results[0].title
        return Decision(
            best_id, (f"{name}: {found}" if found else name) + _replaces(target)
        )
