# Social Book Catalog — Backend Setup

## Prerequisites

- Docker & Docker Compose (for PostgreSQL)
- Python 3.10+
- pip

## Project Structure

```
booksite/backend/
├── docker-compose.yaml      # PostgreSQL 15 container
├── requirements.txt
├── app/
│   ├── __init__.py          # Package init, re-exports Base/engine/session
│   ├── database.py          # Engine, session factory, get_db()
│   ├── main.py              # FastAPI entry point (health checks)
│   └── models.py            # v4 ORM models (13 tables, 21 indexes)
└── tests/
    ├── __init__.py
    ├── conftest.py           # Pytest fixtures (DB setup/teardown)
    └── test_schema.py        # Schema validation tests (30+ tests)
```

## Quick Start

### 1. Start PostgreSQL

```bash
docker compose up db -d
```

Wait a few seconds for PostgreSQL to initialize, then verify:

```bash
docker compose exec db psql -U postgres -d book_platform -c "SELECT 1"
```

### 2. Install Python dependencies

```bash
cd booksite/backend
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Run the schema tests

```bash
pytest tests/ -v
```

This runs `Base.metadata.create_all()` which builds your ENTIRE schema
from scratch — all 13 tables, 21 indexes, 3 enums, the ltree extension,
partial indexes, GiST indexes, GIN indexes, covering indexes, CHECK
constraints, and FK constraints. If every test passes, your schema is
valid and deployable.

### 4. (Optional) Start the API

```bash
uvicorn app.main:app --reload
```

Then visit:

- http://localhost:8000/health — app health
- http://localhost:8000/health/db — database connectivity
- http://localhost:8000/docs — auto-generated API docs (empty for now)

## What's Next

After tests pass, the next steps are:

1. **Alembic migrations** — Version-controlled schema changes for deployment.
   `alembic init`, point it at your models, `alembic revision --autogenerate`.

2. **API routes** — FastAPI routers under `app/routers/` for users, books,
   entries, feed, search, etc.

3. **Background workers** — Celery/ARQ tasks for the write-behind counter
   flushes (Redis → PostgreSQL) and the fan-out timeline generation.

## Environment Variables

| Variable            | Default                                                            | Description                          |
| ------------------- | ------------------------------------------------------------------ | ------------------------------------ |
| `DATABASE_URL`      | `postgresql://postgres:localpassword@localhost:5432/book_platform` | Main DB connection                   |
| `TEST_DATABASE_URL` | Same as DATABASE_URL                                               | Test DB connection (override for CI) |
