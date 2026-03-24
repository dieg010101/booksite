"""
Global error handling.

Catches unhandled exceptions, logs them properly, and returns
clean error responses instead of leaking stack traces to clients.
"""

import logging
import traceback

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.config import DEBUG

logger = logging.getLogger(__name__)


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unhandled exceptions."""
    logger.error(
        f"Unhandled exception on {request.method} {request.url.path}: {exc}",
        exc_info=True,
    )

    if DEBUG:
        # In dev, include the error details for easier debugging
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error",
                "error": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
    else:
        # In production, never leak internals
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
