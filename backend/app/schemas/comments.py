"""Pydantic schemas for threaded comments."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CommentCreate(BaseModel):
    """POST /entries/{entry_id}/comments — create a comment or reply."""

    comment_text: str = Field(min_length=1, max_length=10000)
    parent_comment_id: UUID | None = None  # None = top-level, set = reply


class CommentRead(BaseModel):
    """Comment representation with thread info."""

    model_config = ConfigDict(from_attributes=True)

    comment_id: UUID
    user_id: UUID | None  # None = deleted user → "[deleted]"
    entry_id: UUID
    path: str  # ltree path as string
    comment_text: str
    is_deleted: bool
    created_at: datetime
    updated_at: datetime


class CommentThread(BaseModel):
    """A flat list of comments in tree order (sorted by ltree path)."""

    comments: list[CommentRead]
    total: int
