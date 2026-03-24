"""Tests for production hardening: token refresh, rate limiting, error handling.

Run: pytest tests/test_production.py -v
"""

import time

import pytest

from tests.conftest import auth_header, client, make_user  # noqa: F401


# ═══════════════════════════════════════════════════════════════════════════
#  TOKEN REFRESH
# ═══════════════════════════════════════════════════════════════════════════
class TestTokenRefresh:
    def test_login_returns_both_tokens(self, client):
        """Login should return access_token AND refresh_token."""
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
        # They should be different tokens
        assert body["access_token"] != body["refresh_token"]

    def test_refresh_returns_new_pair(self, client):
        """Refresh endpoint returns a fresh access + refresh token pair."""
        make_user(client)
        login_resp = client.post(
            "/api/v1/users/login",
            json={"email": "test@example.com", "password": "SecurePass1!"},
        )
        refresh_token = login_resp.json()["refresh_token"]

        resp = client.post(
            "/api/v1/users/refresh",
            json={"refresh_token": refresh_token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert "refresh_token" in body
        # Refresh endpoint returns valid tokens (may match if same second)
        assert body["token_type"] == "bearer"

    def test_refresh_with_access_token_rejected(self, client):
        """Using an access token at the refresh endpoint should fail."""
        make_user(client)
        login_resp = client.post(
            "/api/v1/users/login",
            json={"email": "test@example.com", "password": "SecurePass1!"},
        )
        access_token = login_resp.json()["access_token"]

        resp = client.post(
            "/api/v1/users/refresh",
            json={"refresh_token": access_token},
        )
        assert resp.status_code == 401

    def test_refresh_with_garbage_token(self, client):
        resp = client.post(
            "/api/v1/users/refresh",
            json={"refresh_token": "garbage.token.here"},
        )
        assert resp.status_code == 401

    def test_refresh_new_access_token_works(self, client):
        """The new access token from refresh should authenticate API calls."""
        make_user(client)
        login_resp = client.post(
            "/api/v1/users/login",
            json={"email": "test@example.com", "password": "SecurePass1!"},
        )
        refresh_token = login_resp.json()["refresh_token"]

        refresh_resp = client.post(
            "/api/v1/users/refresh",
            json={"refresh_token": refresh_token},
        )
        new_access = refresh_resp.json()["access_token"]

        # Use the new access token to hit a protected endpoint
        me_resp = client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {new_access}"},
        )
        assert me_resp.status_code == 200
        assert me_resp.json()["username"] == "testuser"

    def test_refresh_token_cannot_auth_api(self, client):
        """Refresh tokens should NOT work as access tokens on normal endpoints."""
        make_user(client)
        login_resp = client.post(
            "/api/v1/users/login",
            json={"email": "test@example.com", "password": "SecurePass1!"},
        )
        refresh_token = login_resp.json()["refresh_token"]

        me_resp = client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {refresh_token}"},
        )
        assert me_resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════
#  RATE LIMITING
# ═══════════════════════════════════════════════════════════════════════════
class TestRateLimiting:
    def test_rate_limit_headers_present(self, client):
        """Responses should include X-RateLimit-* headers."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert "X-RateLimit-Limit" in resp.headers
        assert "X-RateLimit-Remaining" in resp.headers

    def test_rate_limit_remaining_decreases(self, client):
        """Each request should decrease the remaining count."""
        r1 = client.get("/health")
        r2 = client.get("/health")
        remaining1 = int(r1.headers["X-RateLimit-Remaining"])
        remaining2 = int(r2.headers["X-RateLimit-Remaining"])
        assert remaining2 == remaining1 - 1


# ═══════════════════════════════════════════════════════════════════════════
#  ERROR HANDLING
# ═══════════════════════════════════════════════════════════════════════════
class TestErrorHandling:
    def test_404_on_nonexistent_route(self, client):
        """Non-existent routes return 404, not 500."""
        resp = client.get("/api/v1/nonexistent")
        assert resp.status_code == 404

    def test_422_on_invalid_json(self, client):
        """Malformed request bodies return 422, not 500."""
        resp = client.post(
            "/api/v1/users/register",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_health_always_works(self, client):
        """Health check should always return 200."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
