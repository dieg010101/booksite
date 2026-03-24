"""
Standardized pagination utilities.

Two pagination strategies, both available as FastAPI Depends:

1. CursorPagination — for feeds and time-ordered lists (seek method)
   - O(1) regardless of page depth
   - No page skipping (intentional — prevents deep crawling)
   - Use when data is ordered by created_at or similar timestamp

2. OffsetPagination — for static collections (books, contributors, search results)
   - Supports random page access
   - O(N) at deep offsets (acceptable for small collections with UI limits)
   - Use when users need page numbers or want to jump to a specific page

Both return standardized response shapes.
"""

from datetime import datetime
from typing import Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Pagination params (use as dependencies)
# ---------------------------------------------------------------------------
class CursorParams:
    """Cursor-based pagination parameters."""

    def __init__(
        self,
        cursor: datetime | None = Query(
            default=None,
            description="Cursor: created_at of the last item from previous page",
        ),
        limit: int = Query(20, ge=1, le=100, description="Items per page"),
    ):
        self.cursor = cursor
        self.limit = limit


class OffsetParams:
    """Offset-based pagination parameters."""

    def __init__(
        self,
        offset: int = Query(0, ge=0, description="Number of items to skip"),
        limit: int = Query(20, ge=1, le=100, description="Items per page"),
    ):
        self.offset = offset
        self.limit = limit


# ---------------------------------------------------------------------------
# Response wrappers
# ---------------------------------------------------------------------------
class CursorPage(BaseModel, Generic[T]):
    """Cursor-paginated response."""

    items: list[Any]  # Generic[T] doesn't work perfectly with Pydantic v2 + FastAPI
    has_more: bool
    next_cursor: str | None = None  # ISO datetime string of last item's created_at


class OffsetPage(BaseModel, Generic[T]):
    """Offset-paginated response."""

    items: list[Any]
    total: int
    offset: int
    limit: int
