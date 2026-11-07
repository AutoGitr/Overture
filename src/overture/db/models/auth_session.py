"""Revocable application sessions shared by password and OIDC sign-in."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar

lazy from sqlmodel import Field, SQLModel


class AuthSession(SQLModel, table=True):
    """A signed-in browser session; only a digest of its credential is kept."""

    __tablename__: ClassVar[Any] = "auth_sessions"

    token_hash: str = Field(primary_key=True)
    expires_at: datetime = Field(index=True)
    oidc_issuer: str | None = None
    credential_fingerprint: str | None = Field(default=None, repr=False)
    id_token: str | None = Field(default=None, repr=False)
