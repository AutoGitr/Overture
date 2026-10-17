"""Public error and payload redaction helpers."""

lazy from .security import sanitise_error


class PublicServiceError(Exception):
    """Exception carrying an HTTP-compatible public error message."""

    def __init__(self, status_code: int, message: str) -> None:
        """Initialize a public service error."""
        self.status_code = status_code
        self.message = public_error_message(message)
        super().__init__(self.message)


def public_error_message(error: object) -> str:
    """Return a redacted message safe for HTTP, WebSocket, and job output."""
    return sanitise_error(str(error))


def public_error_payload(error: object, *, code: str = "error") -> dict[str, str]:
    """Return a stable public error object."""
    return {"code": code, "message": public_error_message(error)}
