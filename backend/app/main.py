"""
Minimal FastAPI application.
=============================

This is NOT the full API — it's a smoke-test entry point that proves:
  1. The app starts.
  2. The database is reachable.
  3. The schema (models) can be loaded.

Run with:
    uvicorn app.main:app --reload

Or from the project root:
    python -m uvicorn app.main:app --reload

The full API routes (users, books, entries, feed, etc.) will be added
in separate router modules under `app/routers/` as the project grows.
"""

from fastapi import FastAPI
from app.routers.users import router as users_router
from app.routers.books import router as books_router
from app.routers.feed import router as feed_router

app = FastAPI(
    title="Social Book Catalog",
    description="A Letterboxd-style platform for books",
    version="0.1.0",
)

app.include_router(users_router)
app.include_router(books_router)
app.include_router(feed_router)


@app.get("/health")
def health_check():
    """
    Basic health check endpoint.

    Returns 200 if the app is running. Does NOT check the database —
    that's what the /health/db endpoint below is for.
    """
    return {"status": "ok"}


@app.get("/health/db")
def db_health_check():
    """
    Database connectivity check.

    Executes a trivial query (SELECT 1) to verify:
      • The connection pool can acquire a connection.
      • PostgreSQL is accepting queries.
      • The network path between app and DB is working.

    If this fails, the database container is likely down or unreachable.
    Run: docker compose up db
    """
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
