"""
Pytest fixtures for database testing.
======================================

How this works:
───────────────
1. `test_engine` (session-scoped): Creates a SQLAlchemy engine connected
   to the test database (same Docker Compose PostgreSQL, but we could use
   a separate test DB if desired).

2. `tables` (session-scoped): Runs `Base.metadata.create_all()` once at
   the start of the test session — this creates ALL tables, indexes,
   constraints, enums, and the ltree extension from your v4 models.
   After all tests finish, `drop_all()` tears everything down.

   This is the critical test: if create_all() succeeds, your entire schema
   — all 13 models, 21 indexes, 3 enums, ltree extension, partial indexes,
   covering indexes, GiST indexes, GIN indexes — is valid PostgreSQL DDL.

3. `db_session` (function-scoped): Yields a fresh session per test,
   wrapped in a transaction that is ROLLED BACK after each test. This
   means tests don't pollute each other — every test starts with empty
   tables (except for the schema structure).

4. `client` (function-scoped): A FastAPI TestClient wired to a rolled-back
   DB session. Used by the router tests (test_users_router.py, etc.).

Requirements:
─────────────
• PostgreSQL running (docker compose up db)
• The ltree extension must be available (it is in the official postgres:15 image)
• pip install pytest psycopg2-binary sqlalchemy uuid6 httpx

Environment:
────────────
Set TEST_DATABASE_URL to override the default. If unset, falls back to
the same local Docker Compose database (which is fine for development).

In CI, you'd typically spin up a disposable PostgreSQL container and
point TEST_DATABASE_URL to it.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Import Base — this triggers the import of all models via app/models.py,
# registering them on Base.metadata. Without this, create_all() would
# create an empty schema.
from app.models import Base


# ── Test database URL ──
# Default: same as dev (Docker Compose PostgreSQL).
# Override with TEST_DATABASE_URL env var for CI or isolated test DBs.
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:localpassword@localhost:5432/book_platform",
)


@pytest.fixture(scope="session")
def test_engine():
    """
    Create a SQLAlchemy engine for the test database.

    Session-scoped: one engine for the entire test run.
    echo=True so you can see the DDL statements during create_all()
    (useful for verifying your schema is correct).
    """
    engine = create_engine(TEST_DATABASE_URL, echo=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def tables(test_engine):
    """
    Create all tables from the ORM models, run tests, then drop everything.

    This is the FIRST real validation of your schema. If this fixture
    succeeds, it proves that:
      • CREATE EXTENSION IF NOT EXISTS ltree — works.
      • All 3 enums (reading_status_enum, activity_type_enum,
        contributor_role_enum) — created successfully.
      • All 13 tables with their columns, types, and defaults — valid DDL.
      • All 21 indexes (B-tree, GIN, GiST, partial, covering) — created.
      • All CHECK constraints, UNIQUE constraints, FKs — valid.
      • The Computed() TSVECTOR column — generates correctly.

    If it FAILS, the error message will tell you exactly which DDL
    statement broke — fix it in models.py and re-run.
    """
    # create_all() emits CREATE TABLE, CREATE INDEX, CREATE EXTENSION, etc.
    # The event listener on Base.metadata fires CREATE EXTENSION ltree first.
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def db_session(test_engine, tables):
    """
    Yield a database session per test, rolled back after each test.

    How rollback isolation works:
    ─────────────────────────────
    1. Open a connection and begin a transaction.
    2. Bind the session to this connection.
    3. The test runs — all INSERTs, UPDATEs, DELETEs happen inside
       this transaction.
    4. After the test, ROLLBACK — all changes are undone.

    This means:
      • Tests don't pollute each other.
      • No manual cleanup needed.
      • Tests can run in any order.
      • Each test starts with an empty (but fully schema'd) database.

    Why not TRUNCATE between tests?
    ───────────────────────────────
    TRUNCATE is DDL (not DML) in PostgreSQL — it requires ACCESS EXCLUSIVE
    lock and cannot be rolled back in some configurations. Transaction
    rollback is faster, safer, and doesn't interfere with concurrent tests.
    """
    connection = test_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTER TEST FIXTURES & HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app


@pytest.fixture(scope="function")
def client(test_engine, tables):
    """
    FastAPI TestClient wired to a rolled-back DB session.

    Same isolation pattern as db_session above: each test gets its own
    transaction that is rolled back after the test completes. The FastAPI
    dependency override ensures all route handlers use this session instead
    of the production SessionLocal.
    """
    connection = test_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()

    def _override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    session.close()
    transaction.rollback()
    connection.close()


def make_user(client, **overrides):
    """Register a user via the API and return the response JSON."""
    payload = {
        "username": "testuser",
        "email": "test@example.com",
        "password": "SecurePass1!",
        "location": "California",
    }
    payload.update(overrides)
    resp = client.post("/api/v1/users/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def auth_header(client, email="test@example.com", password="SecurePass1!"):
    """Login via the API and return an Authorization header dict."""
    resp = client.post(
        "/api/v1/users/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
