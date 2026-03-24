"""Tests for the Google Books router.

Mocks the Google Books API client so tests don't make real HTTP calls.

Run: pytest tests/test_google_books_router.py -v
"""

import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from tests.conftest import auth_header, client, make_user  # noqa: F401


# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------
MOCK_VOLUME = {
    "external_api_id": "google_vol_abc123",
    "title": "Dune",
    "isbn_13": "9780441013593",
    "published_date": "1965-08-01",
    "authors": ["Frank Herbert"],
    "description": "A science fiction masterpiece.",
    "page_count": 412,
    "categories": ["Fiction"],
    "thumbnail": "https://books.google.com/thumb/dune.jpg",
    "language": "en",
    "publisher": "Ace Books",
}

MOCK_VOLUME_2 = {
    **MOCK_VOLUME,
    "external_api_id": "google_vol_def456",
    "title": "Dune Messiah",
    "isbn_13": "9780441172696",
}

MOCK_VOLUME_NO_AUTHORS = {
    **MOCK_VOLUME,
    "external_api_id": "google_vol_noauth",
    "title": "Anonymous Book",
    "authors": [],
    "isbn_13": None,
}


# ═══════════════════════════════════════════════════════════════════════════
#  SEARCH
# ═══════════════════════════════════════════════════════════════════════════
class TestGoogleBooksSearch:
    @patch("app.routers.google_books.search_google_books", new_callable=AsyncMock)
    def test_search_returns_results(self, mock_search, client):
        mock_search.return_value = [MOCK_VOLUME, MOCK_VOLUME_2]
        resp = client.get("/api/v1/google-books/search?q=dune")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert body["results"][0]["title"] == "Dune"
        assert body["results"][0]["authors"] == ["Frank Herbert"]
        assert body["results"][0]["thumbnail"] is not None

    @patch("app.routers.google_books.search_google_books", new_callable=AsyncMock)
    def test_search_empty_results(self, mock_search, client):
        mock_search.return_value = []
        resp = client.get("/api/v1/google-books/search?q=xyznonexistent")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    @patch("app.routers.google_books.search_google_books", new_callable=AsyncMock)
    def test_search_api_error(self, mock_search, client):
        mock_search.side_effect = Exception("API timeout")
        resp = client.get("/api/v1/google-books/search?q=dune")
        assert resp.status_code == 502

    def test_search_no_query(self, client):
        resp = client.get("/api/v1/google-books/search")
        assert resp.status_code == 422

    @patch("app.routers.google_books.search_google_books", new_callable=AsyncMock)
    def test_search_no_auth_required(self, mock_search, client):
        """Search is public — no JWT needed."""
        mock_search.return_value = [MOCK_VOLUME]
        resp = client.get("/api/v1/google-books/search?q=dune")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
#  ISBN LOOKUP
# ═══════════════════════════════════════════════════════════════════════════
class TestGoogleBooksISBN:
    @patch(
        "app.routers.google_books.search_google_books_by_isbn", new_callable=AsyncMock
    )
    def test_isbn_lookup(self, mock_isbn, client):
        mock_isbn.return_value = MOCK_VOLUME
        resp = client.get("/api/v1/google-books/isbn/9780441013593")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Dune"

    @patch(
        "app.routers.google_books.search_google_books_by_isbn", new_callable=AsyncMock
    )
    def test_isbn_not_found(self, mock_isbn, client):
        mock_isbn.return_value = None
        resp = client.get("/api/v1/google-books/isbn/0000000000000")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
#  VOLUME LOOKUP
# ═══════════════════════════════════════════════════════════════════════════
class TestGoogleBooksVolume:
    @patch("app.routers.google_books.fetch_google_book", new_callable=AsyncMock)
    def test_volume_lookup(self, mock_fetch, client):
        mock_fetch.return_value = MOCK_VOLUME
        resp = client.get("/api/v1/google-books/volume/google_vol_abc123")
        assert resp.status_code == 200
        assert resp.json()["external_api_id"] == "google_vol_abc123"

    @patch("app.routers.google_books.fetch_google_book", new_callable=AsyncMock)
    def test_volume_not_found(self, mock_fetch, client):
        mock_fetch.return_value = None
        resp = client.get("/api/v1/google-books/volume/nonexistent")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
#  IMPORT
# ═══════════════════════════════════════════════════════════════════════════
class TestGoogleBooksImport:
    @patch("app.routers.google_books.fetch_google_book", new_callable=AsyncMock)
    def test_import_book(self, mock_fetch, client):
        mock_fetch.return_value = MOCK_VOLUME
        make_user(client)
        headers = auth_header(client)
        resp = client.post(
            "/api/v1/google-books/import",
            json={"volume_id": "google_vol_abc123"},
            headers=headers,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["title"] == "Dune"
        assert body["external_api_id"] == "google_vol_abc123"
        assert body["isbn_13"] == "9780441013593"

    @patch("app.routers.google_books.fetch_google_book", new_callable=AsyncMock)
    def test_import_creates_contributors(self, mock_fetch, client):
        """Importing a book should auto-create Author contributors."""
        mock_fetch.return_value = MOCK_VOLUME
        make_user(client)
        headers = auth_header(client)
        client.post(
            "/api/v1/google-books/import",
            json={"volume_id": "google_vol_abc123"},
            headers=headers,
        )
        # Check the book has contributors
        # First, get the book
        books_resp = client.get("/api/v1/books?limit=1")
        book_id = books_resp.json()["books"][0]["book_id"]
        contribs_resp = client.get(f"/api/v1/books/{book_id}/contributors")
        assert contribs_resp.status_code == 200
        contribs = contribs_resp.json()
        assert len(contribs) == 1
        assert contribs[0]["name"] == "Frank Herbert"
        assert contribs[0]["role"] == "author"

    @patch("app.routers.google_books.fetch_google_book", new_callable=AsyncMock)
    def test_import_duplicate_rejected(self, mock_fetch, client):
        mock_fetch.return_value = MOCK_VOLUME
        make_user(client)
        headers = auth_header(client)
        client.post(
            "/api/v1/google-books/import",
            json={"volume_id": "google_vol_abc123"},
            headers=headers,
        )
        resp = client.post(
            "/api/v1/google-books/import",
            json={"volume_id": "google_vol_abc123"},
            headers=headers,
        )
        assert resp.status_code == 409

    @patch("app.routers.google_books.fetch_google_book", new_callable=AsyncMock)
    def test_import_requires_auth(self, mock_fetch, client):
        mock_fetch.return_value = MOCK_VOLUME
        resp = client.post(
            "/api/v1/google-books/import",
            json={"volume_id": "google_vol_abc123"},
        )
        assert resp.status_code == 401

    @patch("app.routers.google_books.fetch_google_book", new_callable=AsyncMock)
    def test_import_volume_not_found(self, mock_fetch, client):
        mock_fetch.return_value = None
        make_user(client)
        headers = auth_header(client)
        resp = client.post(
            "/api/v1/google-books/import",
            json={"volume_id": "nonexistent"},
            headers=headers,
        )
        assert resp.status_code == 404

    @patch("app.routers.google_books.fetch_google_book", new_callable=AsyncMock)
    def test_import_book_without_authors(self, mock_fetch, client):
        """Books with no authors should import fine, just no contributors."""
        mock_fetch.return_value = MOCK_VOLUME_NO_AUTHORS
        make_user(client)
        headers = auth_header(client)
        resp = client.post(
            "/api/v1/google-books/import",
            json={"volume_id": "google_vol_noauth"},
            headers=headers,
        )
        assert resp.status_code == 201
        assert resp.json()["title"] == "Anonymous Book"

    @patch("app.routers.google_books.fetch_google_book", new_callable=AsyncMock)
    def test_import_api_error(self, mock_fetch, client):
        mock_fetch.side_effect = Exception("Connection refused")
        make_user(client)
        headers = auth_header(client)
        resp = client.post(
            "/api/v1/google-books/import",
            json={"volume_id": "google_vol_abc123"},
            headers=headers,
        )
        assert resp.status_code == 502
