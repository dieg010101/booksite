"""Pydantic schemas for contributors and book-contributor links."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ContributorRoleValue(str, Enum):
    AUTHOR = "author"
    ILLUSTRATOR = "illustrator"
    TRANSLATOR = "translator"
    EDITOR = "editor"
    FOREWORD_BY = "foreword_by"
    NARRATOR = "narrator"


class ContributorCreate(BaseModel):
    """POST /contributors — add a contributor to the system."""

    name: str = Field(min_length=1, max_length=200)
    bio: str | None = None


class ContributorUpdate(BaseModel):
    """PATCH /contributors/{id} — update contributor info."""

    name: str | None = Field(default=None, max_length=200)
    bio: str | None = None


class ContributorRead(BaseModel):
    """Contributor representation."""

    model_config = ConfigDict(from_attributes=True)

    contributor_id: UUID
    name: str
    bio: str | None


class BookContributorAdd(BaseModel):
    """POST /books/{book_id}/contributors — link a contributor to a book."""

    contributor_id: UUID
    role: ContributorRoleValue


class BookContributorRead(BaseModel):
    """A contributor's role on a specific book."""

    model_config = ConfigDict(from_attributes=True)

    book_id: UUID
    contributor_id: UUID
    role: ContributorRoleValue


class BookContributorDetail(BaseModel):
    """Contributor with role — for listing a book's contributors."""

    contributor_id: UUID
    name: str
    bio: str | None
    role: ContributorRoleValue
