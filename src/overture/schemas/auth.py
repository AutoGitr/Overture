"""Authentication REST schemas."""

lazy from typing import Literal

lazy from pydantic import SecretStr

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
