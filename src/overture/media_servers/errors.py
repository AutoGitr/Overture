"""Safe provider failures shared by jobs and HTTP endpoints."""


class MediaServerError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 502,
        upstream_status_code: int | None = None,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.upstream_status_code = upstream_status_code
        super().__init__(message)
