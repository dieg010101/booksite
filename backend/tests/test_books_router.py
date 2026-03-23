"""Tests for the books router.

Run: pytest tests/test_books_router.py -v
"""

import pytest
from uuid import uuid4

from tests.conftest import auth_header, client, make_user  # noqa: F401


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_book(client, headers, **overrides):
    """Create a book via the API and return the response JSON."""
    payload = {
        "external_api_id": f"ext_{uuid4().hex[:12]}",
        "title": "Test Book",
        "isbn_13": None,
    }
    payload.update(overrides)
    resp = client.post("/api/v1/books", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def make_entry(client, book_id, headers, **overrides):
    """Create an entry via the API and return the response JSON."""
    payload = {"rating": 8, "review_text": "Great read!", "is_spoiler": False}
    payload.update(overrides)
    resp = client.post(
        f"/api/v1/books/{book_id}/entries", json=payload, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ═══════════════════════════════════════════════════════════════════════════
#  BOOK CATALOG
# ═══════════════════════════════════════════════════════════════════════════
class TestBookCatalog:
    def test_create_book(self, client):
        make_user(client)
        headers = auth_header(client)
        data = make_book(client, headers, title="Dune")
        assert data["title"] == "Dune"
        assert "book_id" in data
        assert data["is_active"] is True
        assert data["log_count"] == 0

    def test_create_book_requires_auth(self, client):
        resp = client.post(
            "/api/v1/books",
            json={
                "external_api_id": "ext_123",
                "title": "Unauthorized Book",
            },
        )
        assert resp.status_code == 401

    def test_create_book_duplicate_external_id(self, client):
        make_user(client)
        headers = auth_header(client)
        make_book(client, headers, external_api_id="ext_dupe")
        resp = client.post(
            "/api/v1/books",
            json={
                "external_api_id": "ext_dupe",
                "title": "Another Book",
            },
            headers=headers,
        )
        assert resp.status_code == 409

    def test_create_book_duplicate_isbn(self, client):
        make_user(client)
        headers = auth_header(client)
        make_book(client, headers, isbn_13="9780141036144")
        resp = client.post(
            "/api/v1/books",
            json={
                "external_api_id": f"ext_{uuid4().hex[:12]}",
                "title": "Another",
                "isbn_13": "9780141036144",
            },
            headers=headers,
        )
        assert resp.status_code == 409

    def test_get_book(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        resp = client.get(f"/api/v1/books/{book['book_id']}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Test Book"

    def test_get_book_not_found(self, client):
        resp = client.get(f"/api/v1/books/{uuid4()}")
        assert resp.status_code == 404

    def test_list_books(self, client):
        make_user(client)
        headers = auth_header(client)
        make_book(client, headers, title="Book A", external_api_id="ext_a")
        make_book(client, headers, title="Book B", external_api_id="ext_b")
        resp = client.get("/api/v1/books")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["books"]) == 2

    def test_list_books_pagination(self, client):
        make_user(client)
        headers = auth_header(client)
        for i in range(5):
            make_book(client, headers, title=f"Book {i}", external_api_id=f"ext_{i}")
        resp = client.get("/api/v1/books?offset=0&limit=2")
        body = resp.json()
        assert body["total"] == 5
        assert len(body["books"]) == 2

    def test_search_books(self, client):
        make_user(client)
        headers = auth_header(client)
        make_book(
            client, headers, title="The Great Gatsby", external_api_id="ext_gatsby"
        )
        make_book(client, headers, title="Moby Dick", external_api_id="ext_moby")
        resp = client.get("/api/v1/books/search?q=gatsby")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert any("Gatsby" in b["title"] for b in body["books"])

    def test_search_no_results(self, client):
        resp = client.get("/api/v1/books/search?q=xyznonexistent")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_explore_endpoints_return_200(self, client):
        """Smoke test: all explore endpoints return 200 even with no data."""
        for endpoint in [
            "/api/v1/books/trending",
            "/api/v1/books/popular",
            "/api/v1/books/top-rated",
        ]:
            resp = client.get(endpoint)
            assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
#  BOOK ENTRIES (logs / reviews)
# ═══════════════════════════════════════════════════════════════════════════
class TestBookEntries:
    def test_create_entry(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        assert entry["rating"] == 8
        assert entry["review_text"] == "Great read!"
        assert entry["book_id"] == book["book_id"]
        assert "entry_id" in entry

    def test_create_entry_requires_auth(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        resp = client.post(
            f"/api/v1/books/{book['book_id']}/entries", json={"rating": 5}
        )
        assert resp.status_code == 401

    def test_create_entry_nonexistent_book(self, client):
        make_user(client)
        headers = auth_header(client)
        resp = client.post(
            f"/api/v1/books/{uuid4()}/entries", json={"rating": 5}, headers=headers
        )
        assert resp.status_code == 404

    def test_create_entry_no_rating(self, client):
        """Entries without a rating are allowed (just a log, no review)."""
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(
            client, book["book_id"], headers, rating=None, review_text=None
        )
        assert entry["rating"] is None

    def test_create_multiple_entries_same_book(self, client):
        """Re-reads: multiple entries per user per book allowed."""
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        e1 = make_entry(client, book["book_id"], headers, rating=7)
        e2 = make_entry(client, book["book_id"], headers, rating=9)
        assert e1["entry_id"] != e2["entry_id"]

    def test_list_book_entries(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        make_entry(client, book["book_id"], headers)
        make_entry(client, book["book_id"], headers, rating=6)
        resp = client.get(f"/api/v1/books/{book['book_id']}/entries")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_get_entry(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        resp = client.get(f"/api/v1/entries/{entry['entry_id']}")
        assert resp.status_code == 200
        assert resp.json()["entry_id"] == entry["entry_id"]

    def test_update_entry(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers, rating=5)
        resp = client.patch(
            f"/api/v1/entries/{entry['entry_id']}",
            json={"rating": 9, "review_text": "Even better on re-read!"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["rating"] == 9
        assert resp.json()["review_text"] == "Even better on re-read!"

    def test_update_entry_partial(self, client):
        """Partial update: only rating changes, review_text stays."""
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(
            client, book["book_id"], headers, rating=5, review_text="Original"
        )
        resp = client.patch(
            f"/api/v1/entries/{entry['entry_id']}",
            json={"rating": 10},
            headers=headers,
        )
        assert resp.json()["rating"] == 10
        assert resp.json()["review_text"] == "Original"

    def test_update_entry_not_owner(self, client):
        """Users can't edit other people's entries."""
        make_user(client)
        make_user(client, username="alice", email="alice@example.com")
        headers_owner = auth_header(client)
        headers_alice = auth_header(client, email="alice@example.com")
        book = make_book(client, headers_owner)
        entry = make_entry(client, book["book_id"], headers_owner)
        resp = client.patch(
            f"/api/v1/entries/{entry['entry_id']}",
            json={"rating": 1},
            headers=headers_alice,
        )
        assert resp.status_code == 403

    def test_soft_delete_entry(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        resp = client.delete(f"/api/v1/entries/{entry['entry_id']}", headers=headers)
        assert resp.status_code == 204
        # Should no longer be visible
        resp = client.get(f"/api/v1/entries/{entry['entry_id']}")
        assert resp.status_code == 404

    def test_delete_entry_not_owner(self, client):
        make_user(client)
        make_user(client, username="alice", email="alice@example.com")
        headers_owner = auth_header(client)
        headers_alice = auth_header(client, email="alice@example.com")
        book = make_book(client, headers_owner)
        entry = make_entry(client, book["book_id"], headers_owner)
        resp = client.delete(
            f"/api/v1/entries/{entry['entry_id']}", headers=headers_alice
        )
        assert resp.status_code == 403

    def test_list_user_entries(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        make_entry(client, book["book_id"], headers)
        resp = client.get("/api/v1/users/testuser/entries")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_list_user_entries_not_found(self, client):
        resp = client.get("/api/v1/users/nobody/entries")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
#  READING STATUS
# ═══════════════════════════════════════════════════════════════════════════
class TestReadingStatus:
    def test_set_reading_status(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        resp = client.put(
            f"/api/v1/books/{book['book_id']}/status",
            json={"status": "reading"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "reading"

    def test_update_reading_status(self, client):
        """Upsert: setting status again updates it."""
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        client.put(
            f"/api/v1/books/{book['book_id']}/status",
            json={"status": "reading"},
            headers=headers,
        )
        resp = client.put(
            f"/api/v1/books/{book['book_id']}/status",
            json={"status": "read"},
            headers=headers,
        )
        assert resp.json()["status"] == "read"

    def test_get_reading_status(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        client.put(
            f"/api/v1/books/{book['book_id']}/status",
            json={"status": "want_to_read"},
            headers=headers,
        )
        resp = client.get(f"/api/v1/books/{book['book_id']}/status", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "want_to_read"

    def test_get_reading_status_not_set(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        resp = client.get(f"/api/v1/books/{book['book_id']}/status", headers=headers)
        assert resp.status_code == 404

    def test_delete_reading_status(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        client.put(
            f"/api/v1/books/{book['book_id']}/status",
            json={"status": "reading"},
            headers=headers,
        )
        resp = client.delete(f"/api/v1/books/{book['book_id']}/status", headers=headers)
        assert resp.status_code == 204
        # Should be gone now
        resp = client.get(f"/api/v1/books/{book['book_id']}/status", headers=headers)
        assert resp.status_code == 404

    def test_delete_reading_status_not_set(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        resp = client.delete(f"/api/v1/books/{book['book_id']}/status", headers=headers)
        assert resp.status_code == 404

    def test_reading_status_requires_auth(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        resp = client.put(
            f"/api/v1/books/{book['book_id']}/status",
            json={"status": "reading"},
        )
        assert resp.status_code == 401

    def test_invalid_status_rejected(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        resp = client.put(
            f"/api/v1/books/{book['book_id']}/status",
            json={"status": "burned_it"},
            headers=headers,
        )
        assert resp.status_code == 422

    def test_all_valid_statuses(self, client):
        """All four enum values work."""
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        for status_val in ["want_to_read", "reading", "read", "did_not_finish"]:
            resp = client.put(
                f"/api/v1/books/{book['book_id']}/status",
                json={"status": status_val},
                headers=headers,
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == status_val
