"""
Rate limiting middleware.

Simple in-memory sliding window rate limiter per client IP.
For production at scale, replace the in-memory store with Redis
(e.g., using aioredis or redis-py).

Two tiers:
- Auth endpoints (login/register): stricter limit to prevent brute force
- Everything else: standard limit

Returns 429 Too Many Requests when exceeded.
"""

import time
from collections import defaultdict

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import RATE_LIMIT_AUTH_PER_MINUTE, RATE_LIMIT_PER_MINUTE


# Auth-sensitive paths that get stricter rate limiting
AUTH_PATHS = {"/api/v1/users/login", "/api/v1/users/register"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding window rate limiter per client IP."""

    def __init__(self, app):
        super().__init__(app)
        # {ip: [timestamp, timestamp, ...]}
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._last_cleanup = time.time()

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP, respecting X-Forwarded-For behind a reverse proxy."""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _cleanup_old_entries(self) -> None:
        """Periodically remove expired entries to prevent memory growth."""
        now = time.time()
        if now - self._last_cleanup < 60:  # cleanup every 60 seconds
            return
        self._last_cleanup = now
        cutoff = now - 60
        expired_keys = []
        for key, timestamps in self._requests.items():
            self._requests[key] = [t for t in timestamps if t > cutoff]
            if not self._requests[key]:
                expired_keys.append(key)
        for key in expired_keys:
            del self._requests[key]

    async def dispatch(self, request: Request, call_next) -> Response:
        self._cleanup_old_entries()

        client_ip = self._get_client_ip(request)
        path = request.url.path
        now = time.time()
        window_start = now - 60  # 1-minute window

        # Determine rate limit for this path
        is_auth_path = path in AUTH_PATHS
        limit = RATE_LIMIT_AUTH_PER_MINUTE if is_auth_path else RATE_LIMIT_PER_MINUTE

        # Build a key that separates auth vs general requests
        key = f"{client_ip}:auth" if is_auth_path else client_ip

        # Filter to requests within the window
        self._requests[key] = [t for t in self._requests[key] if t > window_start]

        if len(self._requests[key]) >= limit:
            retry_after = int(60 - (now - self._requests[key][0]))
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later."},
                headers={"Retry-After": str(max(retry_after, 1))},
            )

        self._requests[key].append(now)

        response = await call_next(request)
        # Add rate limit headers so clients know their status
        remaining = limit - len(self._requests[key])
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
