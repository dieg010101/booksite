"""Tests for the book lists router.

Run: pytest tests/test_lists_router.py -v
"""

import pytest
from uuid import uuid4

from tests.conftest import auth_header, client, make_user  # noqa: F401


def make_book(client, headers, **overrides):
    payload = {"external_api_id": f"ext_{uuid4().hex[:12]}", "title": "Test Book"}
    payload.update(overrides)
    resp = client.post("/api/v1/books", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def make_list(client, headers, name="My Favorites", **overrides):
    payload = {"list_name": name, "is_public": True}
    payload.update(overrides)
    resp = client.post("/api/v1/lists", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestListCRUD:
    def test_create_list(self, client):
        make_user(client)
        headers = auth_header(client)
        lst = make_list(client, headers, name="2026 Reads")
        assert lst["list_name"] == "2026 Reads"
        assert lst["is_public"] is True
        assert "list_id" in lst

    def test_create_private_list(self, client):
        make_user(client)
        headers = auth_header(client)
        lst = make_list(client, headers, name="Secret List", is_public=False)
        assert lst["is_public"] is False

    def test_create_list_requires_auth(self, client):
        resp = client.post("/api/v1/lists", json={"list_name": "Nope"})
        assert resp.status_code == 401

    def test_duplicate_list_name_rejected(self, client):
        make_user(client)
        headers = auth_header(client)
        make_list(client, headers, name="Favorites")
        resp = client.post(
            "/api/v1/lists",
            json={"list_name": "Favorites"},
            headers=headers,
        )
        assert resp.status_code == 409

    def test_get_list(self, client):
        make_user(client)
        headers = auth_header(client)
        lst = make_list(client, headers)
        resp = client.get(f"/api/v1/lists/{lst['list_id']}")
        assert resp.status_code == 200
        assert resp.json()["list_name"] == "My Favorites"

    def test_update_list(self, client):
        make_user(client)
        headers = auth_header(client)
        lst = make_list(client, headers)
        resp = client.patch(
            f"/api/v1/lists/{lst['list_id']}",
            json={"description": "The best books"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["description"] == "The best books"

    def test_update_list_not_owner(self, client):
        make_user(client)
        make_user(client, username="alice", email="alice@example.com")
        headers_test = auth_header(client)
        headers_alice = auth_header(client, email="alice@example.com")
        lst = make_list(client, headers_test)
        resp = client.patch(
            f"/api/v1/lists/{lst['list_id']}",
            json={"description": "Hacked"},
            headers=headers_alice,
        )
        assert resp.status_code == 403

    def test_rename_list_duplicate_rejected(self, client):
        make_user(client)
        headers = auth_header(client)
        make_list(client, headers, name="List A")
        lst_b = make_list(client, headers, name="List B")
        resp = client.patch(
            f"/api/v1/lists/{lst_b['list_id']}",
            json={"list_name": "List A"},
            headers=headers,
        )
        assert resp.status_code == 409

    def test_delete_list(self, client):
        make_user(client)
        headers = auth_header(client)
        lst = make_list(client, headers)
        resp = client.delete(f"/api/v1/lists/{lst['list_id']}", headers=headers)
        assert resp.status_code == 204
        resp = client.get(f"/api/v1/lists/{lst['list_id']}")
        assert resp.status_code == 404

    def test_delete_list_not_owner(self, client):
        make_user(client)
        make_user(client, username="alice", email="alice@example.com")
        headers_test = auth_header(client)
        headers_alice = auth_header(client, email="alice@example.com")
        lst = make_list(client, headers_test)
        resp = client.delete(f"/api/v1/lists/{lst['list_id']}", headers=headers_alice)
        assert resp.status_code == 403


class TestListBrowse:
    def test_user_lists(self, client):
        make_user(client)
        headers = auth_header(client)
        make_list(client, headers, name="List 1")
        make_list(client, headers, name="List 2")
        make_list(client, headers, name="Private", is_public=False)
        resp = client.get("/api/v1/users/testuser/lists")
        assert resp.status_code == 200
        assert len(resp.json()) == 2  # private list excluded

    def test_user_lists_not_found(self, client):
        resp = client.get("/api/v1/users/nobody/lists")
        assert resp.status_code == 404

    def test_explore_lists(self, client):
        make_user(client)
        headers = auth_header(client)
        make_list(client, headers, name="Public List")
        make_list(client, headers, name="Hidden", is_public=False)
        resp = client.get("/api/v1/lists/explore")
        assert resp.status_code == 200
        names = [l["list_name"] for l in resp.json()]
        assert "Public List" in names
        assert "Hidden" not in names


class TestListItems:
    def test_add_item(self, client):
        make_user(client)
        headers = auth_header(client)
        lst = make_list(client, headers)
        book = make_book(client, headers)
        resp = client.post(
            f"/api/v1/lists/{lst['list_id']}/items",
            json={"book_id": book["book_id"]},
            headers=headers,
        )
        assert resp.status_code == 201
        assert resp.json()["book_id"] == book["book_id"]
        assert resp.json()["position"] == 0

    def test_add_item_auto_position(self, client):
        """Items auto-append with incrementing positions."""
        make_user(client)
        headers = auth_header(client)
        lst = make_list(client, headers)
        b1 = make_book(client, headers, title="Book 1", external_api_id="ext_1")
        b2 = make_book(client, headers, title="Book 2", external_api_id="ext_2")
        client.post(
            f"/api/v1/lists/{lst['list_id']}/items",
            json={"book_id": b1["book_id"]},
            headers=headers,
        )
        resp = client.post(
            f"/api/v1/lists/{lst['list_id']}/items",
            json={"book_id": b2["book_id"]},
            headers=headers,
        )
        assert resp.json()["position"] == 1

    def test_add_duplicate_item_rejected(self, client):
        make_user(client)
        headers = auth_header(client)
        lst = make_list(client, headers)
        book = make_book(client, headers)
        client.post(
            f"/api/v1/lists/{lst['list_id']}/items",
            json={"book_id": book["book_id"]},
            headers=headers,
        )
        resp = client.post(
            f"/api/v1/lists/{lst['list_id']}/items",
            json={"book_id": book["book_id"]},
            headers=headers,
        )
        assert resp.status_code == 409

    def test_add_item_not_owner(self, client):
        make_user(client)
        make_user(client, username="alice", email="alice@example.com")
        headers_test = auth_header(client)
        headers_alice = auth_header(client, email="alice@example.com")
        lst = make_list(client, headers_test)
        book = make_book(client, headers_test)
        resp = client.post(
            f"/api/v1/lists/{lst['list_id']}/items",
            json={"book_id": book["book_id"]},
            headers=headers_alice,
        )
        assert resp.status_code == 403

    def test_list_items_in_order(self, client):
        make_user(client)
        headers = auth_header(client)
        lst = make_list(client, headers)
        books = []
        for i in range(3):
            books.append(
                make_book(
                    client, headers, title=f"Book {i}", external_api_id=f"ext_{i}"
                )
            )
        for b in books:
            client.post(
                f"/api/v1/lists/{lst['list_id']}/items",
                json={"book_id": b["book_id"]},
                headers=headers,
            )
        resp = client.get(f"/api/v1/lists/{lst['list_id']}/items")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 3
        positions = [i["position"] for i in items]
        assert positions == [0, 1, 2]

    def test_remove_item(self, client):
        make_user(client)
        headers = auth_header(client)
        lst = make_list(client, headers)
        book = make_book(client, headers)
        client.post(
            f"/api/v1/lists/{lst['list_id']}/items",
            json={"book_id": book["book_id"]},
            headers=headers,
        )
        resp = client.delete(
            f"/api/v1/lists/{lst['list_id']}/items/{book['book_id']}",
            headers=headers,
        )
        assert resp.status_code == 204
        resp = client.get(f"/api/v1/lists/{lst['list_id']}/items")
        assert len(resp.json()) == 0

    def test_reorder_items(self, client):
        make_user(client)
        headers = auth_header(client)
        lst = make_list(client, headers)
        books = []
        for i in range(3):
            books.append(
                make_book(
                    client, headers, title=f"Book {i}", external_api_id=f"ext_{i}"
                )
            )
        for b in books:
            client.post(
                f"/api/v1/lists/{lst['list_id']}/items",
                json={"book_id": b["book_id"]},
                headers=headers,
            )
        # Reverse the order
        reversed_ids = [b["book_id"] for b in reversed(books)]
        resp = client.put(
            f"/api/v1/lists/{lst['list_id']}/items/reorder",
            json={"book_ids": reversed_ids},
            headers=headers,
        )
        assert resp.status_code == 200
        items = resp.json()
        assert items[0]["book_id"] == books[2]["book_id"]
        assert items[1]["book_id"] == books[1]["book_id"]
        assert items[2]["book_id"] == books[0]["book_id"]

    def test_reorder_not_owner(self, client):
        make_user(client)
        make_user(client, username="alice", email="alice@example.com")
        headers_test = auth_header(client)
        headers_alice = auth_header(client, email="alice@example.com")
        lst = make_list(client, headers_test)
        resp = client.put(
            f"/api/v1/lists/{lst['list_id']}/items/reorder",
            json={"book_ids": []},
            headers=headers_alice,
        )
        assert resp.status_code == 403
