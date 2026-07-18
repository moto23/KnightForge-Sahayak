"""
Authentication endpoints (Phase 12) — the /auth surface.

Thin layer over AuthService. The refresh token is handled EXCLUSIVELY here as
an HttpOnly cookie scoped to /auth — JavaScript never sees it, and it is never
part of a JSON body. The access token (short-lived JWT) is returned in the
body for the client to hold in memory.

    POST /auth/register       create account + sign in
    POST /auth/login          email/password sign in
    POST /auth/refresh        rotate the refresh cookie -> new access token
    POST /auth/logout         revoke this device's refresh token
    POST /auth/logout-all     revoke every device's refresh token
    GET  /auth/me             current profile           (Bearer)
    PATCH /auth/me            update profile            (Bearer)
    GET  /auth/providers      which providers are configured
    GET  /auth/google/login   begin Google OAuth (returns consent URL)
    GET  /auth/google/callback  Google redirects here; we redirect to the app

Everything OUTSIDE /auth and /chats remains guest-accessible — Phase 12 adds
no guard to any existing endpoint.
"""

import logging
import secrets

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.dependencies import get_auth_service, get_current_user
from app.core.exceptions import DomainError, OAuthFailedError
from app.infrastructure.db.models import User
from app.schemas.auth import (
    AuthResponse,
    GoogleLoginResponse,
    LoginRequest,
    LogoutResponse,
    ProvidersResponse,
    RegisterRequest,
    UpdateProfileRequest,
    UserResponse,
)
from app.services.auth_service import AuthService, AuthSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

_STATE_COOKIE = "kf_oauth_state"


# --------------------------------------------------------------------------- #
# Cookie plumbing — the only place the refresh cookie is written or cleared.
# --------------------------------------------------------------------------- #


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=token,
        httponly=True,                        # invisible to JavaScript
        secure=settings.AUTH_COOKIE_SECURE,   # true under HTTPS
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_DAYS * 86_400,
        path="/auth",                         # only ever sent to /auth/*
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(settings.AUTH_COOKIE_NAME, path="/auth")


def _auth_response(response: Response, session: AuthSession) -> AuthResponse:
    _set_refresh_cookie(response, session.refresh_token)
    return AuthResponse(
        user=UserResponse.from_user(session.user),
        access_token=session.access_token,
        expires_in_minutes=settings.ACCESS_TOKEN_MINUTES,
    )


# --------------------------------------------------------------------------- #
# Email + password
# --------------------------------------------------------------------------- #


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=201,
    summary="Create an account and sign in",
    responses={409: {"description": "Email already registered."}},
)
async def register(
    body: RegisterRequest,
    response: Response,
    auth: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    """Register with email + password (Argon2id-hashed) and start a session."""
    return _auth_response(response, auth.register(body.email, body.password, body.full_name))


@router.post(
    "/login",
    response_model=AuthResponse,
    summary="Sign in with email and password",
    responses={401: {"description": "Incorrect email or password."}},
)
async def login(
    body: LoginRequest,
    response: Response,
    auth: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    """Verify credentials and start a session (sets the refresh cookie)."""
    return _auth_response(response, auth.login(body.email, body.password))


# --------------------------------------------------------------------------- #
# Session lifecycle
# --------------------------------------------------------------------------- #


@router.post(
    "/refresh",
    response_model=AuthResponse,
    summary="Rotate the refresh cookie and mint a new access token",
    description=(
        "Persistent login: the browser sends the HttpOnly refresh cookie; the "
        "old token is revoked (single use) and a new pair is issued. A reused "
        "token revokes every session for that account."
    ),
    responses={401: {"description": "Missing/expired/revoked refresh token."}},
)
async def refresh(
    request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    """Exchange the refresh cookie for a fresh access token (rotation)."""
    raw = request.cookies.get(settings.AUTH_COOKIE_NAME)
    try:
        return _auth_response(response, auth.refresh(raw))
    except DomainError:
        _clear_refresh_cookie(response)  # dead cookie — stop resending it
        raise


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Sign out on this device",
)
async def logout(
    request: Request,
    response: Response,
    auth: AuthService = Depends(get_auth_service),
) -> LogoutResponse:
    """Revoke this device's refresh token and clear the cookie. Idempotent."""
    auth.logout(request.cookies.get(settings.AUTH_COOKIE_NAME))
    _clear_refresh_cookie(response)
    return LogoutResponse(sessions_revoked=1)


@router.post(
    "/logout-all",
    response_model=LogoutResponse,
    summary="Sign out on every device",
    responses={401: {"description": "Not signed in."}},
)
async def logout_all(
    response: Response,
    user: User = Depends(get_current_user),
    auth: AuthService = Depends(get_auth_service),
) -> LogoutResponse:
    """Revoke every refresh token the account has, then clear this cookie."""
    revoked = auth.logout_all(user.id)
    _clear_refresh_cookie(response)
    return LogoutResponse(sessions_revoked=revoked)


# --------------------------------------------------------------------------- #
# Profile
# --------------------------------------------------------------------------- #


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Current user profile",
    responses={401: {"description": "Not signed in."}},
)
async def me(user: User = Depends(get_current_user)) -> UserResponse:
    """The signed-in account's public profile."""
    return UserResponse.from_user(user)


@router.patch(
    "/me",
    response_model=UserResponse,
    summary="Update the profile",
    responses={401: {"description": "Not signed in."}},
)
async def update_me(
    body: UpdateProfileRequest,
    user: User = Depends(get_current_user),
    auth: AuthService = Depends(get_auth_service),
) -> UserResponse:
    """Update the display name."""
    return UserResponse.from_user(auth.update_profile(user, body.full_name))


# --------------------------------------------------------------------------- #
# Google OAuth
# --------------------------------------------------------------------------- #


@router.get(
    "/providers",
    response_model=ProvidersResponse,
    summary="Which sign-in providers are configured",
)
async def providers() -> ProvidersResponse:
    """Lets the frontend hide the Google button when OAuth isn't configured."""
    return ProvidersResponse(google=AuthService.google_configured())


@router.get(
    "/google/login",
    response_model=GoogleLoginResponse,
    summary="Begin Google sign-in",
    responses={503: {"description": "Google OAuth is not configured."}},
)
async def google_login(response: Response) -> GoogleLoginResponse:
    """Return the Google consent URL (and set the CSRF state cookie)."""
    state = secrets.token_urlsafe(16)
    response.set_cookie(
        key=_STATE_COOKIE,
        value=state,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="lax",
        max_age=600,
        path="/auth",
    )
    return GoogleLoginResponse(auth_url=AuthService.google_auth_url(state))


@router.get(
    "/google/callback",
    summary="Google OAuth callback (browser navigation, not an API call)",
    include_in_schema=False,
)
async def google_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    auth: AuthService = Depends(get_auth_service),
) -> RedirectResponse:
    """Finish Google sign-in, set the refresh cookie, bounce to the app."""
    frontend = settings.FRONTEND_URL.rstrip("/")
    if error or not code:
        return RedirectResponse(f"{frontend}/signin?error=google_cancelled")
    if not state or state != request.cookies.get(_STATE_COOKIE):
        return RedirectResponse(f"{frontend}/signin?error=oauth_state_mismatch")
    try:
        session = auth.google_login(code)
    except (OAuthFailedError, DomainError) as exc:
        logger.warning("Google callback failed: %s", exc)
        return RedirectResponse(f"{frontend}/signin?error=google_failed")
    redirect = RedirectResponse(f"{frontend}/dashboard?signin=google")
    redirect.delete_cookie(_STATE_COOKIE, path="/auth")
    _set_refresh_cookie(redirect, session.refresh_token)
    return redirect
