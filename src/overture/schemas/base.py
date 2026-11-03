"""The base every API and event schema derives from."""

lazy from typing import Annotated

lazy from pydantic import BaseModel, ConfigDict, PlainSerializer

lazy from ..utils.security import sanitise_error

#: Free text a secret could reach: an error, a log reason, a server's message.
#: It is redacted whenever it is serialised, so no response, event or stored
#: job row carries a credential, and no field of another type is ever redacted.
type PublicText = Annotated[str, PlainSerializer(sanitise_error, return_type=str)]


class StrictBaseModel(BaseModel):
    """Base schema that rejects accidental public contract drift."""

    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
        json_schema_serialization_defaults_required=True,
    )
