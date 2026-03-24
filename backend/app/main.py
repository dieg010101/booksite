"""
Social Book Catalog — FastAPI Application
==========================================

Production-hardened entry point with:
- CORS middleware for SvelteKit frontend
- Rate limiting (per-IP sliding window)
- Structured logging
- Global error handling
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import CORS_ORIGINS
from app.core.errors import global_exception_handler
from app.core.logging import setup_logging
from app.core.rate_limit import RateLimitMiddleware
from app.routers.books import router as books_router
from app.routers.comments import router as comments_router
from app.routers.contributors import router as contributors_router
from app.routers.feed import router as feed_router
from app.routers.google_books import router as google_books_router
from app.routers.lists import router as lists_router
from app.routers.users import router as users_router

# ── Initialize logging before anything else ───────────────────────────────
setup_logging()

app = FastAPI(
    title="Social Book Catalog",
    description="A Letterboxd-style platform for books",
    version="0.1.0",
)

# ── Middleware (order matters — outermost first) ──────────────────────────
# Rate limiting runs before CORS so rate-limited requests don't waste
# time on CORS processing.
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global error handler ─────────────────────────────────────────────────
app.add_exception_handler(Exception, global_exception_handler)

# ── Routers ───────────────────────────────────────────────────────────────
app.include_router(users_router)
app.include_router(books_router)
app.include_router(feed_router)
app.include_router(comments_router)
app.include_router(contributors_router)
app.include_router(lists_router)
app.include_router(google_books_router)


# ── Health checks ─────────────────────────────────────────────────────────
@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/health/db")
def db_health_check():
    from sqlalchemy import text as sa_text
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        db.execute(sa_text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        return {"status": "error", "database": str(e)}
    finally:
        db.close()
