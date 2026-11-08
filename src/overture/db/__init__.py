"""Database models and the schema they declare."""

from sqlmodel import SQLModel

from .tables import table_models

table_models()

#: Schema for every table the models declare. Depend on this rather than on
#: ``SQLModel.metadata`` directly: reaching it through this module is what
#: guarantees every model has been imported and registered its table.
metadata = SQLModel.metadata

__all__ = ["metadata"]
