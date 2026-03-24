"""Pydantic schemas for User endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------
class UserCreate(BaseModel):
    """POST /users/register body."""

    username: str = Field(min_length=3, max_length=30, pattern=r"^[a-zA-Z0-9_]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    location: str | None = Field(default=None, max_length=100)


class UserUpdate(BaseModel):
    """PATCH /users/me body. All fields optional."""

    location: str | None = Field(default=None, max_length=100)
    avatar_url: str | None = Field(default=None, max_length=2048)


class LoginRequest(BaseModel):
    """POST /users/login body."""

    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    """POST /users/refresh body."""

    refresh_token: str


# ---------------------------------------------------------------------------
# Response bodies
# ---------------------------------------------------------------------------
class UserRead(BaseModel):
    """Public user representation (safe to expose)."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    username: str
    avatar_url: str | None
    location: str | None
    follower_count: int
    following_count: int
    created_at: datetime


class UserPrivate(UserRead):
    """Full profile returned only to the user themselves."""

    email: str
    updated_at: datetime


class TokenResponse(BaseModel):
    """Login/refresh response with both tokens."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class MessageResponse(BaseModel):
    """Generic envelope for simple messages."""

    detail: str
