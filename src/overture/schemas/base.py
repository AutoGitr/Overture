"""The base every API and event schema derives from."""

lazy from pydantic import BaseModel, ConfigDict


class StrictBaseModel(BaseModel):
    """Base schema that rejects accidental public contract drift."""

    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
        json_schema_serialization_defaults_required=True,
    )
