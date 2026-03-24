"""Tests for the comments router — threaded comments with ltree.

Run: pytest tests/test_comments_router.py -v
"""

import pytest
from uuid import uuid4

from tests.conftest import auth_header, client, make_user  # noqa: F401


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_book(client, headers, **overrides):
    payload = {"external_api_id": f"ext_{uuid4().hex[:12]}", "title": "Test Book"}
    payload.update(overrides)
    resp = client.post("/api/v1/books", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def make_entry(client, book_id, headers):
    resp = client.post(
        f"/api/v1/books/{book_id}/entries",
        json={"rating": 8, "review_text": "Great!"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def make_comment(client, entry_id, headers, text="Nice review!", parent_id=None):
    payload = {"comment_text": text}
    if parent_id:
        payload["parent_comment_id"] = parent_id
    resp = client.post(
        f"/api/v1/entries/{entry_id}/comments",
        json=payload,
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestComments:
    def test_create_top_level_comment(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        comment = make_comment(client, entry["entry_id"], headers)
        assert comment["comment_text"] == "Nice review!"
        assert comment["entry_id"] == entry["entry_id"]
        assert comment["is_deleted"] is False
        # Top-level path = just the comment_id (no dots)
        assert "." not in comment["path"]

    def test_create_reply(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        parent = make_comment(client, entry["entry_id"], headers, "Parent")
        reply = make_comment(
            client, entry["entry_id"], headers, "Reply", parent_id=parent["comment_id"]
        )
        # Reply path should be parent_path.reply_id
        assert reply["path"].startswith(parent["path"])
        assert "." in reply["path"]

    def test_nested_reply(self, client):
        """Three levels deep: comment → reply → reply-to-reply."""
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        c1 = make_comment(client, entry["entry_id"], headers, "Level 1")
        c2 = make_comment(
            client, entry["entry_id"], headers, "Level 2", parent_id=c1["comment_id"]
        )
        c3 = make_comment(
            client, entry["entry_id"], headers, "Level 3", parent_id=c2["comment_id"]
        )
        # c3 path should have 3 segments
        assert c3["path"].count(".") == 2
        assert c3["path"].startswith(c1["path"])

    def test_comment_requires_auth(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        resp = client.post(
            f"/api/v1/entries/{entry['entry_id']}/comments",
            json={"comment_text": "Anonymous?"},
        )
        assert resp.status_code == 401

    def test_comment_on_nonexistent_entry(self, client):
        make_user(client)
        headers = auth_header(client)
        resp = client.post(
            f"/api/v1/entries/{uuid4()}/comments",
            json={"comment_text": "Where?"},
            headers=headers,
        )
        assert resp.status_code == 404

    def test_reply_to_nonexistent_parent(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        resp = client.post(
            f"/api/v1/entries/{entry['entry_id']}/comments",
            json={"comment_text": "Reply", "parent_comment_id": str(uuid4())},
            headers=headers,
        )
        assert resp.status_code == 404

    def test_list_thread_in_tree_order(self, client):
        """Comments sorted by ltree path = correct thread order."""
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        c1 = make_comment(client, entry["entry_id"], headers, "First")
        c2 = make_comment(client, entry["entry_id"], headers, "Second")
        c1_reply = make_comment(
            client,
            entry["entry_id"],
            headers,
            "Reply to first",
            parent_id=c1["comment_id"],
        )
        resp = client.get(f"/api/v1/entries/{entry['entry_id']}/comments")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        paths = [c["path"] for c in body["comments"]]
        # ltree sort: c1, c1_reply (child of c1), c2
        assert paths == sorted(paths)

    def test_get_single_comment(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        comment = make_comment(client, entry["entry_id"], headers)
        resp = client.get(f"/api/v1/comments/{comment['comment_id']}")
        assert resp.status_code == 200
        assert resp.json()["comment_id"] == comment["comment_id"]

    def test_get_replies_subtree(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        c1 = make_comment(client, entry["entry_id"], headers, "Root")
        c2 = make_comment(
            client, entry["entry_id"], headers, "Reply", parent_id=c1["comment_id"]
        )
        c3 = make_comment(
            client, entry["entry_id"], headers, "Deep reply", parent_id=c2["comment_id"]
        )
        # Also a sibling top-level comment that should NOT appear
        make_comment(client, entry["entry_id"], headers, "Other thread")
        resp = client.get(f"/api/v1/comments/{c1['comment_id']}/replies")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2  # c2 and c3, not the other thread
        ids = {c["comment_id"] for c in body["comments"]}
        assert c2["comment_id"] in ids
        assert c3["comment_id"] in ids

    def test_soft_delete_comment(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        comment = make_comment(client, entry["entry_id"], headers, "Delete me")
        resp = client.delete(
            f"/api/v1/comments/{comment['comment_id']}", headers=headers
        )
        assert resp.status_code == 204
        # Comment still exists but text is [deleted]
        resp = client.get(f"/api/v1/comments/{comment['comment_id']}")
        assert resp.status_code == 200
        assert resp.json()["comment_text"] == "[deleted]"
        assert resp.json()["is_deleted"] is True

    def test_soft_delete_preserves_thread(self, client):
        """Deleting a parent doesn't orphan replies."""
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        parent = make_comment(client, entry["entry_id"], headers, "Parent")
        child = make_comment(
            client, entry["entry_id"], headers, "Child", parent_id=parent["comment_id"]
        )
        # Delete parent
        client.delete(f"/api/v1/comments/{parent['comment_id']}", headers=headers)
        # Child's path should still be intact — thread is preserved
        resp = client.get(f"/api/v1/comments/{child['comment_id']}")
        assert resp.status_code == 200
        assert resp.json()["path"] == child["path"]
        # Full thread still returns both
        resp = client.get(f"/api/v1/entries/{entry['entry_id']}/comments")
        assert resp.json()["total"] == 2

    def test_delete_not_owner(self, client):
        make_user(client)
        make_user(client, username="alice", email="alice@example.com")
        headers_test = auth_header(client)
        headers_alice = auth_header(client, email="alice@example.com")
        book = make_book(client, headers_test)
        entry = make_entry(client, book["book_id"], headers_test)
        comment = make_comment(client, entry["entry_id"], headers_test)
        resp = client.delete(
            f"/api/v1/comments/{comment['comment_id']}", headers=headers_alice
        )
        assert resp.status_code == 403

    def test_empty_comment_rejected(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        entry = make_entry(client, book["book_id"], headers)
        resp = client.post(
            f"/api/v1/entries/{entry['entry_id']}/comments",
            json={"comment_text": ""},
            headers=headers,
        )
        assert resp.status_code == 422
