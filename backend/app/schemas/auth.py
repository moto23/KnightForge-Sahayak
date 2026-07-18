"""Pydantic request/response DTOs for the /auth endpoints (Phase 12)."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.infrastructure.db.models import User


class RegisterRequest(BaseModel):
    """Body of POST /auth/register."""

    email: EmailStr = Field(..., description="Account email (unique).")
    password: str = Field(..., min_length=8, max_length=128, description="At least 8 chars.")
    full_name: str = Field(default="", max_length=120, description="Display name.")


class LoginRequest(BaseModel):
    """Body of POST /auth/login."""

    email: EmailStr = Field(..., description="Account email.")
    password: str = Field(..., min_length=1, max_length=128, description="Password.")


class UpdateProfileRequest(BaseModel):
    """Body of PATCH /auth/me."""

    full_name: str = Field(..., min_length=1, max_length=120, description="New display name.")


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
