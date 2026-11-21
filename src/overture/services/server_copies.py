"""What a media server's copy of a title or collection shows.

The one home of how a server copy's image and theme are read, and of what
counts as the same image or the same theme. Sync records a collection's
copies by it, collection art compares candidates with it, and Server audit
reports and records what it finds by it, so a copy is never judged one way
by one operation and another way by another.

A server names its current image or theme by a link (Plex's carries the
collection's last edit time), so an unchanged link with the content already
delivered is taken as the same, and a changed one is settled by fingerprint.
Anything that cannot be read is :attr:`~overture.db.ledger.Evidence.UNKNOWN`,
which records nothing: that is no evidence the copy changed.
"""

lazy import logging
lazy from dataclasses import dataclass
lazy from pathlib import Path

lazy import httpx2

lazy from ..db.ledger import Destination, Evidence, delivery, holds_content, read_asset
lazy from ..db.models.media_collection import MediaCollection
lazy from ..domain import ArtType, ServerAsset
lazy from ..integrations.proxy import ProxyClientManager
lazy from ..media_servers.registry import Provider
lazy from ..utils.audio import audio_hash, downloaded_audio, ffprobe_duration
lazy from ..utils.errors import PublicServiceError
lazy from ..utils.image_fetch import fetch_image
lazy from .art.phash import PhashService
lazy from .art.uploads import ArtUploads

logger = logging.getLogger(__name__)

#: What reading a copy can fail with; a check reports it as unknown.
READ_ERRORS = (PublicServiceError, httpx2.HTTPError, OSError, ValueError)


@dataclass(frozen=True, slots=True)
class ServedTheme:
    """The audio a server plays for a theme, as read from what it serves."""

    #: The hash of the audio alone, without tags a server may rewrite.
    audio_hash: str | None
    #: Seconds it plays, read only to describe how it differs from another.
    duration: float | None = None


class ServerCopies:
    """Read server copies, and compare what they show with Overture's content."""

    def __init__(
        self,
        *,
        phash: PhashService,
        image_clients: ProxyClientManager,
        uploads: ArtUploads,
        config_dir: Path,
    ) -> None:
        self._phash = phash
        self._image_clients = image_clients
        self._uploads = uploads
        self._config_dir = config_dir

    def distance(self, first: str, second: str) -> int:
        """How far apart two image fingerprints are."""
        return self._phash.hamming_distance(first, second)

    def same_image(self, first: str, second: str) -> bool:
        """Whether two fingerprints are the same image.

        Servers re-encode what they are sent, so images are compared by sight,
        not by bytes.
        """
        return self.distance(first, second) == 0

    async def _fingerprint(
        self,
        url: str,
        headers: dict[str, str],
        params: dict[str, str] | None = None,
    ) -> str:
        fetched = await fetch_image(
            url,
            await self._image_clients.get_client(url),
            allow_generic_image=True,
            allow_private=True,
            headers=headers,
            params=params,
        )
        return await self._phash.compute_from_bytes(fetched.data)

    async def item_image(self, provider: Provider, server_url: str) -> str:
        """Fingerprint the image a server shows for a title at *server_url*.

        Raises:
            httpx2.HTTPError: When the image cannot be fetched.
            OSError: When the image cannot be read.
            ValueError: When the response is not a usable image.
        """
        return await self._fingerprint(
            server_url, provider.get_download_headers(server_url)
        )

    async def collection_image(
        self,
        provider: Provider,
        server_item_id: str,
        art_type: ArtType,
        server_url: str,
    ) -> str:
        """Fingerprint the image a server copy of a collection shows at *server_url*.

        Raises:
            httpx2.HTTPError: When the image cannot be fetched.
            OSError: When the image cannot be read.
            ValueError: When the response is not a usable image.
        """
        request = await provider.build_collection_image_request(
            server_item_id, art_type, None, current_url=server_url
        )
        return await self._fingerprint(request.url, request.headers, request.params)

    async def served_theme(
        self, provider: Provider, url: str, *, compared_with: str | None = None
    ) -> ServedTheme:
        """Read the audio a server serves for a theme.

        Its length is read only when it is not the audio hashed as
        *compared_with*, where it describes the difference.

        Raises:
            httpx2.HTTPError: When the theme cannot be downloaded.
            OSError: When it cannot be read.
            ValueError: When the response is not audio.
        """
        async with downloaded_audio(
            await self._image_clients.get_client(url),
            url,
            provider.get_download_headers(url),
            config_dir=self._config_dir,
        ) as path:
            served = await audio_hash(path)
            if compared_with is None or served is None or served == compared_with:
                return ServedTheme(served)
            return ServedTheme(served, await ffprobe_duration(path))

    @staticmethod
    def _unchanged(
        row: MediaCollection, kind: ServerAsset, destination: Destination, ref: str
    ) -> Evidence | None:
        """Settle a copy without fetching it, when its link alone decides.

        Returns ``None`` when only a fingerprint can.
        """
        asset = read_asset(row, kind)
        if asset.content_hash is None:
            return Evidence.DIFFERENT
        seen = delivery(asset, destination)
        if seen is not None and seen.observed_ref == ref and holds_content(seen, asset):
            return Evidence.SAME
        return None

    async def held_fingerprint(self, row: MediaCollection, kind: ServerAsset) -> str:
        """The fingerprint of the image Overture holds for a collection's *kind*.

        Raises:
            PublicServiceError: 409 when Overture no longer keeps the image.
            ValueError: When Overture holds no image for it.
        """
        asset = read_asset(row, kind)
        if asset.content_hash is None:
            raise ValueError("Overture holds no image for it")
        fingerprint = (
            asset.fingerprint
            or (await self._uploads.facts(asset.content_hash)).fingerprint
        )
        if fingerprint is None:
            raise ValueError("The image Overture holds could not be decoded")
        return fingerprint

    async def image_evidence(
        self,
        row: MediaCollection | None,
        kind: ServerAsset,
        destination: Destination,
        provider: Provider,
        server_url: str | None,
    ) -> Evidence:
        """Whether a collection's copy shows the image Overture holds for *kind*.

        *server_url* is the image the copy lists now, ``None`` when it shows none.
        """
        if row is None or server_url is None:
            return Evidence.DIFFERENT
        if (settled := self._unchanged(row, kind, destination, server_url)) is not None:
            return settled
        art_type = kind.art_type
        if art_type is None:
            raise ValueError("Only artwork is an image")
        try:
            held = await self.held_fingerprint(row, kind)
            shown = await self.collection_image(
                provider, destination.server_item_id or "", art_type, server_url
            )
        except READ_ERRORS as exc:
            logger.debug("Could not check collection %s's %s: %s", row.id, kind, exc)
            return Evidence.UNKNOWN
        return Evidence.SAME if self.same_image(held, shown) else Evidence.DIFFERENT

    async def theme_evidence(
        self,
        row: MediaCollection | None,
        destination: Destination,
        provider: Provider,
        theme_ref: str | None,
    ) -> Evidence:
        """Whether an uploaded copy plays the theme Overture holds.

        *theme_ref* is the theme the copy lists now, ``None`` when it has none.
        The audio is compared without its tags, which a server may rewrite.
        Its hash depends on the ffmpeg build, so after an upgrade a copy can
        read as different once, and the next upload records it anew.
        """
        if row is None or theme_ref is None:
            return Evidence.DIFFERENT
        settled = self._unchanged(row, ServerAsset.THEME, destination, theme_ref)
        if settled is not None:
            return settled
        expected = read_asset(row, ServerAsset.THEME).fingerprint
        if expected is None:
            return Evidence.UNKNOWN
        try:
            themes = await provider.get_theme_songs(destination.server_item_id or "")
            url = themes[0].url if themes else None
            if url is None:
                return Evidence.UNKNOWN
            served = (await self.served_theme(provider, url)).audio_hash
        except READ_ERRORS as exc:
            logger.debug("Could not check collection %s's theme: %s", row.id, exc)
            return Evidence.UNKNOWN
        if served is None:
            return Evidence.UNKNOWN
        return Evidence.SAME if served == expected else Evidence.DIFFERENT
