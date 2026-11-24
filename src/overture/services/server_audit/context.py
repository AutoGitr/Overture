"""What every server-audit comparison works with, and how it reports a finding."""

lazy from dataclasses import dataclass

lazy from ... import protocols
lazy from ...db.session import Database
lazy from ...media_servers.registry import Provider, ProviderRegistry
lazy from ...schemas.server_audit import (
    AuditStatus,
    ServerAuditResult,
)
lazy from ..art.collection_art import CollectionArtService
lazy from ..art.phash import PhashService
lazy from ..downloads.theme import DownloadThemeHandler
lazy from ..local_assets.service import LocalAssets
lazy from ..server_copies import ServerCopies
lazy from ..storage.assets import AssetStorage


@dataclass(slots=True, frozen=True)
class AuditContext:
    """Collaborator container for server audit execution."""

    provider_registry: ProviderRegistry
    asset_storage: AssetStorage
    local_assets: LocalAssets
    phash: PhashService
    server_copies: ServerCopies
    database: Database
    collection_art: CollectionArtService
    theme_handler: DownloadThemeHandler
    publisher: protocols.EventPublisher
    #: The database's numbers of the servers a run compares with, those that
    #: answered when it started; every configured server when ``None``.
    servers: frozenset[int] | None = None

    def compared(self, provider: Provider) -> bool:
        return self.servers is None or provider.server_id in self.servers


def for_server(result: ServerAuditResult, provider: Provider) -> ServerAuditResult:
    """*result*, about the copy on *provider*'s server."""
    return result.model_copy(
        update={"server_id": provider.server_id, "server": provider.server.title}
    )


def finding(
    result: ServerAuditResult, status: AuditStatus, reason: str, **fields: object
) -> ServerAuditResult:
    """Return *result* with what the audit found, and why."""
    return result.model_copy(update={"status": status, "reason": reason, **fields})


def image_finding(
    result: ServerAuditResult, copies: ServerCopies, expected: str, shown: str
) -> ServerAuditResult:
    """What comparing a copy's image with the one expected there found.

    The distance is the finding's ``hamming``, so its reason does not repeat it.
    """
    if copies.same_image(expected, shown):
        return finding(
            result, AuditStatus.PHASH_MATCH, "The server shows this image", hamming=0
        )
    distance = copies.distance(expected, shown)
    return finding(
        result,
        AuditStatus.PHASH_MISMATCH,
        "The server shows another image",
        hamming=distance,
    )
