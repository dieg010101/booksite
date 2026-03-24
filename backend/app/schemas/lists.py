"""Pydantic schemas for user-curated book lists."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ListCreate(BaseModel):
    """POST /lists — create a new book list."""

    list_name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    is_public: bool = True


class ListUpdate(BaseModel):
    """PATCH /lists/{list_id} — update list metadata."""

    list_name: str | None = Field(default=None, max_length=150)
    description: str | None = None
    is_public: bool | None = None


class ListRead(BaseModel):
    """List representation."""

    model_config = ConfigDict(from_attributes=True)

    list_id: UUID
    user_id: UUID
    list_name: str
    description: str | None
    is_public: bool
    created_at: datetime
    updated_at: datetime


class ListItemAdd(BaseModel):
    """POST /lists/{list_id}/items — add a book to a list."""

    book_id: UUID
    position: int | None = None  # None = append to end


class ListItemRead(BaseModel):
    """An item in a list with position."""

    model_config = ConfigDict(from_attributes=True)

    list_id: UUID
    book_id: UUID
    position: int
    added_at: datetime


class ListItemReorder(BaseModel):
    """PUT /lists/{list_id}/items/reorder — set new positions."""

    book_ids: list[UUID]  # ordered list of book_ids in desired order
