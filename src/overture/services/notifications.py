"""Announce finished runs at ``NOTIFY_URL``, as each kind's notification rule says.

Every run's terminal event passes the notifier, which reads the kind's rule
and sends one ``POST`` in the format of the service the URL names (see
:mod:`overture.integrations.notify`).
"""

lazy import asyncio
lazy import logging
lazy from collections.abc import Callable, Mapping
lazy from typing import Any

lazy import httpx2
lazy from sqlmodel import select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from .. import protocols
lazy from ..config import Settings
lazy from ..db.models.notification import NotificationRule
lazy from ..db.session import Database
lazy from ..domain import NotifyCompleted
lazy from ..integrations.http import create_client
lazy from ..integrations.notify import NotifyLevel, NotifyMessage, NotifyService
lazy from ..jobs.kinds import NOTIFIABLE_KINDS, JobKind, LifecycleStatus
lazy from ..jobs.lifecycle import label
lazy from ..jobs.progress_log import CHANGE_OUTCOMES, JobOutcome
lazy from ..schemas.common import JobEnvelope, Status, StatusResponse
lazy from ..schemas.notifications import (
    NotificationRuleRead,
    NotificationRuleWrite,
    NotificationSettingsRead,
    NotificationSettingsUpdate,
)
lazy from ..utils.errors import PublicServiceError
lazy from ..utils.security import sanitise_error
lazy from ..ws.events import EVENT_REGISTRY

logger = logging.getLogger(__name__)

_TERMINAL = (LifecycleStatus.COMPLETED, LifecycleStatus.STOPPED, LifecycleStatus.FAILED)
#: The events that end a run, and the kind and ending of each.
_ENDINGS: Mapping[str, tuple[JobKind, LifecycleStatus]] = {
    f"{kind.event_prefix}.{status}": (kind, status)
    for kind in NOTIFIABLE_KINDS
    for status in _TERMINAL
}


async def notification_rules(
    session: AsyncSession,
) -> dict[JobKind, NotificationRuleWrite]:
    """Return every kind's rule, with the defaults for a kind without a saved one."""
    saved = {rule.kind: rule for rule in await session.exec(select(NotificationRule))}
    return {
        kind: NotificationRuleWrite.model_validate(
            saved[kind].model_dump() if kind in saved else {"kind": kind}
        )
        for kind in NOTIFIABLE_KINDS
    }


def _title(kind: JobKind, status: LifecycleStatus) -> str:
    return f"Overture: {label(kind.label)} {status}"


def _summary(outcomes: Mapping[JobOutcome, int]) -> str:
    counted = [
        f"{outcome} {count}"
        for outcome, count in outcomes.items()
        if count and outcome is not JobOutcome.STARTED
    ]
    return ", ".join(counted) or "Nothing to report."


def message_for(
    rule: NotificationRuleWrite,
    status: LifecycleStatus,
    envelope: JobEnvelope,
    *,
    secrets: tuple[str, ...],
) -> NotifyMessage | None:
    """Return what *rule* announces for a run that ended with *status*, if anything."""
    if rule.scheduled_only and envelope.schedule is None:
        return None
    error = envelope.job.error.message if envelope.job and envelope.job.error else None
    detail = sanitise_error(error, secrets=secrets) if error else None
    outcomes = envelope.log_outcomes or {}
    errors = outcomes.get(JobOutcome.ERROR, 0)
    match status:
        case LifecycleStatus.FAILED if rule.failed:
            body, level = (
                detail or "See the run's log in Overture.",
                NotifyLevel.FAILURE,
            )
        case LifecycleStatus.STOPPED if rule.stopped:
            body, level = detail or "Stopped before it finished.", NotifyLevel.WARNING
        case LifecycleStatus.COMPLETED if (
            rule.completed is NotifyCompleted.ALWAYS
            or (rule.completed is NotifyCompleted.ERRORS and errors)
            or (
                rule.completed is NotifyCompleted.CHANGES
                and any(outcomes.get(outcome) for outcome in CHANGE_OUTCOMES)
            )
        ):
            body = _summary(outcomes)
            level = NotifyLevel.WARNING if errors else NotifyLevel.SUCCESS
        case _:
            return None
    return NotifyMessage(title=_title(rule.kind, status), body=body, level=level)


class RunNotifier:
    """Send each run's ending its rule announces, never holding up the run."""

    def __init__(self, *, app_config: Settings, database: Database) -> None:
        self._url = app_config.NOTIFY_URL.get_secret_value()
        self.service = NotifyService.of(self._url) if self._url else None
        self._database = database
        self._secrets = tuple(app_config.secret_values())
        self._client: httpx2.AsyncClient | None = None
        self._sending: set[asyncio.Task[None]] = set()

    def observe(self, event: str, payload: Any) -> None:
        """Start announcing the run *event* ends, when its rule says to."""
        ending = _ENDINGS.get(event)
        if self.service is None or ending is None:
            return
        task = asyncio.create_task(self._announce(event, *ending, payload))
        self._sending.add(task)
        task.add_done_callback(self._sending.discard)

    async def _announce(
        self, event: str, kind: JobKind, status: LifecycleStatus, payload: Any
    ) -> None:
        model = EVENT_REGISTRY[event].payload_model
        envelope = model.model_validate(payload) if model is not None else None
        if not isinstance(envelope, JobEnvelope):
            return
        async with self._database.read_session() as session:
            rule = (await notification_rules(session))[kind]
        message = message_for(rule, status, envelope, secrets=self._secrets)
        if message is None:
            return
        try:
            await self.send(message)
        except httpx2.HTTPError as exc:
            # The URL holds its credentials, so only the error type is logged.
            logger.warning(
                "Could not send the %s notification: %s",
                kind.label,
                type(exc).__name__,
            )

    async def send(self, message: NotifyMessage) -> None:
        """Send *message* to ``NOTIFY_URL``.

        Raises:
            PublicServiceError: 409 without ``NOTIFY_URL``.
            httpx2.HTTPError: when the service cannot be reached or refuses it.
        """
        if self.service is None:
            raise PublicServiceError(409, "Set NOTIFY_URL to send notifications")
        self._client = self._client or create_client()
        response = await self._client.post(self._url, **self.service.request(message))
        response.raise_for_status()

    async def close(self) -> None:
        """Let notifications being sent finish, then close the client."""
        if self._sending:
            await asyncio.gather(*self._sending, return_exceptions=True)
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class NotificationSettings:
    """Read and save the notification rules, and send a test notification."""

    def __init__(self, *, database: Database, notifier: RunNotifier) -> None:
        self._database = database
        self._notifier = notifier

    async def get(self) -> NotificationSettingsRead:
        """Return where notifications go and every kind's rule."""
        async with self._database.read_session() as session:
            rules = await notification_rules(session)
        service = self._notifier.service
        return NotificationSettingsRead(
            service=service,
            service_label=service.label if service else None,
            rules=[
                NotificationRuleRead.model_validate(
                    {**rule.model_dump(), "label": label(rule.kind.label)}
                )
                for rule in rules.values()
            ],
        )

    async def update(
        self, body: NotificationSettingsUpdate
    ) -> NotificationSettingsRead:
        """Save the rules *body* gives."""
        async with self._database.write_session() as session:
            for rule in body.rules:
                await session.merge(
                    NotificationRule.model_validate(rule.model_dump(mode="json"))
                )
        return await self.get()

    async def test(self) -> StatusResponse:
        """Send a test notification and say whether the service took it.

        Raises:
            PublicServiceError: 409 without ``NOTIFY_URL``, 502 when the service
                cannot be reached or refuses it.
        """
        message = NotifyMessage(
            title="Overture: Test notification",
            body="Notifications reach this service.",
            level=NotifyLevel.SUCCESS,
        )
        try:
            await self._notifier.send(message)
        except httpx2.HTTPStatusError as exc:
            status = exc.response.status_code
            raise PublicServiceError(
                502, f"The service refused the notification: HTTP {status}"
            ) from exc
        except httpx2.HTTPError as exc:
            raise PublicServiceError(
                502, f"Could not reach the service: {type(exc).__name__}"
            ) from exc
        return StatusResponse(status=Status.OK)


class NotifyingPublisher:
    """Publish events as *inner* does, and show each to the notifier."""

    def __init__(self, inner: protocols.EventPublisher, notifier: RunNotifier) -> None:
        self._inner = inner
        self._notifier = notifier

    async def broadcast(
        self,
        event: str,
        payload: Any = None,
        *,
        before_publish: Callable[[str, Any], None] | None = None,
    ) -> None:
        """Publish *event*, then let the notifier announce the run it ends."""
        await self._inner.broadcast(event, payload, before_publish=before_publish)
        self._notifier.observe(event, payload)

    async def broadcast_built(
        self, builder: Callable[[], tuple[str, Any] | None]
    ) -> bool:
        """Publish what *builder* builds, then let the notifier see it."""
        built: list[tuple[str, Any]] = []

        def recording() -> tuple[str, Any] | None:
            event = builder()
            if event is not None:
                built.append(event)
            return event

        published = await self._inner.broadcast_built(recording)
        for event, payload in built if published else ():
            self._notifier.observe(event, payload)
        return published
