"""
Security primitives (Phase 12) — hashing and token crafting, nothing else.

Pure functions over the configured secrets:

    hash_password / verify_password   Argon2id (argon2-cffi defaults)
    create_access_token               short-lived signed JWT (HS256)
    decode_access_token               verify + parse; typed 401 on any problem
    new_refresh_token                 opaque 256-bit random secret
    hash_token                        SHA-256 — only the HASH is stored

Design: the refresh token is NOT a JWT. It is a random secret whose hash
lives in the database, which is what enables rotation, revocation ("logout
all devices"), and reuse detection — none of which stateless JWTs can do.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

from app.core.config import settings
from app.core.exceptions import AuthRequiredError

# argon2-cffi's default profile IS Argon2id (RFC 9106 low-memory profile).
_hasher = PasswordHasher()


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #


def hash_password(password: str) -> str:
    """Argon2id hash, salt embedded in the encoded string."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time verification; False for ANY failure, never an exception."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# --------------------------------------------------------------------------- #
# Access tokens (JWT — stateless, short-lived, kept in JS memory client-side)
# --------------------------------------------------------------------------- #


def create_access_token(user_id: str) -> str:
    """Signed JWT identifying one user for ACCESS_TOKEN_MINUTES."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> str:
    """
    Verify signature + expiry and return the user id.

    Raises AuthRequiredError (typed 401) for anything wrong — expired,
    malformed, bad signature, wrong type — so routes have exactly one branch.
    """
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthRequiredError("Your session token expired — refresh or sign in.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthRequiredError("Invalid session token — sign in again.") from exc
    if payload.get("type") != "access" or not payload.get("sub"):
        raise AuthRequiredError("Invalid session token — sign in again.")
    return str(payload["sub"])


# --------------------------------------------------------------------------- #
# Refresh tokens (opaque, hashed at rest, rotated on every use)
# --------------------------------------------------------------------------- #


def new_refresh_token() -> str:
    """256 bits of URL-safe randomness — the value set in the HttpOnly cookie."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 hex digest — the ONLY form a refresh token is stored in."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_expiry() -> datetime:
    """Absolute UTC expiry for a refresh token issued now."""
    return datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_DAYS)
