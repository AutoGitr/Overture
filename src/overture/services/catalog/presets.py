"""Read the presets bundle OvertureDB publishes."""

lazy from typing import Any

lazy import httpx2

lazy from ...catalog_contract.contract import read_presets
lazy from ...integrations.http import create_client
lazy from . import remote


async def fetch_presets() -> tuple[dict[str, Any], list[object]]:
    """Return the bundle's header and its presets, each still to be checked.

    Raises:
        ValueError: When the bundle cannot be downloaded or read.
    """
    data = bytearray()
    try:
        async with (
            create_client(follow_redirects=True) as client,
            client.stream("GET", remote.PRESETS_URL) as response,
        ):
            response.raise_for_status()
            async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                data += chunk
                if len(data) > remote.MAX_PRESETS_BYTES:
                    raise ValueError("Presets exceed their size limit")
    except (httpx2.HTTPError, OSError) as exc:
        raise ValueError("OvertureDB's presets could not be downloaded") from exc
    return read_presets(bytes(data))
