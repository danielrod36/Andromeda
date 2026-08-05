"""Tests for the Andromeda web shell boot and security contracts (U4).

Uses FastAPI's synchronous TestClient (no asyncio interaction).
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _get_client() -> TestClient:
    from src.web.app import create_app

    # Use 127.0.0.1 as base_url so requests pass the host allowlist.
    return TestClient(create_app(), base_url="http://127.0.0.1")


class TestAppBoot:
    """U4/U9: the app boots and the root route redirects to the menu."""

    def test_get_index_redirects_to_menu(self):
        """GET / redirects to /menu (U9)."""
        with _get_client() as client:
            response = client.get("/", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/menu"

    def test_get_index_follows_to_menu(self):
        """GET / following redirects lands on the menu page."""
        with _get_client() as client:
            response = client.get("/")
        assert response.status_code == 200
        assert "Andromeda" in response.text

    def test_entry_module_importable(self):
        """The __main__ module is importable and constructs the app."""
        from src.web.app import create_app

        app = create_app()
        assert app is not None


class TestStaticAssets:
    """U4: static assets (CSS, JS, htmx) are served."""

    def test_tokens_css_served(self):
        with _get_client() as client:
            response = client.get("/static/tokens.css")
        assert response.status_code == 200
        content = response.text
        assert "--ink" in content
        assert "--vellum" in content
        assert "--brass" in content

    def test_app_css_served(self):
        with _get_client() as client:
            response = client.get("/static/app.css")
        assert response.status_code == 200

    def test_app_js_served(self):
        with _get_client() as client:
            response = client.get("/static/app.js")
        assert response.status_code == 200

    def test_htmx_served(self):
        with _get_client() as client:
            response = client.get("/static/vendor/htmx.min.js")
        assert response.status_code == 200
        assert len(response.text) > 1000  # Real JS content.


class TestTokensCSS:
    """U4: tokens.css defines the six palette variables and three font stacks."""

    def test_six_palette_variables(self):
        with _get_client() as client:
            response = client.get("/static/tokens.css")
        css = response.text
        for var in ("--ink", "--vellum", "--brass", "--verdigris", "--signal-red", "--haze"):
            assert var in css, f"Missing palette variable {var}"

    def test_three_font_stacks(self):
        with _get_client() as client:
            response = client.get("/static/tokens.css")
        css = response.text
        assert "--font-prose" in css
        assert "--font-chrome" in css
        assert "--font-engine" in css


class TestSameOriginGuard:
    """U4: same-origin guard rejects cross-origin POSTs."""

    def test_same_origin_post_allowed(self):
        """A POST with matching Origin header passes the guard."""
        with _get_client() as client:
            response = client.post(
                "/",
                data={"test": "value"},
                headers={"Origin": "http://127.0.0.1"},
            )
        # 405 is expected — there's no POST handler for /.
        # The point is we get past the guard (not 403).
        assert response.status_code != 403

    def test_cross_origin_post_rejected(self):
        """A POST with mismatched Origin header is rejected with 403."""
        with _get_client() as client:
            response = client.post(
                "/",
                data={"test": "value"},
                headers={"Origin": "http://evil.example.com"},
            )
        assert response.status_code == 403

    def test_post_without_origin_rejected(self):
        """A POST with no Origin header is rejected defensively."""
        with _get_client() as client:
            response = client.post("/", data={"test": "value"})
        assert response.status_code == 403

    def test_get_without_origin_allowed(self):
        """GET requests are never blocked by the guard."""
        with _get_client() as client:
            response = client.get("/")
        assert response.status_code == 200

    def test_dns_rebinding_rejected(self):
        """A POST whose Host and Origin match but aren't localhost is rejected.

        Simulates a DNS-rebinding attack: an attacker's domain resolves to
        127.0.0.1, so the browser treats the POST as same-origin. The guard
        must still reject it because the Host isn't in the allowlist.
        """
        from src.web.app import create_app

        client = TestClient(create_app(), base_url="http://evil.example.com")
        with client:
            response = client.post(
                "/",
                data={"test": "value"},
                headers={"Origin": "http://evil.example.com"},
            )
        assert response.status_code == 403
