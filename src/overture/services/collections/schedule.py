"""Running due collection sets and rules on their schedules."""

lazy import logging

lazy from ...jobs.gate import LibraryGate
lazy from ...repositories.collections import CollectionRepository
lazy from ...schemas.collections import CollectionGroupSyncResult
lazy from ..scheduler import SchedulerService
lazy from .access import CollectionAccess
lazy from .policy import is_due
lazy from .rule_sync import RuleSync
lazy from .rules import generator, never_created
lazy from .set_runner import CollectionSets

logger = logging.getLogger(__name__)

_JOB_ID = "collection-rules"


class CollectionSchedule:
    """Poll for due sets and rules; each owns its persisted due time."""

    def __init__(
        self,
        *,
        access: CollectionAccess,
        sets: CollectionSets,
        rules: RuleSync,
        scheduler: SchedulerService,
        library_gate: LibraryGate | None = None,
    ) -> None:
        self._access = access
        self._sets = sets
        self._rules = rules
        self._scheduler = scheduler
        self._library_gate = library_gate

    def start(self) -> None:
        """Register a bounded poll."""
        self._scheduler.set_interval_job(
            _JOB_ID, enabled=True, func=self.sync_due, minutes=1
        )

    def stop(self) -> None:
        self._scheduler.remove_job(_JOB_ID)

    async def sync_due(self) -> None:
        """Run due sets and rules independently, so one failure stops none."""
        if not self._access.supported:
            return
        if (
            self._library_gate is not None
            and self._library_gate.blocker("downloads") is not None
        ):
            return
        server = self._access.server_type
        async with self._access.database.read_session() as session:
            repo = CollectionRepository(session)
            rules = await repo.rules()
            groups = await repo.groups(server)
        for group in groups:
            set_generator = generator(group)
            if set_generator is None:
                continue
            async with self._access.database.read_session() as session:
                policy = await self._access.policy(session, group)
            # A set runs on its schedule once it has been synced by hand.
            if group.generated_at is None or not is_due(group.generated_at, policy):
                continue
            try:
                await self._sets.run(group, set_generator, CollectionGroupSyncResult())
            except Exception as exc:
                logger.warning("Collection set %s failed: %s", group.name, exc)
        for rule in rules:
            async with self._access.database.read_session() as session:
                row = await CollectionRepository(session).get(rule.collection_id)
                if row is None or row.server_type is not server or never_created(row):
                    continue
                policy = await self._access.policy(session, row.group, rule)
            if not is_due(rule.last_synced_at, policy):
                continue
            try:
                await self._rules.sync(rule.collection_id, scheduled=True)
            except Exception as exc:
                logger.warning("Collection rule %s failed: %s", rule.collection_id, exc)
