"""
Database connection and session management.
============================================

This module provides:
  • `engine`      — the SQLAlchemy Engine connected to PostgreSQL.
  • `SessionLocal` — a session factory (call it to get a session).
  • `get_db()`    — a generator that yields a session and ensures cleanup.
                    Use as a FastAPI dependency or call manually.

Connection string:
──────────────────
Reads DATABASE_URL from the environment. Falls back to the local Docker
Compose PostgreSQL container defined in your docker-compose.yaml:

    services:
      db:
        image: postgres:15
        environment:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: localpassword
          POSTGRES_DB: book_platform
        ports:
          - '5432:5432'

The default URL matches these exact settings so `docker compose up db`
is all you need for local development.

Why sync (not async)?
─────────────────────
The v4 models use `declarative_base()` (sync ORM). Async SQLAlchemy
requires `AsyncSession`, `create_async_engine`, and an async-compatible
driver (asyncpg). This can be added later without changing the models —
it's purely a session/engine concern. For now, sync psycopg2 is simpler
and sufficient for testing and early development.

Reference: HPPG ch. 1 — Atkinson: start with the simplest configuration
that works, then optimize. Connection pooling, async drivers, and
read-replica routing are scale-up concerns, not day-one requirements.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ── Connection URL ──
# Format: postgresql://user:password@host:port/dbname
#
# In production, this should come from a secrets manager or environment
# variable — NEVER hardcode credentials in source code.
#
# The Docker Compose default matches your existing docker-compose.yaml:
#   POSTGRES_USER=postgres, POSTGRES_PASSWORD=localpassword,
#   POSTGRES_DB=book_platform, port 5432.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:localpassword@localhost:5432/book_platform",
)

# ── Engine ──
# pool_pre_ping=True: Tests connections before handing them to the app.
# If the database restarted or a connection went stale, SQLAlchemy
# transparently reconnects instead of raising a "connection closed" error.
#
# Reference: DBRE ch. 8 — Campbell & Majors: connection health checks
# prevent cascading failures when the database restarts under load.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    echo=False,  # Set to True to see all SQL in stdout (noisy but useful for debugging)
)

# ── Session Factory ──
# autocommit=False: You must explicitly call session.commit().
#   This prevents accidental implicit commits mid-transaction.
# autoflush=False: Prevents SQLAlchemy from auto-flushing pending changes
#   before every query. You control when flushes happen (usually at commit).
#   This avoids surprising IntegrityErrors mid-query.
#
# Reference: AoP — Fontaine: explicit transaction boundaries are safer
# than implicit ones. You should always know when you're committing.
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


def get_db():
    """
    Yield a database session and ensure it's closed after use.

    Usage as a FastAPI dependency:
    ──────────────────────────────
        from fastapi import Depends
        from app.database import get_db

        @app.get("/users/{user_id}")
        def get_user(user_id: str, db: Session = Depends(get_db)):
            return db.query(User).filter(User.user_id == user_id).first()

    Usage in scripts or tests:
    ──────────────────────────
        from app.database import get_db

        db = next(get_db())
        try:
            # ... do work ...
            db.commit()
        finally:
            db.close()

    The `finally` block (via the generator's cleanup) ensures the
    connection is returned to the pool even if an exception occurs.
    Leaked connections exhaust the pool and cause the app to hang.

    Reference: DBRE ch. 8 — connection pool exhaustion is a top-3
    cause of production database outages.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
