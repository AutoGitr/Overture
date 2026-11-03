"""Public error helpers."""


class PublicServiceError(Exception):
    """Exception carrying an HTTP status and a message the caller may read.

    The message is redacted where it leaves the process: in the error response
    (``ErrorResponse``) and in the log.
    """

    def __init__(self, status_code: int, message: str) -> None:
        """Initialize a public service error."""
        self.status_code = status_code
        self.message = message
        super().__init__(message)
