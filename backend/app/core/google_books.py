"""Google Books API client.

Fetches book metadata and maps it to our catalog schema.
Works with or without an API key (keyless has lower rate limits).

Usage:
    from app.core.google_books import search_google_books, fetch_google_book

    results = await search_google_books("Dune Frank Herbert")
    book_data = await fetch_google_book("google_volume_id_here")
"""

from datetime import date
from typing import Any

import httpx

from app.core.config import GOOGLE_BOOKS_API_KEY, GOOGLE_BOOKS_BASE_URL


def _parse_published_date(date_str: str | None) -> date | None:
    """Parse Google's inconsistent date formats: '2024', '2024-03', '2024-03-15'."""
    if not date_str:
        return None
    try:
        if len(date_str) == 4:  # "2024"
            return date(int(date_str), 1, 1)
        elif len(date_str) == 7:  # "2024-03"
            parts = date_str.split("-")
            return date(int(parts[0]), int(parts[1]), 1)
        else:  # "2024-03-15"
            return date.fromisoformat(date_str)
    except (ValueError, IndexError):
        return None


def _extract_isbn_13(industry_identifiers: list[dict] | None) -> str | None:
    """Extract ISBN-13 from Google's industryIdentifiers array."""
    if not industry_identifiers:
        return None
    for ident in industry_identifiers:
        if ident.get("type") == "ISBN_13":
            return ident.get("identifier")
    return None


def _parse_volume(volume: dict[str, Any]) -> dict[str, Any]:
    """Parse a Google Books API volume into our Book-compatible dict."""
    info = volume.get("volumeInfo", {})
    return {
        "external_api_id": volume["id"],
        "title": info.get("title", "Unknown Title"),
        "isbn_13": _extract_isbn_13(info.get("industryIdentifiers")),
        "published_date": _parse_published_date(info.get("publishedDate")),
        "edition": None,  # Google doesn't have a clean edition field
        "publishing_location": None,
        # Extra metadata (not in our Book model, but useful for the frontend)
        "authors": info.get("authors", []),
        "description": info.get("description"),
        "page_count": info.get("pageCount"),
        "categories": info.get("categories", []),
        "thumbnail": (
            info.get("imageLinks", {}).get("thumbnail")
            if info.get("imageLinks")
            else None
        ),
        "language": info.get("language"),
        "publisher": info.get("publisher"),
    }


def _build_params(extra: dict) -> dict:
    """Build query params, adding API key if configured."""
    params = {**extra}
    if GOOGLE_BOOKS_API_KEY:
        params["key"] = GOOGLE_BOOKS_API_KEY
    return params


async def search_google_books(
    query: str,
    max_results: int = 10,
    start_index: int = 0,
) -> list[dict[str, Any]]:
    """Search Google Books by query string.

    Returns a list of parsed volume dicts ready to display or import.
    """
    params = _build_params(
        {
            "q": query,
            "maxResults": min(max_results, 40),
            "startIndex": start_index,
            "printType": "books",
        }
    )

    async with httpx.AsyncClient() as client:
        resp = await client.get(GOOGLE_BOOKS_BASE_URL, params=params, timeout=10.0)
        resp.raise_for_status()

    data = resp.json()
    items = data.get("items", [])
    return [_parse_volume(item) for item in items]


async def fetch_google_book(volume_id: str) -> dict[str, Any] | None:
    """Fetch a single book by its Google Books volume ID.

    Returns a parsed volume dict or None if not found.
    """
    url = f"{GOOGLE_BOOKS_BASE_URL}/{volume_id}"
    params = _build_params({})

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params, timeout=10.0)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()

    return _parse_volume(resp.json())


async def search_google_books_by_isbn(isbn: str) -> dict[str, Any] | None:
    """Look up a book by ISBN (13 or 10).

    Returns a single parsed volume dict or None.
    """
    results = await search_google_books(f"isbn:{isbn}", max_results=1)
    return results[0] if results else None
