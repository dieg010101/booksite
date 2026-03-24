"""Tests for the contributors router.

Run: pytest tests/test_contributors_router.py -v
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


def make_contributor(client, headers, name="Frank Herbert", bio=None):
    payload = {"name": name}
    if bio:
        payload["bio"] = bio
    resp = client.post("/api/v1/contributors", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestContributorCRUD:
    def test_create_contributor(self, client):
        make_user(client)
        headers = auth_header(client)
        c = make_contributor(client, headers, name="Ursula K. Le Guin")
        assert c["name"] == "Ursula K. Le Guin"
        assert "contributor_id" in c

    def test_create_contributor_with_bio(self, client):
        make_user(client)
        headers = auth_header(client)
        c = make_contributor(client, headers, name="Tolkien", bio="Author of LOTR")
        assert c["bio"] == "Author of LOTR"

    def test_create_contributor_requires_auth(self, client):
        resp = client.post("/api/v1/contributors", json={"name": "Nobody"})
        assert resp.status_code == 401

    def test_get_contributor(self, client):
        make_user(client)
        headers = auth_header(client)
        c = make_contributor(client, headers)
        resp = client.get(f"/api/v1/contributors/{c['contributor_id']}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Frank Herbert"

    def test_get_contributor_not_found(self, client):
        resp = client.get(f"/api/v1/contributors/{uuid4()}")
        assert resp.status_code == 404

    def test_list_contributors(self, client):
        make_user(client)
        headers = auth_header(client)
        make_contributor(client, headers, name="Author A")
        make_contributor(client, headers, name="Author B")
        resp = client.get("/api/v1/contributors")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_search_contributors(self, client):
        make_user(client)
        headers = auth_header(client)
        make_contributor(client, headers, name="Ursula K. Le Guin")
        make_contributor(client, headers, name="Frank Herbert")
        resp = client.get("/api/v1/contributors?q=ursula")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert "Ursula" in resp.json()[0]["name"]

    def test_update_contributor(self, client):
        make_user(client)
        headers = auth_header(client)
        c = make_contributor(client, headers)
        resp = client.patch(
            f"/api/v1/contributors/{c['contributor_id']}",
            json={"bio": "Science fiction legend"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["bio"] == "Science fiction legend"
        assert resp.json()["name"] == "Frank Herbert"  # unchanged


class TestBookContributorLinks:
    def test_add_contributor_to_book(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers, title="Dune")
        c = make_contributor(client, headers)
        resp = client.post(
            f"/api/v1/books/{book['book_id']}/contributors",
            json={"contributor_id": c["contributor_id"], "role": "author"},
            headers=headers,
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "author"

    def test_duplicate_role_rejected(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        c = make_contributor(client, headers)
        client.post(
            f"/api/v1/books/{book['book_id']}/contributors",
            json={"contributor_id": c["contributor_id"], "role": "author"},
            headers=headers,
        )
        resp = client.post(
            f"/api/v1/books/{book['book_id']}/contributors",
            json={"contributor_id": c["contributor_id"], "role": "author"},
            headers=headers,
        )
        assert resp.status_code == 409

    def test_same_contributor_different_roles(self, client):
        """One person can be both author and illustrator."""
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        c = make_contributor(client, headers)
        client.post(
            f"/api/v1/books/{book['book_id']}/contributors",
            json={"contributor_id": c["contributor_id"], "role": "author"},
            headers=headers,
        )
        resp = client.post(
            f"/api/v1/books/{book['book_id']}/contributors",
            json={"contributor_id": c["contributor_id"], "role": "illustrator"},
            headers=headers,
        )
        assert resp.status_code == 201

    def test_list_book_contributors(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        c1 = make_contributor(client, headers, name="Author A")
        c2 = make_contributor(client, headers, name="Illustrator B")
        client.post(
            f"/api/v1/books/{book['book_id']}/contributors",
            json={"contributor_id": c1["contributor_id"], "role": "author"},
            headers=headers,
        )
        client.post(
            f"/api/v1/books/{book['book_id']}/contributors",
            json={"contributor_id": c2["contributor_id"], "role": "illustrator"},
            headers=headers,
        )
        resp = client.get(f"/api/v1/books/{book['book_id']}/contributors")
        assert resp.status_code == 200
        assert len(resp.json()) == 2
        roles = {c["role"] for c in resp.json()}
        assert "author" in roles
        assert "illustrator" in roles

    def test_remove_contributor_from_book(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        c = make_contributor(client, headers)
        client.post(
            f"/api/v1/books/{book['book_id']}/contributors",
            json={"contributor_id": c["contributor_id"], "role": "author"},
            headers=headers,
        )
        resp = client.delete(
            f"/api/v1/books/{book['book_id']}/contributors/{c['contributor_id']}/author",
            headers=headers,
        )
        assert resp.status_code == 204
        # Should be gone
        resp = client.get(f"/api/v1/books/{book['book_id']}/contributors")
        assert len(resp.json()) == 0

    def test_invalid_role_rejected(self, client):
        make_user(client)
        headers = auth_header(client)
        book = make_book(client, headers)
        c = make_contributor(client, headers)
        resp = client.post(
            f"/api/v1/books/{book['book_id']}/contributors",
            json={"contributor_id": c["contributor_id"], "role": "wizard"},
            headers=headers,
        )
        assert resp.status_code == 422

    def test_list_contributor_books(self, client):
        make_user(client)
        headers = auth_header(client)
        c = make_contributor(client, headers, name="Prolific Author")
        b1 = make_book(client, headers, title="Book 1", external_api_id="ext_1")
        b2 = make_book(client, headers, title="Book 2", external_api_id="ext_2")
        client.post(
            f"/api/v1/books/{b1['book_id']}/contributors",
            json={"contributor_id": c["contributor_id"], "role": "author"},
            headers=headers,
        )
        client.post(
            f"/api/v1/books/{b2['book_id']}/contributors",
            json={"contributor_id": c["contributor_id"], "role": "author"},
            headers=headers,
        )
        resp = client.get(f"/api/v1/contributors/{c['contributor_id']}/books")
        assert resp.status_code == 200
        assert len(resp.json()) == 2
