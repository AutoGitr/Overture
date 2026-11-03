"""Validating a chosen artwork link before any slot records it."""

lazy from dataclasses import dataclass

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...config import Settings
lazy from ...dataset_contract.contract import canonical_art_url
lazy from ...db.models.settings import get_app_settings
lazy from ...db.session import Database
lazy from ...domain import ArtType
lazy from ...integrations.proxy import ProxyClientManager
lazy from ...media_servers.registry import ProviderRegistry
lazy from ...schemas.art import SaveArtRequest
lazy from ...utils.art_urls import PublicArtUrl, public_art_url
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.image import (
    RateLimitedError,
    is_valid_aspect_ratio,
    is_valid_image_format,
    raise_if_rate_limited,
    sniff_image_size,
)
lazy from ...utils.security import remove_sensitive_url_params
lazy from ...utils.ssrf import is_private_url


async def _validate_art_url(target_url: str, *, trusted_media_server: bool) -> None:
    """Reject a URL Overture will not download from.

    Raises:
        PublicServiceError: When the format is unsupported, or the URL points
            somewhere only the server can reach.
    """
    if not is_valid_image_format(target_url):
        raise PublicServiceError(400, "Only JPG and PNG formats are allowed.")
    if not trusted_media_server and await is_private_url(target_url):
        raise PublicServiceError(
            400,
            "Private/Local URLs are not allowed in the database.",
        )


async def require_valid_aspect_ratio(
    db: AsyncSession, art_type: ArtType, width: int, height: int
) -> None:
    """Check the image's shape against the configured tolerance.

    Raises:
        PublicServiceError: When the aspect ratio is outside the tolerance.
    """
    settings_row = await get_app_settings(db)
    if not is_valid_aspect_ratio(
        width, height, art_type, settings_row.aspect_ratio_tolerance
    ):
        raise PublicServiceError(
            400,
            f"Invalid aspect ratio for {art_type.replace('_', ' ')}.",
        )


@dataclass(frozen=True, slots=True)
class ArtSelection:
    """A validated artwork choice, ready to record for any slot.

    ``stored_url`` is ``None`` for a media-server image, which has no storable
    link: its download records the slot when it lands.
    """

    target_url: str
    stored_url: PublicArtUrl | None


class ArtSelector:
    """Turn a requested artwork link into a validated :class:`ArtSelection`."""

    def __init__(
        self,
        *,
        app_config: Settings,
        database: Database,
        provider_registry: ProviderRegistry,
        image_clients: ProxyClientManager,
    ) -> None:
        self._config = app_config
        self._database = database
        self._provider_registry = provider_registry
        self._image_clients = image_clients

    async def _resolve_art_dimensions(
        self,
        target_url: str,
        *,
        width: int | None,
        height: int | None,
        trusted_media_server: bool,
    ) -> tuple[int, int]:
        """Return the image's dimensions, fetching them when the client omitted them.

        Raises:
            PublicServiceError: When the remote image cannot be measured.
        """
        if width is not None and height is not None:
            return width, height

        try:
            raise_if_rate_limited(target_url)
            width, height = await sniff_image_size(
                target_url,
                await self._image_clients.get_client(target_url),
                allow_private=trusted_media_server,
                headers=self._provider_registry.provider.get_download_headers(
                    target_url
                ),
            )
        except RateLimitedError as exc:
            raise PublicServiceError(503, str(exc)) from exc
        if not width or not height:
            raise PublicServiceError(
                400,
                "Could not validate remote image dimensions or content type.",
            )
        return width, height

    async def prepare(self, art_type: ArtType, body: SaveArtRequest) -> ArtSelection:
        """Validate the chosen artwork before anything is recorded."""
        try:
            target_url = canonical_art_url(remove_sensitive_url_params(body.url))
        except ValueError as exc:
            raise PublicServiceError(400, f"{exc}.") from exc
        trusted_media_server = self._config.is_trusted_media_server_url(target_url)

        await _validate_art_url(target_url, trusted_media_server=trusted_media_server)
        width, height = await self._resolve_art_dimensions(
            target_url,
            width=body.width,
            height=body.height,
            trusted_media_server=trusted_media_server,
        )
        async with self._database.read_session() as db:
            await require_valid_aspect_ratio(db, art_type, width, height)
        return ArtSelection(
            target_url=target_url,
            stored_url=await public_art_url(target_url, app_config=self._config),
        )
