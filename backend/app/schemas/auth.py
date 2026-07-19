"""Pydantic request/response DTOs for the /auth endpoints (Phase 12)."""

import re
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.infrastructure.db.models import User

# --------------------------------------------------------------------------- #
# Password policy — the SINGLE definition, mirrored verbatim by the sign-in
# form in frontend/src/app/signin/page.tsx.
#
# The two MUST agree. When they drifted (frontend min 8, backend min 8 with no
# character-class rules) the failure mode was silent: a password the form
# happily accepted could still be refused by the API, and the user was shown a
# generic "could not create the account". Every rule below is therefore stated
# once, checked here, and re-stated identically in the client so the inline
# error appears before the request is ever sent.
# --------------------------------------------------------------------------- #

PASSWORD_MIN_LENGTH = 6
PASSWORD_MAX_LENGTH = 128

_PASSWORD_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[a-z]"), "one lowercase letter"),
    (re.compile(r"[A-Z]"), "one uppercase letter"),
    (re.compile(r"[0-9]"), "one number"),
    (re.compile(r"[^A-Za-z0-9]"), "one special character"),
)


def validate_password(value: str) -> str:
    """
    Enforce the shared password policy.

    Reports EVERY unmet rule at once rather than the first one, so a user is
    not sent round the loop four times. The password itself is never logged or
    echoed back — only the names of the rules it failed.
    """
    if len(value) < PASSWORD_MIN_LENGTH:
        raise ValueError(
            f"Password must be at least {PASSWORD_MIN_LENGTH} characters."
        )
    missing = [name for pattern, name in _PASSWORD_RULES if not pattern.search(value)]
    if missing:
        raise ValueError("Password must contain at least " + ", ".join(missing) + ".")
    return value


class RegisterRequest(BaseModel):
    """Body of POST /auth/register."""

    email: EmailStr = Field(..., description="Account email (unique).")
    password: str = Field(
        ...,
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
        description=(
            f"At least {PASSWORD_MIN_LENGTH} characters, including an uppercase "
            "letter, a lowercase letter, a number and a special character."
        ),
    )
    full_name: str = Field(
        ..., min_length=1, max_length=120, description="Display name (required)."
    )

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return validate_password(value)

    @field_validator("full_name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        """Trim, and reject a whitespace-only name (which is not a name)."""
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Please enter your name.")
        return trimmed


class LoginRequest(BaseModel):
    """Body of POST /auth/login."""

    email: EmailStr = Field(..., description="Account email.")
    password: str = Field(..., min_length=1, max_length=128, description="Password.")


class UpdateProfileRequest(BaseModel):
    """Body of PATCH /auth/me."""

    full_name: str = Field(..., min_length=1, max_length=120, description="New display name.")

    @field_validator("full_name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        """Same rule as registration: a name of only spaces is not a name."""
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Please enter your name.")
        return trimmed


class UserResponse(BaseModel):
    """Public view of an account — never includes hashes or token data."""

    user_id: str = Field(..., description="Stable account id.")
    email: str = Field(..., description="Account email.")
    full_name: str = Field(..., description="Display name.")
    has_password: bool = Field(..., description="False for Google-only accounts.")
    google_linked: bool = Field(..., description="True when linked to a Google account.")
    created_at: datetime = Field(..., description="Account creation (UTC).")

    @classmethod
    def from_user(cls, user: User) -> "UserResponse":
        return cls(
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            has_password=user.password_hash is not None,
            google_linked=user.google_sub is not None,
            created_at=user.created_at,
        )


class AuthResponse(BaseModel):
    """Login/register/refresh result. The refresh token travels ONLY as an
    HttpOnly cookie — it never appears in this body."""

    user: UserResponse = Field(..., description="The signed-in account.")
    access_token: str = Field(..., description="Short-lived JWT for the Authorization header.")
    token_type: str = Field(default="bearer", description="Always 'bearer'.")
    expires_in_minutes: int = Field(..., description="Access-token lifetime.")


class LogoutResponse(BaseModel):
    """Result of POST /auth/logout and /auth/logout-all."""

    logged_out: bool = Field(default=True, description="Always true (idempotent).")
    sessions_revoked: int = Field(
        default=1, description="How many refresh tokens were revoked."
    )


class ProvidersResponse(BaseModel):
    """Which optional sign-in providers this deployment has configured."""

    google: bool = Field(..., description="True when Google OAuth is configured.")


class GoogleLoginResponse(BaseModel):
    """Where the frontend should send the browser to start Google sign-in."""

    auth_url: str = Field(..., description="Google consent-screen URL (redirect the user).")
