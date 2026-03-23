"""Tests for the feed router — likes, reposts, timeline fan-out, feed reading.

Run: pytest tests/test_feed_router.py -v
"""

import pytest
from uuid import uuid4

from tests.conftest import auth_header, client, make_user  # noqa: F401


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_book(client, headers, **overrides):
    payload = {
        "external_api_id": f"ext_{uuid4().hex[:12]}",
        "title": "Test Book",
    }
    payload.update(overrides)
    resp = client.post("/api/v1/books", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def make_entry(client, book_id, headers, **overrides):
    payload = {"rating": 8, "review_text": "Great read!"}
    payload.update(overrides)
    resp = client.post(
        f"/api/v1/books/{book_id}/entries", json=payload, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def setup_follow(client):
    """Create two users, have alice follow testuser. Return both headers + a book."""
    make_user(client)
    make_user(client, username="alice", email="alice@example.com")
    headers_test = auth_header(client)
    headers_alice = auth_header(client, email="alice@example.com")
    # alice follows testuser
    client.post("/api/v1/users/testuser/follow", headers=headers_alice)
    book = make_book(client, headers_test)
    return headers_test, headers_alice, book


# ═══════════════════════════════════════════════════════════════════════════
#  LIKES
# ═══════════════════════════════════════════════════════════════════════════
class TestLikes:
    def test_like_entry(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        resp = client.post(f"/api/v1/entries/{entry['entry_id']}/like", headers=headers)
        assert resp.status_code == 201
        assert resp.json()["entry_id"] == entry["entry_id"]

    def test_like_requires_auth(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        resp = client.post(f"/api/v1/entries/{entry['entry_id']}/like")
        assert resp.status_code == 401

    def test_double_like_rejected(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        client.post(f"/api/v1/entries/{entry['entry_id']}/like", headers=headers)
        resp = client.post(f"/api/v1/entries/{entry['entry_id']}/like", headers=headers)
        assert resp.status_code == 409

    def test_like_nonexistent_entry(self, client):
        make_user(client)
        headers = auth_header(client)
        resp = client.post(f"/api/v1/entries/{uuid4()}/like", headers=headers)
        assert resp.status_code == 404

    def test_unlike_entry(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        client.post(f"/api/v1/entries/{entry['entry_id']}/like", headers=headers)
        resp = client.delete(
            f"/api/v1/entries/{entry['entry_id']}/like", headers=headers
        )
        assert resp.status_code == 204

    def test_unlike_not_liked(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        resp = client.delete(
            f"/api/v1/entries/{entry['entry_id']}/like", headers=headers
        )
        assert resp.status_code == 404

    def test_list_entry_likes(self, client):
        make_user(client)
        make_user(client, username="alice", email="alice@example.com")
        headers_test = auth_header(client)
        headers_alice = auth_header(client, email="alice@example.com")
        book = make_book(client, headers_test)
        entry = make_entry(client, book["book_id"], headers_test)
        client.post(f"/api/v1/entries/{entry['entry_id']}/like", headers=headers_test)
        client.post(f"/api/v1/entries/{entry['entry_id']}/like", headers=headers_alice)
        resp = client.get(f"/api/v1/entries/{entry['entry_id']}/likes")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


# ═══════════════════════════════════════════════════════════════════════════
#  REPOSTS
# ═══════════════════════════════════════════════════════════════════════════
class TestReposts:
    def test_repost_entry(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        resp = client.post(
            f"/api/v1/entries/{entry['entry_id']}/repost", headers=headers
        )
        assert resp.status_code == 201
        assert resp.json()["entry_id"] == entry["entry_id"]

    def test_repost_requires_auth(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        resp = client.post(f"/api/v1/entries/{entry['entry_id']}/repost")
        assert resp.status_code == 401

    def test_double_repost_rejected(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        client.post(f"/api/v1/entries/{entry['entry_id']}/repost", headers=headers)
        resp = client.post(
            f"/api/v1/entries/{entry['entry_id']}/repost", headers=headers
        )
        assert resp.status_code == 409

    def test_repost_nonexistent_entry(self, client):
        make_user(client)
        headers = auth_header(client)
        resp = client.post(f"/api/v1/entries/{uuid4()}/repost", headers=headers)
        assert resp.status_code == 404

    def test_unrepost_entry(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        client.post(f"/api/v1/entries/{entry['entry_id']}/repost", headers=headers)
        resp = client.delete(
            f"/api/v1/entries/{entry['entry_id']}/repost", headers=headers
        )
        assert resp.status_code == 204

    def test_unrepost_not_reposted(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        resp = client.delete(
            f"/api/v1/entries/{entry['entry_id']}/repost", headers=headers
        )
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
#  FAN-OUT ON WRITE + FEED READING
# ═══════════════════════════════════════════════════════════════════════════
class TestFanOutAndFeed:
    def test_entry_appears_in_own_feed(self, client):
        """Creating an entry should appear in the author's own feed."""
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        resp = client.get("/api/v1/feed", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["entry_id"] == entry["entry_id"]
        assert body["items"][0]["activity_type"] == "review"

    def test_entry_fans_out_to_follower(self, client):
        """When testuser creates an entry, alice (who follows testuser) sees it."""
        headers_test, headers_alice, book = setup_follow(client)
        entry = make_entry(client, book["book_id"], headers_test)
        # Check alice's feed
        resp = client.get("/api/v1/feed", headers=headers_alice)
        assert resp.status_code == 200
        items = resp.json()["items"]
        entry_ids = [item["entry_id"] for item in items]
        assert entry["entry_id"] in entry_ids

    def test_repost_fans_out_to_follower(self, client):
        """When testuser reposts, alice sees the repost in her feed."""
        headers_test, headers_alice, book = setup_follow(client)
        entry = make_entry(client, book["book_id"], headers_test)
        client.post(f"/api/v1/entries/{entry['entry_id']}/repost", headers=headers_test)
        resp = client.get("/api/v1/feed", headers=headers_alice)
        items = resp.json()["items"]
        repost_items = [i for i in items if i["activity_type"] == "repost"]
        assert len(repost_items) >= 1

    def test_feed_empty_for_new_user(self, client):
        make_user(client)
        headers = auth_header(client)
        resp = client.get("/api/v1/feed", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["items"] == []
        assert resp.json()["has_more"] is False

    def test_feed_requires_auth(self, client):
        resp = client.get("/api/v1/feed")
        assert resp.status_code == 401

    def test_feed_cursor_pagination(self, client):
        """Cursor-based pagination: use created_at of last item to get next page."""
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        # Create 5 entries
        entries = []
        for i in range(5):
            entries.append(make_entry(client, book["book_id"], headers, rating=i + 1))

        # First page: limit=2
        resp = client.get("/api/v1/feed?limit=2", headers=headers)
        body = resp.json()
        assert len(body["items"]) == 2
        assert body["has_more"] is True

        # Second page: use cursor from last item
        cursor = body["items"][-1]["created_at"]
        resp = client.get(f"/api/v1/feed?limit=2&cursor={cursor}", headers=headers)
        body2 = resp.json()
        assert len(body2["items"]) == 2
        assert body2["has_more"] is True

        # Third page
        cursor2 = body2["items"][-1]["created_at"]
        resp = client.get(f"/api/v1/feed?limit=2&cursor={cursor2}", headers=headers)
        body3 = resp.json()
        assert len(body3["items"]) == 1
        assert body3["has_more"] is False

    def test_feed_no_duplicates_from_review_and_repost(self, client):
        """Same entry as review + repost = 2 distinct timeline items (different activity_type)."""
        headers_test, headers_alice, book = setup_follow(client)
        entry = make_entry(client, book["book_id"], headers_test)
        client.post(f"/api/v1/entries/{entry['entry_id']}/repost", headers=headers_test)
        resp = client.get("/api/v1/feed", headers=headers_alice)
        items = resp.json()["items"]
        # Should have both a review and a repost item for the same entry
        types = {
            i["activity_type"] for i in items if i["entry_id"] == entry["entry_id"]
        }
        assert "review" in types
        assert "repost" in types

    def test_non_follower_does_not_see_entry(self, client):
        """A user who doesn't follow the author shouldn't see their entries."""
        make_user(client)
        make_user(client, username="alice", email="alice@example.com")
        headers_test = auth_header(client)
        headers_alice = auth_header(client, email="alice@example.com")
        # alice does NOT follow testuser
        book = make_book(client, headers_test)
        make_entry(client, book["book_id"], headers_test)
        resp = client.get("/api/v1/feed", headers=headers_alice)
        assert resp.json()["items"] == []
