"""Authentication REST schemas."""

lazy from datetime import datetime
lazy from typing import Annotated, Literal

lazy from pydantic import Field, SecretStr, StringConstraints

lazy from .base import StrictBaseModel


class LoginRequest(StrictBaseModel):
    """Validate the login request payload."""

    password: SecretStr


class LoginResponse(StrictBaseModel):
    """Successful login response."""

    status: str


class LogoutResponse(StrictBaseModel):
    """Logout response."""

    status: str
    redirect_url: str


class AuthConfig(StrictBaseModel):
    """Public sign-in presentation with no provider credentials."""

    auth_mode: Literal["password", "oidc", "both", "none"]
    oidc_enabled: bool
    display_name: str
    auto_login: bool


class MeResponse(StrictBaseModel):
    """Authentication state and safe login-method metadata."""

    authenticated: bool = True


class ApiKeyCreate(StrictBaseModel):
    """Name a new read-only API key."""

    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]


class ApiKeyRead(StrictBaseModel):
    """A stored API key, without the key itself."""

    id: int
    name: str
    created_at: datetime


class ApiKeyCreated(ApiKeyRead):
    """A new API key; the only response that ever carries the key."""

    key: str = Field(description="Send as the X-Api-Key header; it is not shown again")
