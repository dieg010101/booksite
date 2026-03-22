"""
app — Social Book Catalog backend package.
==========================================

Re-exports the key database components so the rest of the codebase
(API routes, background workers, tests) can import from a single place:

    from app import Base, engine, SessionLocal, get_db
    from app.models import User, BookEntry, Timeline, ...

This file intentionally does NOT import all models by name — that would
create a massive import list that breaks every time a model is added.
Instead, import models explicitly from `app.models` where needed.

The one exception is `Base`: it's re-exported here because Alembic,
test fixtures, and `create_all()` all need it without knowing about models.
"""

from app.database import engine, SessionLocal, get_db  # noqa: F401
from app.models import Base  # noqa: F401
