"""Pydantic schemas for Book, BookEntry, and ReadingStatus endpoints."""

from datetime import date, datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Reading status enum (mirrors the DB enum for validation)
# ---------------------------------------------------------------------------
class ReadingStatusValue(str, Enum):
    WANT_TO_READ = "want_to_read"
    READING = "reading"
    READ = "read"
    DID_NOT_FINISH = "did_not_finish"


# ---------------------------------------------------------------------------
# Book schemas
# ---------------------------------------------------------------------------
class BookCreate(BaseModel):
    """POST /books — add a book to the catalog."""

    external_api_id: str = Field(max_length=64)
    isbn_13: str | None = Field(default=None, max_length=13)
    title: str = Field(max_length=500)
    published_date: date | None = None
    edition: str | None = Field(default=None, max_length=100)
    publishing_location: str | None = Field(default=None, max_length=200)


class BookRead(BaseModel):
    """Public book representation."""

    model_config = ConfigDict(from_attributes=True)

    book_id: UUID
    external_api_id: str
    isbn_13: str | None
    title: str
    published_date: date | None
    edition: str | None
    publishing_location: str | None
    is_active: bool
    log_count: int
    avg_rating: float | None
    currently_reading_count: int


class BookList(BaseModel):
    """Paginated list of books."""

    books: list[BookRead]
    total: int


# ---------------------------------------------------------------------------
# BookEntry schemas
# ---------------------------------------------------------------------------
class EntryCreate(BaseModel):
    """POST /books/{book_id}/entries — log/review a book."""

    rating: int | None = Field(default=None, ge=1, le=10)
    review_text: str | None = None
    is_spoiler: bool = False
    mood: str | None = Field(default=None, max_length=50)


class EntryUpdate(BaseModel):
    """PATCH /entries/{entry_id} — update a log/review."""

    rating: int | None = Field(default=None, ge=1, le=10)
    review_text: str | None = None
    is_spoiler: bool | None = None
    mood: str | None = Field(default=None, max_length=50)


class EntryRead(BaseModel):
    """Public entry representation."""

    model_config = ConfigDict(from_attributes=True)

    entry_id: UUID
    user_id: UUID
    book_id: UUID
    rating: int | None
    review_text: str | None
    is_spoiler: bool
    mood: str | None
    logged_date: datetime
    created_at: datetime
    updated_at: datetime
    like_count: int
    repost_count: int
    comment_count: int


# ---------------------------------------------------------------------------
# ReadingStatus schemas
# ---------------------------------------------------------------------------
class ReadingStatusSet(BaseModel):
    """PUT /books/{book_id}/status — set reading status."""

    status: ReadingStatusValue


class ReadingStatusRead(BaseModel):
    """Reading status response."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    book_id: UUID
    status: ReadingStatusValue
    created_at: datetime
    updated_at: datetime
