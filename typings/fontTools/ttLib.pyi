"""The part of fontTools' TTFont that Overture uses; fontTools ships no types."""

from os import PathLike
from types import TracebackType
from typing import Self

class TTFont:
    def __init__(
        self, file: str | PathLike[str], *, lazy: bool | None = None
    ) -> None: ...
    def __enter__(self) -> Self: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...
    def getBestCmap(self) -> dict[int, str] | None: ...  # noqa: N802 -- fontTools' name
