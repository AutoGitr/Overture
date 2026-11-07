"""Public-dataset catalog download, validation, and persistence replacement."""

lazy import asyncio
lazy from typing import Any

lazy from ...config import Settings
lazy from ...dataset_contract.contract import entry_art_urls
lazy from ...utils.art_urls import public_art_url

PUBLIC_DATASET_REPO_URL = "https://github.com/AutoGitr/OvertureDB"
#: The catalog OvertureDB publishes on GitHub Pages, as one gzip stream.
PUBLIC_DATASET_CATALOG_URL = "https://AutoGitr.github.io/OvertureDB/catalog.jsonl.gz"
MAX_CATALOG_COMPRESSED_BYTES = 50 * 1024 * 1024
MAX_CATALOG_UNCOMPRESSED_BYTES = 250 * 1024 * 1024
#: Artwork hosts checked at once while a catalog is validated.
_URL_CHECK_CONCURRENCY = 16


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
