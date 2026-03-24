"""Tests for CORS configuration.

Run: pytest tests/test_cors.py -v
"""

import pytest
from tests.conftest import client  # noqa: F401


class TestCORS:
    def test_cors_allows_sveltekit_origin(self, client):
        """SvelteKit dev server (localhost:5173) should get CORS headers."""
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert (
            resp.headers.get("access-control-allow-origin") == "http://localhost:5173"
        )
        assert "GET" in resp.headers.get("access-control-allow-methods", "")

    def test_cors_allows_credentials(self, client):
        """Credentials (cookies/auth headers) should be allowed."""
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.headers.get("access-control-allow-credentials") == "true"

    def test_cors_headers_on_actual_request(self, client):
        """Regular GET request from allowed origin gets CORS headers."""
        resp = client.get(
            "/health",
            headers={"Origin": "http://localhost:5173"},
        )
        assert resp.status_code == 200
        assert (
            resp.headers.get("access-control-allow-origin") == "http://localhost:5173"
        )
