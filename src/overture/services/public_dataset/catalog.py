"""Public-dataset catalog download, validation, and persistence replacement."""

lazy import asyncio
lazy from typing import Any
lazy from urllib.parse import urlparse

lazy from ...config import Settings
lazy from ...utils.art_urls import public_art_url
lazy from .schema.contract import entry_art_urls

PUBLIC_DATASET_REPO_URL = "https://github.com/AutoGitr/OvertureDB"
MAX_CATALOG_COMPRESSED_BYTES = 50 * 1024 * 1024
MAX_CATALOG_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
#: Artwork hosts checked at once while a catalog is validated.
_URL_CHECK_CONCURRENCY = 16


def get_public_dataset_catalog_url() -> str:
    """Derive the GitHub Pages catalog URL from the configured repo URL."""
    parsed = urlparse(PUBLIC_DATASET_REPO_URL)
    if parsed.scheme != "https" or parsed.netloc != "github.com":
        return ""

    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        return ""

    owner, repo = parts[0], parts[1]
    return f"https://{owner}.github.io/{repo}/catalog.jsonl.gz"


def catalog_url_candidates() -> list[str]:
    """Return public-dataset catalog URLs in fallback order."""
    primary = get_public_dataset_catalog_url()
    if not primary:
        return []
    if primary.endswith(".gz"):
        return [primary, primary.removesuffix(".gz")]
    return [primary]


async def check_catalog_urls(
    entries: list[dict[str, Any]], *, app_config: Settings
) -> None:
    """Require every artwork link of *entries* to be safe to store publicly.

    Hosts are resolved before the write transaction, so network delays
    cannot hold SQLite's single writer lock.

    Raises:
        ValueError: When a link is unsafe or carries credentials.
    """
    pending = iter({url for entry in entries for _, url in entry_art_urls(entry)})
    dns_cache: dict[str, asyncio.Task[bool]] = {}

    async def check_urls() -> None:
        for url in pending:
            public = await public_art_url(
                url, dns_cache=dns_cache, app_config=app_config
            )
            if public != url:
                raise ValueError(
                    "Catalog artwork URL is unsafe or contains credentials"
                )

    try:
        async with asyncio.TaskGroup() as group:
            for _ in range(_URL_CHECK_CONCURRENCY):
                group.create_task(check_urls())
    except* ValueError as exc:
        raise ValueError("Catalog contains unsafe artwork URLs") from exc
