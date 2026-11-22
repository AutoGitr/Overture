"""What the dead code test reads of vulture, which ships no types."""

from collections.abc import Sequence

class Item:
    typ: str
    name: str
    filename: str
    first_lineno: int
    message: str
    confidence: int

class Vulture:
    def __init__(
        self,
        verbose: bool = ...,
        ignore_names: Sequence[str] | None = ...,
        ignore_decorators: Sequence[str] | None = ...,
    ) -> None: ...
    def scavenge(
        self, paths: Sequence[str], exclude: Sequence[str] | None = ...
    ) -> None: ...
    def get_unused_code(
        self, min_confidence: int = ..., sort_by_size: bool = ...
    ) -> list[Item]: ...
