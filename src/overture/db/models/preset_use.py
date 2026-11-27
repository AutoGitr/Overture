"""PresetUse model - the OvertureDB preset item a collection or set was saved from."""

lazy from typing import Any, ClassVar

lazy from sqlmodel import JSON, CheckConstraint, Field, SQLModel

lazy from ..columns import typed_columns


class PresetUse(SQLModel, table=True):
    """A collection or set saved from an OvertureDB preset, and the item as it was.

    What was saved is the person's own; the item OvertureDB published is kept
    so a change OvertureDB makes to it later can be shown and taken alone.
    """

    __tablename__: ClassVar[Any] = "preset_uses"
    __table_args__ = (
        CheckConstraint(
            "(collection_id IS NOT NULL) + (group_id IS NOT NULL) = 1",
            name="ck_preset_uses_owner",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    #: The preset's OvertureDB ID, such as ``holidays``.
    preset_id: str
    #: The collection's title or the set's group name in the preset.
    item: str
    #: The ``PortableCollection`` or ``PortableGroup`` as OvertureDB published
    #: it when it was saved, or when its changes were last taken or kept.
    definition: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    collection_id: int | None = Field(
        default=None,
        foreign_key="media_collections.id",
        ondelete="CASCADE",
        unique=True,
    )
    group_id: int | None = Field(
        default=None,
        foreign_key="collection_groups.id",
        ondelete="CASCADE",
        unique=True,
    )


typed_columns(PresetUse)
