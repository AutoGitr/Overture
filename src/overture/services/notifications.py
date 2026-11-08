"""Tell an outside service when a run fails, from the events the UI receives.

``NOTIFY_URL`` takes one JSON ``POST`` per failure: ``title``, ``body`` and
``type`` (``failure``), the body Apprise's API takes, so one Apprise URL
reaches any notification service; other webhooks read the same fields.
"""

lazy import asyncio
lazy import logging
lazy from collections.abc import Callable, Mapping
lazy from typing import Any

lazy import httpx2

lazy from .. import protocols
lazy from ..config import Settings
lazy from ..integrations.http import create_client
lazy from ..jobs.kinds import JobKind, LifecycleStatus
lazy from ..schemas.common import JobEnvelope
lazy from ..utils.security import sanitise_error
lazy from ..ws.events import EVENT_REGISTRY

logger = logging.getLogger(__name__)

#: The events that end a failed run, and the kind of run each ends. A single
#: download failing is reported in the queue, not sent out.
FAILURE_EVENTS: Mapping[str, JobKind] = {
    f"{kind.event_prefix}.{LifecycleStatus.FAILED}": kind
    for kind in JobKind
    if kind is not JobKind.DOWNLOAD
}


def _error(event: str, payload: Any) -> str | None:
    """The error message a failure event's job carries, if any."""
    model = EVENT_REGISTRY[event].payload_model
    envelope = model.model_validate(payload) if model is not None else None
    if isinstance(envelope, JobEnvelope) and envelope.job and envelope.job.error:
        return envelope.job.error.message
    return None


class FailureNotifier:
    """Send each failed run to ``NOTIFY_URL``, never holding up the run."""

    def __init__(self, *, app_config: Settings) -> None:
        self._url = app_config.NOTIFY_URL.get_secret_value()
        self._secrets = tuple(app_config.secret_values())
        self._client: httpx2.AsyncClient | None = None
        self._sending: set[asyncio.Task[None]] = set()

    def observe(self, event: str, payload: Any) -> None:
        """Start sending a notification when *event* ends a failed run."""
        kind = FAILURE_EVENTS.get(event)
        if not self._url or kind is None:
            return
        task = asyncio.create_task(self._send(kind, _error(event, payload)))
        self._sending.add(task)
        task.add_done_callback(self._sending.discard)

    async def _send(self, kind: JobKind, error: str | None) -> None:
        self._client = self._client or create_client()
        body = {
            "title": f"Overture: {kind.label[:1].upper()}{kind.label[1:]} failed",
            "body": sanitise_error(error, secrets=self._secrets)
            if error
            else "See the run's log in Overture.",
            "type": "failure",
        }
        try:
            response = await self._client.post(self._url, json=body)
            response.raise_for_status()
        except httpx2.HTTPError as exc:
            # The URL holds its credentials, so only the error type is logged.
            logger.warning(
                "Could not send the %s failure notification: %s",
                kind.label,
                type(exc).__name__,
            )

    async def close(self) -> None:
        """Let notifications being sent finish, then close the client."""
        if self._sending:
            await asyncio.gather(*self._sending, return_exceptions=True)
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class NotifyingPublisher:
    """Publish events as *inner* does, and show each to the notifier."""

    def __init__(
        self, inner: protocols.EventPublisher, notifier: FailureNotifier
    ) -> None:
        self._inner = inner
        self._notifier = notifier

    async def broadcast(
        self,
        event: str,
        payload: Any = None,
        *,
        before_publish: Callable[[str, Any], None] | None = None,
    ) -> None:
        """Publish *event*, then notify if it ends a failed run."""
        await self._inner.broadcast(event, payload, before_publish=before_publish)
        self._notifier.observe(event, payload)

    async def broadcast_built(
        self, builder: Callable[[], tuple[str, Any] | None]
    ) -> bool:
        """Publish what *builder* builds, then notify if it ends a failed run."""
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
