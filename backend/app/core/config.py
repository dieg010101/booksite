"""
Centralized application configuration.

All settings are loaded from environment variables with dev-friendly defaults.
In production, set these via .env file, Docker env, or your deployment platform.

CRITICAL: Change SECRET_KEY in production. The dev default is insecure.
"""

import os
import logging

logger = logging.getLogger(__name__)

# ── Security ──────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

if SECRET_KEY == "dev-secret-change-me-in-production":
    logger.warning(
        "⚠️  Using default SECRET_KEY — set the SECRET_KEY environment variable in production!"
    )

# ── Database ──────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:localpassword@localhost:5432/book_platform",
)

# ── CORS ──────────────────────────────────────────────────────────────────
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:3000,http://localhost:8080",
).split(",")

# ── Rate Limiting ─────────────────────────────────────────────────────────
# Requests per minute for authenticated endpoints
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
# Requests per minute for auth endpoints (login/register) — lower to prevent brute force
RATE_LIMIT_AUTH_PER_MINUTE = int(os.getenv("RATE_LIMIT_AUTH_PER_MINUTE", "10"))

# ── Google Books API ──────────────────────────────────────────────────────
GOOGLE_BOOKS_API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY", "")
GOOGLE_BOOKS_BASE_URL = "https://www.googleapis.com/books/v1/volumes"

# ── Environment ───────────────────────────────────────────────────────────
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
DEBUG = ENVIRONMENT == "development"
