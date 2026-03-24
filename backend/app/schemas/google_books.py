"""Pydantic schemas for Google Books search and import."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field


class GoogleBookResult(BaseModel):
    """A single result from Google Books API search."""

    external_api_id: str
    title: str
    isbn_13: str | None
    published_date: date | None
    authors: list[str]
    description: str | None
    page_count: int | None
    categories: list[str]
    thumbnail: str | None
    language: str | None
    publisher: str | None


class GoogleBookSearchResponse(BaseModel):
    """Search results from Google Books."""

    results: list[GoogleBookResult]
    total: int


class GoogleBookImport(BaseModel):
    """POST /books/import — import a book from Google Books by volume ID."""

    volume_id: str = Field(description="Google Books volume ID (external_api_id)")
