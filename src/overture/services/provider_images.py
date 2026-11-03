"""Bounded media-server image proxy."""

lazy from functools import partial

lazy import httpx2
lazy from fastapi import Response

lazy from ..integrations.http import retrying
lazy from ..integrations.proxy import ProxyClientManager
lazy from ..media_servers.adapters import ProviderImageRequest
lazy from ..utils.errors import PublicServiceError
lazy from ..utils.image import (
    RateLimitedError,
    RemoteImageError,
    fetch_image,
    raise_if_rate_limited,
)

_IMAGE_RETRY_DELAYS = (0.2, 0.5)
_CACHE_SECONDS = 604800


async def proxy_provider_image(
    request: ProviderImageRequest,
    *,
    proxy_clients: ProxyClientManager,
) -> Response:
    """Fetch and return one authenticated, bounded media-server image."""
    client = await proxy_clients.get_client(request.url)
    try:
        raise_if_rate_limited(request.url)
        image = await retrying(
            partial(
                fetch_image,
                request.url,
                client,
                allow_generic_image=True,
                allow_private=True,
                headers=request.headers,
                params=request.params,
            ),
            label="provider image fetch",
            # Short: a sidebar full of thumbnails must not stall on one blip.
            retry_delays=_IMAGE_RETRY_DELAYS,
        )
    except RateLimitedError as exc:
        raise PublicServiceError(503, str(exc)) from exc
    except RemoteImageError as exc:
        raise PublicServiceError(502, str(exc)) from exc
    except httpx2.HTTPError as exc:
        raise PublicServiceError(503, "Image temporarily unreachable") from exc
    return Response(
        content=image.data,
        media_type=image.media_type,
        headers={"Cache-Control": f"max-age={_CACHE_SECONDS}"},
    )
