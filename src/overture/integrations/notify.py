"""The body each notification service takes, chosen by the ``NOTIFY_URL`` it is sent to.

Discord, Slack, Telegram, Gotify and ntfy.sh webhooks are recognised by their
address and get the body their API documents. Any other URL gets the JSON an
Apprise API server takes, which reaches every service Apprise supports.
"""

lazy import re
lazy from dataclasses import dataclass
lazy from enum import StrEnum
lazy from typing import Any
lazy from urllib.parse import parse_qs, urlsplit

#: A Discord webhook's path, with or without an API version.
_DISCORD_WEBHOOK = re.compile(r"^/api(?:/v\d+)?/webhooks/")
#: The longest message Discord and Telegram accept, in characters.
_DISCORD_LIMIT = 2000
_TELEGRAM_LIMIT = 4096


class NotifyLevel(StrEnum):
    """How a notification reads; the values are Apprise's notification types."""

    SUCCESS = "success"
    WARNING = "warning"
    FAILURE = "failure"


@dataclass(frozen=True, slots=True)
class NotifyMessage:
    """One notification, before a service's format is applied."""

    title: str
    body: str
    level: NotifyLevel


class NotifyService(StrEnum):
    """A service ``NOTIFY_URL`` can name; ``apprise`` covers every other URL."""

    APPRISE = "apprise"
    DISCORD = "discord"
    SLACK = "slack"
    TELEGRAM = "telegram"
    GOTIFY = "gotify"
    NTFY = "ntfy"

    @classmethod
    def of(cls, url: str) -> NotifyService:
        """Return the service *url* is a webhook of."""
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        path = parts.path.rstrip("/")
        if (
            host in {"discord.com", "discordapp.com"} or host.endswith(".discord.com")
        ) and _DISCORD_WEBHOOK.match(path):
            return cls.DISCORD
        if host == "hooks.slack.com":
            return cls.SLACK
        if host == "api.telegram.org" and path.endswith("/sendMessage"):
            return cls.TELEGRAM
        if host == "ntfy.sh":
            return cls.NTFY
        if path.endswith("/message") and "token" in parse_qs(parts.query):
            return cls.GOTIFY
        return cls.APPRISE

    @property
    def label(self) -> str:
        """Return how the service is named to users."""
        return _LABELS[self]

    def request(self, message: NotifyMessage) -> dict[str, Any]:
        """Return the keyword arguments of the ``POST`` that sends *message*."""
        match self:
            case NotifyService.DISCORD:
                # An error can quote "@everyone"; a notification pings no one.
                return {
                    "json": {
                        "content": _fit(
                            f"**{message.title}**", message.body, _DISCORD_LIMIT
                        ),
                        "allowed_mentions": {"parse": []},
                    }
                }
            case NotifyService.SLACK:
                # Slack reads <...> as links and mentions such as <!channel>.
                title, body = _slack_text(message.title), _slack_text(message.body)
                return {"json": {"text": f"*{title}*\n{body}"}}
            case NotifyService.TELEGRAM:
                # The chat comes from the URL's chat_id parameter.
                return {
                    "json": {"text": _fit(message.title, message.body, _TELEGRAM_LIMIT)}
                }
            case NotifyService.GOTIFY:
                priority = 8 if message.level is NotifyLevel.FAILURE else 5
                return {
                    "json": {
                        "title": message.title,
                        "message": message.body,
                        "priority": priority,
                    }
                }
            case NotifyService.NTFY:
                # ntfy publishes the request body to the URL's topic as is.
                # Titles are Overture's own words, so they fit in a header.
                return {
                    "content": message.body.encode(),
                    "headers": {
                        "Title": message.title,
                        "Tags": _NTFY_EMOJI[message.level],
                    },
                }
            case NotifyService.APPRISE:
                return {
                    "json": {
                        "title": message.title,
                        "body": message.body,
                        "type": message.level.value,
                    }
                }


_LABELS = {
    NotifyService.APPRISE: "Apprise or webhook",
    NotifyService.DISCORD: "Discord",
    NotifyService.SLACK: "Slack",
    NotifyService.TELEGRAM: "Telegram",
    NotifyService.GOTIFY: "Gotify",
    NotifyService.NTFY: "ntfy",
}


#: The emoji ntfy shows for each level, by the tag that names it.
_NTFY_EMOJI = {
    NotifyLevel.SUCCESS: "white_check_mark",
    NotifyLevel.WARNING: "warning",
    NotifyLevel.FAILURE: "rotating_light",
}


def _fit(title: str, body: str, limit: int) -> str:
    """Join *title* and *body*, cutting the body short to fit *limit* characters."""
    text = f"{title}\n{body}"
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def _slack_text(text: str) -> str:
    """Escape the characters Slack's message format gives a meaning."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
