"""
AuthService (Phase 12) — accounts, sessions-across-devices, Google OAuth.

Token architecture (the "secure JWT" shape):

    access token   short-lived JWT, returned in the JSON body, held in JS
                   memory only (never localStorage, never a cookie)
    refresh token  opaque 256-bit secret in an HttpOnly cookie; only its
                   SHA-256 lives in the database

Refresh ROTATION: every /auth/refresh revokes the presented token and issues
a new one. Presenting an already-revoked token is treated as theft (someone
replayed a stolen cookie) and revokes every session the user has.

Guest mode is preserved by construction: nothing here is consulted by any
pre-Phase-12 endpoint. Auth guards exist only on /auth/me and /chats/*.
"""

import logging
from datetime import datetime, timezone
from urllib.parse import urlencode

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    OAuthFailedError,
    OAuthNotConfiguredError,
)
from app.core.security import (
    create_access_token,
    hash_password,
    hash_token,
    new_refresh_token,
    refresh_expiry,
    verify_password,
)
from app.infrastructure.db.models import RefreshToken, User

try:  # Only Google OAuth needs an HTTP client; guarded like every optional dep.
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


class AuthSession:
    """What a successful login/refresh hands back to the route layer."""

    __slots__ = ("user", "access_token", "refresh_token")

    def __init__(self, user: User, access_token: str, refresh_token: str) -> None:
        self.user = user
        self.access_token = access_token
        self.refresh_token = refresh_token  # raw value — for the cookie only


class AuthService:
    """All account and token use-cases, one DB session per request."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------ #
    # Email + password
    # ------------------------------------------------------------------ #

    def register(self, email: str, password: str, full_name: str) -> AuthSession:
        """Create an account (Argon2id-hashed password) and sign it in."""
        normalized = email.strip().lower()
        existing = self._db.scalar(select(User).where(User.email == normalized))
        if existing is not None:
            raise EmailAlreadyRegisteredError(normalized)
        user = User(
            email=normalized,
            password_hash=hash_password(password),
            full_name=full_name.strip(),
        )
        self._db.add(user)
        self._db.flush()  # assign the id before issuing tokens
        session = self._issue(user)
        self._db.commit()
        logger.info("Account registered: %s", user.id)
        return session

    def login(self, email: str, password: str) -> AuthSession:
        """Verify credentials; identical error whether email or password is wrong."""
        normalized = email.strip().lower()
        user = self._db.scalar(select(User).where(User.email == normalized))
        if user is None or not user.password_hash:
            # Hash anyway so response timing can't reveal whether the email exists.
            hash_password(password)
            raise InvalidCredentialsError()
        if not verify_password(password, user.password_hash):
            raise InvalidCredentialsError()
        session = self._issue(user)
        self._db.commit()
        logger.info("Login: %s", user.id)
        return session

    # ------------------------------------------------------------------ #
    # Refresh rotation / logout
    # ------------------------------------------------------------------ #

    def refresh(self, raw_token: str | None) -> AuthSession:
        """
        Rotate a refresh token: revoke the presented one, issue a fresh pair.

        Reuse detection: a token that exists but is already revoked means the
        cookie was replayed — every session of that user is revoked.
        """
        if not raw_token:
            raise InvalidRefreshTokenError("No session cookie present.")
        record = self._db.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token))
        )
        if record is None:
            raise InvalidRefreshTokenError()
        if record.revoked:
            logger.warning(
                "Refresh token REUSE for user %s — revoking all sessions", record.user_id
            )
            self._revoke_all(record.user_id)
            self._db.commit()
            raise InvalidRefreshTokenError("Session invalidated for your security — sign in again.")
        if record.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
            raise InvalidRefreshTokenError()

        record.revoked = True  # rotation: the old token is single-use
        user = self._db.get(User, record.user_id)
        if user is None:  # account deleted while the cookie lived on
            raise InvalidRefreshTokenError()
        session = self._issue(user)
        self._db.commit()
        return session

    def logout(self, raw_token: str | None) -> None:
        """Revoke the presented refresh token (this device only). Idempotent."""
        if not raw_token:
            return
        self._db.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == hash_token(raw_token))
            .values(revoked=True)
        )
        self._db.commit()

    def logout_all(self, user_id: str) -> int:
        """Revoke EVERY refresh token the user has (all devices)."""
        count = self._revoke_all(user_id)
        self._db.commit()
        logger.info("Logout-all for %s: %d sessions revoked", user_id, count)
        return count

    def _revoke_all(self, user_id: str) -> int:
        result = self._db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False))
            .values(revoked=True)
        )
        return result.rowcount or 0

    # ------------------------------------------------------------------ #
    # Profile
    # ------------------------------------------------------------------ #

    def update_profile(self, user: User, full_name: str) -> User:
        """The one editable profile field today."""
        user.full_name = full_name.strip()
        self._db.add(user)
        self._db.commit()
        return user

    # ------------------------------------------------------------------ #
    # Google OAuth (authorization-code flow)
    # ------------------------------------------------------------------ #

    @staticmethod
    def google_configured() -> bool:
        return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)

    @staticmethod
    def google_auth_url(state: str) -> str:
        """Where to send the browser to ask Google for consent."""
        if not AuthService.google_configured():
            raise OAuthNotConfiguredError()
        query = urlencode(
            {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "access_type": "online",
                "prompt": "select_account",
            }
        )
        return f"{_GOOGLE_AUTH_URL}?{query}"

    def google_login(self, code: str) -> AuthSession:
        """Exchange the callback code, upsert the user, and sign them in."""
        if not self.google_configured():
            raise OAuthNotConfiguredError()
        if httpx is None:
            raise OAuthFailedError("httpx is not installed on the backend.")
        try:
            with httpx.Client(timeout=15.0) as client:
                token_response = client.post(
                    _GOOGLE_TOKEN_URL,
                    data={
                        "code": code,
                        "client_id": settings.GOOGLE_CLIENT_ID,
                        "client_secret": settings.GOOGLE_CLIENT_SECRET,
                        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                        "grant_type": "authorization_code",
                    },
                )
                token_response.raise_for_status()
                google_access = token_response.json().get("access_token", "")
                userinfo_response = client.get(
                    _GOOGLE_USERINFO_URL,
                    headers={"Authorization": f"Bearer {google_access}"},
                )
                userinfo_response.raise_for_status()
                info = userinfo_response.json()
        except OAuthFailedError:
            raise
        except Exception as exc:  # network/HTTP/JSON — one typed 502
            raise OAuthFailedError(str(exc)) from exc

        sub = str(info.get("sub") or "")
        email = str(info.get("email") or "").strip().lower()
        if not sub or not email:
            raise OAuthFailedError("Google did not return a subject/email.")

        user = self._db.scalar(select(User).where(User.google_sub == sub))
        if user is None:
            # Link by email if an email/password account already exists.
            user = self._db.scalar(select(User).where(User.email == email))
            if user is not None:
                user.google_sub = sub
            else:
                user = User(
                    email=email,
                    password_hash=None,
                    full_name=str(info.get("name") or ""),
                    google_sub=sub,
                )
                self._db.add(user)
                self._db.flush()
        session = self._issue(user)
        self._db.commit()
        logger.info("Google login: %s", user.id)
        return session

    # ------------------------------------------------------------------ #
    # Token issuance
    # ------------------------------------------------------------------ #

    def _issue(self, user: User) -> AuthSession:
        """Mint an access JWT + a fresh refresh token row (hash at rest)."""
        raw = new_refresh_token()
        self._db.add(
            RefreshToken(
                user_id=user.id,
                token_hash=hash_token(raw),
                expires_at=refresh_expiry(),
                revoked=False,
            )
        )
        return AuthSession(
            user=user,
            access_token=create_access_token(user.id),
            refresh_token=raw,
        )
