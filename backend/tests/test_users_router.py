"""Tests for the users router.

Run: pytest tests/test_users_router.py -v
"""

import pytest

from tests.conftest import auth_header, client, make_user  # noqa: F401


# ═══════════════════════════════════════════════════════════════════════════
#  REGISTRATION
# ═══════════════════════════════════════════════════════════════════════════
class TestRegister:
    def test_register_success(self, client):
        data = make_user(client)
        assert data["username"] == "testuser"
        assert data["location"] == "California"
        assert "user_id" in data
        assert "password" not in data
        assert "password_hash" not in data
        assert "email" not in data  # UserRead doesn't expose email

    def test_register_returns_follower_counts(self, client):
        data = make_user(client)
        assert data["follower_count"] == 0
        assert data["following_count"] == 0

    def test_register_duplicate_email(self, client):
        make_user(client)
        resp = client.post(
            "/api/v1/users/register",
            json={
                "username": "other",
                "email": "test@example.com",
                "password": "SecurePass1!",
            },
        )
        assert resp.status_code == 409
        assert "Email already registered" in resp.json()["detail"]

    def test_register_duplicate_username(self, client):
        make_user(client)
        resp = client.post(
            "/api/v1/users/register",
            json={
                "username": "testuser",
                "email": "other@example.com",
                "password": "SecurePass1!",
            },
        )
        assert resp.status_code == 409
        assert "Username already taken" in resp.json()["detail"]

    def test_register_short_password(self, client):
        resp = client.post(
            "/api/v1/users/register",
            json={"username": "abc", "email": "a@b.com", "password": "short"},
        )
        assert resp.status_code == 422  # Pydantic validation

    def test_register_invalid_username_chars(self, client):
        resp = client.post(
            "/api/v1/users/register",
            json={
                "username": "bad user!",
                "email": "a@b.com",
                "password": "SecurePass1!",
            },
        )
        assert resp.status_code == 422

    def test_register_username_too_short(self, client):
        resp = client.post(
            "/api/v1/users/register",
            json={
                "username": "ab",
                "email": "a@b.com",
                "password": "SecurePass1!",
            },
        )
        assert resp.status_code == 422

    def test_register_invalid_email(self, client):
        resp = client.post(
            "/api/v1/users/register",
            json={
                "username": "validuser",
                "email": "not-an-email",
                "password": "SecurePass1!",
            },
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
#  LOGIN
# ═══════════════════════════════════════════════════════════════════════════
class TestLogin:
    def test_login_success(self, client):
        make_user(client)
        resp = client.post(
            "/api/v1/users/login",
            json={"email": "test@example.com", "password": "SecurePass1!"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["token_type"] == "bearer"

    def test_login_wrong_password(self, client):
        make_user(client)
        resp = client.post(
            "/api/v1/users/login",
            json={"email": "test@example.com", "password": "WrongPass!"},
        )
        assert resp.status_code == 401

    def test_login_nonexistent_email(self, client):
        resp = client.post(
            "/api/v1/users/login",
            json={"email": "nobody@example.com", "password": "whatever1!"},
        )
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════
#  GET /me  (authenticated)
# ═══════════════════════════════════════════════════════════════════════════
class TestMe:
    def test_get_me(self, client):
        make_user(client)
        headers = auth_header(client)
        resp = client.get("/api/v1/users/me", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "testuser"
        assert body["email"] == "test@example.com"  # private field present
        assert "updated_at" in body
        assert "user_id" in body

    def test_get_me_no_token(self, client):
        resp = client.get("/api/v1/users/me")
        assert resp.status_code == 401

    def test_get_me_bad_token(self, client):
        resp = client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer garbage.token.here"},
        )
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════
#  PATCH /me
# ═══════════════════════════════════════════════════════════════════════════
class TestUpdateMe:
    def test_update_location(self, client):
        make_user(client)
        headers = auth_header(client)
        resp = client.patch(
            "/api/v1/users/me",
            json={"location": "New York"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["location"] == "New York"

    def test_update_avatar(self, client):
        make_user(client)
        headers = auth_header(client)
        resp = client.patch(
            "/api/v1/users/me",
            json={"avatar_url": "https://example.com/pic.jpg"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["avatar_url"] == "https://example.com/pic.jpg"

    def test_update_partial_leaves_other_fields(self, client):
        make_user(client)
        headers = auth_header(client)
        # Only update avatar, location should stay
        client.patch(
            "/api/v1/users/me",
            json={"avatar_url": "https://example.com/pic.jpg"},
            headers=headers,
        )
        resp = client.get("/api/v1/users/me", headers=headers)
        assert resp.json()["location"] == "California"
        assert resp.json()["avatar_url"] == "https://example.com/pic.jpg"

    def test_update_me_no_auth(self, client):
        resp = client.patch("/api/v1/users/me", json={"location": "hack"})
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════
#  GET /{username}  (public profile)
# ═══════════════════════════════════════════════════════════════════════════
class TestPublicProfile:
    def test_get_profile(self, client):
        make_user(client)
        resp = client.get("/api/v1/users/testuser")
        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "testuser"
        assert "email" not in body  # public view shouldn't leak email

    def test_get_profile_not_found(self, client):
        resp = client.get("/api/v1/users/nobody")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
#  FOLLOW / UNFOLLOW
# ═══════════════════════════════════════════════════════════════════════════
class TestFollow:
    def _setup_two_users(self, client):
        make_user(client)
        make_user(client, username="alice", email="alice@example.com")
        return auth_header(client)  # logged in as testuser

    def test_follow_success(self, client):
        headers = self._setup_two_users(client)
        resp = client.post("/api/v1/users/alice/follow", headers=headers)
        assert resp.status_code == 201
        assert "alice" in resp.json()["detail"]

    def test_follow_self_rejected(self, client):
        make_user(client)
        headers = auth_header(client)
        resp = client.post("/api/v1/users/testuser/follow", headers=headers)
        assert resp.status_code == 400

    def test_follow_duplicate_rejected(self, client):
        headers = self._setup_two_users(client)
        client.post("/api/v1/users/alice/follow", headers=headers)
        resp = client.post("/api/v1/users/alice/follow", headers=headers)
        assert resp.status_code == 409

    def test_follow_nonexistent_user(self, client):
        make_user(client)
        headers = auth_header(client)
        resp = client.post("/api/v1/users/ghost/follow", headers=headers)
        assert resp.status_code == 404

    def test_unfollow_success(self, client):
        headers = self._setup_two_users(client)
        client.post("/api/v1/users/alice/follow", headers=headers)
        resp = client.delete("/api/v1/users/alice/follow", headers=headers)
        assert resp.status_code == 200
        assert "Unfollowed" in resp.json()["detail"]

    def test_unfollow_not_following(self, client):
        headers = self._setup_two_users(client)
        resp = client.delete("/api/v1/users/alice/follow", headers=headers)
        assert resp.status_code == 404

    def test_follow_requires_auth(self, client):
        make_user(client, username="alice", email="alice@example.com")
        resp = client.post("/api/v1/users/alice/follow")
        assert resp.status_code == 401
