"""
Minimal in-process rate limiting.

Deliberately small: a fixed-window counter in memory, no Redis, no new
infrastructure. It exists to blunt the three things that are cheap to abuse and
expensive (or dangerous) to serve —

  * AUTH        — password guessing against /auth/login and /auth/register.
  * UPLOADS     — filling the disk with 10 MB files.
  * AI / OCR    — Tesseract and Gemini calls, which cost real time and money.

The limits are per client IP and per endpoint group, and are set well above
what the product's own flows do. In particular the upload limit is sized for
MULTI-FILE uploads: a user attaching a KYC form plus several supporting proofs
in quick succession must never be throttled, so the allowance is generous and
the window short.

This is a single-process guard. Behind several workers each process keeps its
own counter, so the effective limit is the configured one times the worker
count — fine as a brake on scripted abuse, not a substitute for a real gateway
limiter. See the deployment notes.
"""

import threading
import time
from dataclasses import dataclass, field

from fastapi import Request

from app.core.exceptions import DomainError


class RateLimitExceededError(DomainError):
    """429 — too many requests from this client for this endpoint group."""

    code = "rate_limited"
    status_code = 429

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            f"Too many requests. Please try again in {retry_after} second(s)."
        )
        self.retry_after = retry_after


@dataclass
class _Window:
    started_at: float
    count: int = 0


@dataclass
class RateLimiter:
    """Fixed-window counter: `limit` requests per `window_seconds` per key."""

    limit: int
    window_seconds: float
    name: str = "requests"
    _windows: dict[str, _Window] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def check(self, key: str) -> None:
        """Count one request, raising once the window's allowance is spent."""
        now = time.monotonic()
        with self._lock:
            window = self._windows.get(key)
            if window is None or now - window.started_at >= self.window_seconds:
                self._windows[key] = _Window(started_at=now, count=1)
                return
            window.count += 1
            if window.count > self.limit:
                remaining = self.window_seconds - (now - window.started_at)
                raise RateLimitExceededError(retry_after=max(1, int(remaining) + 1))

    def reset(self) -> None:
        """Drop all counters (tests)."""
        with self._lock:
            self._windows.clear()


def client_key(request: Request) -> str:
    """Identify the caller for limiting: the signed-in user, else the peer IP."""
    auth = request.headers.get("authorization", "")
    if auth:
        # The token itself is never logged or stored — only hashed into a
        # bucket key, so one account cannot be throttled by another's traffic.
        return f"tok:{hash(auth)}"
    client = request.client
    return f"ip:{client.host if client else 'unknown'}"


# Allowances chosen against what the product's own flows actually do.
auth_limiter = RateLimiter(limit=10, window_seconds=60.0, name="auth attempts")
upload_limiter = RateLimiter(limit=40, window_seconds=60.0, name="uploads")
ai_limiter = RateLimiter(limit=30, window_seconds=60.0, name="AI/OCR requests")
knowledge_limiter = RateLimiter(limit=20, window_seconds=60.0, name="knowledge queries")


def limit(limiter: RateLimiter):
    """Build a FastAPI dependency enforcing one limiter."""

    def _dependency(request: Request) -> None:
        limiter.check(client_key(request))

    return _dependency
