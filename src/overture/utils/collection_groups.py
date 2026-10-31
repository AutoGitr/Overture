"""Group membership for collections managed by Overture."""

lazy from ..domain import UNGROUPED_GROUP


def collection_group(name: str | None) -> str:
    """Assign missing membership to the reserved fallback group."""
    name = name.strip() if name else ""
    return name or UNGROUPED_GROUP
