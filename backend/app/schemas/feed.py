"""Pydantic schemas for feed, likes, and reposts."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Activity type enum (mirrors DB enum)
# ---------------------------------------------------------------------------
class ActivityType(str, Enum):
    REVIEW = "review"
    REPOST = "repost"
    STATUS_UPDATE = "status_update"


# ---------------------------------------------------------------------------
# Timeline / feed
# ---------------------------------------------------------------------------
class TimelineRead(BaseModel):
    """A single item in the user's feed."""

    model_config = ConfigDict(from_attributes=True)

    timeline_id: UUID
    user_id: UUID
    entry_id: UUID
    activity_type: ActivityType
    created_at: datetime


class FeedResponse(BaseModel):
    """Paginated feed."""

    items: list[TimelineRead]
    has_more: bool


# ---------------------------------------------------------------------------
# Likes
# ---------------------------------------------------------------------------
class LikeRead(BaseModel):
    """Like response."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    entry_id: UUID
    created_at: datetime


# ---------------------------------------------------------------------------
# Reposts
# ---------------------------------------------------------------------------
class RepostRead(BaseModel):
    """Repost response."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    entry_id: UUID
    created_at: datetime


# ---------------------------------------------------------------------------
# Generic
# ---------------------------------------------------------------------------
class MessageResponse(BaseModel):
    detail: str
