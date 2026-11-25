"""AddedPreset model - an OvertureDB preset as it was when last added."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar

lazy from sqlmodel import JSON, Field, SQLModel

lazy from ..columns import typed_columns


class AddedPreset(SQLModel, table=True):
    """A preset added to this install, kept to tell when OvertureDB changes it.

    What it created is ordinary and the person's own; the collections and
    groups name the preset and their item in it, so a newer version can
    update them when the person asks.
    """

    __tablename__: ClassVar[Any] = "added_presets"

    #: The preset's OvertureDB ID, such as ``holidays``.
    id: str = Field(primary_key=True)
    #: The ``CollectionPresetFile`` as it was added.
    file: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    added_at: datetime = Field(nullable=False)


typed_columns(AddedPreset)
