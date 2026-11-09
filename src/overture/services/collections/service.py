"""The collections feature, assembled from its focused parts."""

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.session import Database
lazy from ...integrations.arr import ArrClient
lazy from ...integrations.mdblist import MDBListClient
lazy from ...integrations.proxy import ProxyClientManager
lazy from ...integrations.tmdb import TMDBClient
lazy from ...jobs.gate import LibraryGate
lazy from ...media_servers.registry import ProviderRegistry
lazy from ..art.collection_art import CollectionArtService
lazy from ..downloads.service import DownloadService
lazy from ..scheduler import SchedulerService
lazy from .access import CollectionAccess
lazy from .arr_requests import CollectionArr
lazy from .bulk import CollectionBulk
lazy from .discovery import CollectionDiscovery
lazy from .display import CollectionDisplay
lazy from .editor import CollectionEditor
lazy from .groups import CollectionGroups
lazy from .member_effects import MemberEffects
lazy from .membership import Membership
lazy from .post_sync import (
    AutoAssets,
    HomeOrder,
    MemberLabel,
    MemberTag,
    PostSync,
    RequestMissing,
)
lazy from .reader import CollectionReader
lazy from .rule_sync import RuleSync
lazy from .schedule import CollectionSchedule
lazy from .separators import CollectionSeparators
lazy from .set_runner import CollectionSets
lazy from .sources import SourceResolver
lazy from .themes import CollectionThemes
lazy from .validation import CollectionValidator


class CollectionsService:
    """Own the collection workflows and their lifetime.

    Each attribute is one responsibility that callers use directly; this class
    only wires them together and starts and stops what needs it.
    """

    def __init__(
        self,
        *,
        database: Database,
        provider_registry: ProviderRegistry,
        publisher: protocols.EventPublisher,
        downloads: DownloadService,
        proxy_clients: ProxyClientManager,
        app_config: Settings,
        tmdb: TMDBClient,
        mdblist: MDBListClient,
        scheduler: SchedulerService,
        art: CollectionArtService,
        radarr: ArrClient | None = None,
        sonarr: ArrClient | None = None,
        library_gate: LibraryGate | None = None,
    ) -> None:
        self._sources = SourceResolver(
            app_config=app_config,
            tmdb=tmdb,
            mdblist=mdblist,
            radarr=radarr,
            sonarr=sonarr,
        )
        effects = MemberEffects(sources=self._sources, tmdb=tmdb)
        access = CollectionAccess(
            database=database,
            provider_registry=provider_registry,
            publisher=publisher,
            asset_locks=downloads.asset_locks,
            app_config=app_config,
        )
        validator = CollectionValidator(access=access, sources=self._sources)
        membership = Membership(access=access, sources=self._sources)
        self.reader = CollectionReader(access=access, proxy_clients=proxy_clients)
        self.discovery = CollectionDiscovery(
            access=access,
            validator=validator,
            membership=membership,
            sources=self._sources,
            app_config=app_config,
        )
        self.editor = CollectionEditor(
            access=access,
            validator=validator,
            membership=membership,
            display=CollectionDisplay(access=access),
            reader=self.reader,
            sources=self._sources,
            downloads=downloads,
        )
        self.themes = CollectionThemes(
            access=access, downloads=downloads, app_config=app_config
        )
        self.arr = CollectionArr(access=access, sources=self._sources, effects=effects)
        post_sync = PostSync(
            access=access,
            steps=(
                AutoAssets(access=access, art=art, themes=self.themes),
                MemberLabel(access=access, membership=membership),
                MemberTag(access=access, sources=self._sources, effects=effects),
                RequestMissing(access=access, sources=self._sources, arr=self.arr),
                HomeOrder(access=access),
            ),
        )
        self.rules = RuleSync(
            access=access,
            membership=membership,
            editor=self.editor,
            post_sync=post_sync,
            sources=self._sources,
        )
        self.sets = CollectionSets(
            access=access,
            validator=validator,
            membership=membership,
            editor=self.editor,
            post_sync=post_sync,
            sources=self._sources,
        )
        self.groups = CollectionGroups(
            access=access,
            validator=validator,
            editor=self.editor,
            sets=self.sets,
            rules=self.rules,
            separators=CollectionSeparators(
                access=access, editor=self.editor, rules=self.rules
            ),
        )
        self.bulk = CollectionBulk(access=access, editor=self.editor)
        self.schedule = CollectionSchedule(
            access=access,
            sets=self.sets,
            rules=self.rules,
            scheduler=scheduler,
            library_gate=library_gate,
        )

    async def start(self) -> None:
        """Start polling for due sets and rules."""
        self.schedule.start()

    async def stop(self) -> None:
        """Remove polling before the runtime closes its HTTP clients."""
        self.schedule.stop()
        await self._sources.close()
