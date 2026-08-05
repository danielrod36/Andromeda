"""Tests for theme-pack theming and quality-floor accessibility (U17, R19).

Covers:
- ``resolve_theme_attr`` maps known packs and falls back for unknown ones.
- Both theme blocks in ``tokens.css`` define every required token.
- Route responses carry the ``data-theme`` attribute from the campaign's pack.
- Quality-floor CSS/JS: ``prefers-reduced-motion``, ``:focus-visible``,
  responsive overlay media query, ARIA live region, drawer disclosure
  semantics (labelled trigger, ``aria-expanded``, ``aria-controls``,
  Esc-to-close, focus return).
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from src.game.theming import DEFAULT_THEME, KNOWN_THEMES, resolve_theme_attr

# ---------------------------------------------------------------------------
# Theme resolution unit tests.
# ---------------------------------------------------------------------------


class TestResolveThemeAttr:
    """resolve_theme_attr maps packs to data-theme values (U17, R19)."""

    def test_scifi_known(self):
        assert resolve_theme_attr("scifi") == "scifi"

    def test_fantasy_known(self):
        assert resolve_theme_attr("fantasy") == "fantasy"

    def test_unknown_pack_falls_back(self):
        assert resolve_theme_attr("western") == DEFAULT_THEME

    def test_none_falls_back(self):
        assert resolve_theme_attr(None) == DEFAULT_THEME

    def test_empty_falls_back(self):
        assert resolve_theme_attr("") == DEFAULT_THEME

    def test_case_sensitive(self):
        """Theme pack matching is case-sensitive (packs are lowercase IDs)."""
        assert resolve_theme_attr("SciFi") == DEFAULT_THEME

    def test_known_themes_contains_both_packs(self):
        assert "scifi" in KNOWN_THEMES
        assert "fantasy" in KNOWN_THEMES


# ---------------------------------------------------------------------------
# Token completeness — both theme blocks define every required token.
# ---------------------------------------------------------------------------

_STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "web" / "static"

#: Tokens that must be defined in every [data-theme="..."] block.
REQUIRED_TOKENS = {
    "--ink",
    "--vellum",
    "--brass",
    "--verdigris",
    "--signal-red",
    "--haze",
    "--surface-tint",
    "--border-tint",
}


def _extract_theme_block(css: str, theme: str) -> str:
    """Extract the body of a ``[data-theme="<theme>"] { ... }`` block."""
    pattern = rf'\[data-theme="{re.escape(theme)}"\]\s*\{{([^}}]*)\}}'
    match = re.search(pattern, css)
    return match.group(1) if match else ""


def _extract_tokens(block: str) -> set[str]:
    """Pull ``--token-name`` identifiers from a CSS block."""
    return set(re.findall(r"(--[\w-]+)\s*:", block))


class TestTokenCompleteness:
    """Both theme blocks define every required token (U17, R19)."""

    def test_scifi_block_has_all_tokens(self):
        css = (_STATIC_DIR / "tokens.css").read_text()
        block = _extract_theme_block(css, "scifi")
        assert block, "Missing [data-theme='scifi'] block"
        defined = _extract_tokens(block)
        missing = REQUIRED_TOKENS - defined
        assert not missing, f"scifi block missing tokens: {missing}"

    def test_fantasy_block_has_all_tokens(self):
        css = (_STATIC_DIR / "tokens.css").read_text()
        block = _extract_theme_block(css, "fantasy")
        assert block, "Missing [data-theme='fantasy'] block"
        defined = _extract_tokens(block)
        missing = REQUIRED_TOKENS - defined
        assert not missing, f"fantasy block missing tokens: {missing}"

    def test_scifi_and_fantasy_have_different_palettes(self):
        """The whole point — different packs look different."""
        css = (_STATIC_DIR / "tokens.css").read_text()
        scifi_block = _extract_theme_block(css, "scifi")
        fantasy_block = _extract_theme_block(css, "fantasy")

        def _token_val(block: str, token: str) -> str | None:
            m = re.search(rf"{re.escape(token)}\s*:\s*([^;]+);", block)
            return m.group(1).strip() if m else None

        for token in ("--ink", "--vellum", "--brass"):
            scifi_val = _token_val(scifi_block, token)
            fantasy_val = _token_val(fantasy_block, token)
            assert scifi_val != fantasy_val, (
                f"{token} identical in both themes — no visual difference"
            )


# ---------------------------------------------------------------------------
# Route tests — data-theme follows the campaign's theme_pack.
# ---------------------------------------------------------------------------


def _get_client(saves_dir: Path) -> TestClient:
    from src.web.app import create_app
    from src.web.routes import adventure as adv_module
    from src.web.routes import inspector as insp_module
    from src.web.routes import lifepath as life_module
    from src.web.routes import memorial as mem_module
    from src.web.routes import menu as menu_module
    from src.web.routes import stream as stream_module

    saves_dir.mkdir(parents=True, exist_ok=True)
    menu_module.DEFAULT_SAVES_DIR = saves_dir
    life_module.DEFAULT_SAVES_DIR = saves_dir
    adv_module.DEFAULT_SAVES_DIR = saves_dir
    stream_module.DEFAULT_SAVES_DIR = saves_dir
    insp_module.DEFAULT_SAVES_DIR = saves_dir
    mem_module.DEFAULT_SAVES_DIR = saves_dir
    return TestClient(create_app(), base_url="http://127.0.0.1")


def _create_save(
    saves_dir: Path,
    name: str = "Hero",
    theme_pack: str = "scifi",
    alive: bool = True,
) -> Path:
    from src.engine.persistence import save
    from src.engine.state import CampaignConfig, GameState

    state = GameState.new(seed=42)
    state.campaign = CampaignConfig(
        theme_pack=theme_pack, resolution_profile="narrative", death_mode="narrative"
    )
    state.character.name = name
    state.character.characteristics = {
        "STR": 7,
        "DEX": 9,
        "END": 6,
        "INT": 8,
        "EDU": 10,
        "SOC": 5,
    }
    state.character.skills = {"Gun Combat": 1}
    state.character.career = "navy"
    state.character.terms = 2
    state.character.alive = alive
    state.narrative_log.append("mustered_out=true")
    path = saves_dir / f"{name}.json"
    save(state, path)
    return path


class TestRouteThemeAttribute:
    """The data-theme attribute follows the campaign's theme_pack (U17, R19)."""

    def test_adventure_scifi_theme(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir, theme_pack="scifi")
        with _get_client(saves_dir) as client:
            resp = client.get("/adventure/Hero")
        assert resp.status_code == 200
        assert 'data-theme="scifi"' in resp.text

    def test_adventure_fantasy_theme(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir, theme_pack="fantasy")
        with _get_client(saves_dir) as client:
            resp = client.get("/adventure/Hero")
        assert resp.status_code == 200
        assert 'data-theme="fantasy"' in resp.text

    def test_adventure_unknown_pack_falls_back(self, tmp_path: Path):
        """Unknown pack in resolve_theme_attr falls back — unit-tested separately
        since the engine itself rejects unknown packs at load time."""
        assert resolve_theme_attr("western") == DEFAULT_THEME

    def test_lifepath_fantasy_theme(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir, name="Recruit", theme_pack="fantasy")
        with _get_client(saves_dir) as client:
            resp = client.get("/play/Recruit")
        assert resp.status_code == 200
        assert 'data-theme="fantasy"' in resp.text

    def test_memorial_fantasy_theme(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir, name="Dead", theme_pack="fantasy", alive=False)
        with _get_client(saves_dir) as client:
            resp = client.get("/memorial/Dead")
        assert resp.status_code == 200
        assert 'data-theme="fantasy"' in resp.text

    def test_inspector_scifi_theme(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir, theme_pack="scifi")
        with _get_client(saves_dir) as client:
            resp = client.get("/inspector/Hero")
        assert resp.status_code == 200
        assert 'data-theme="scifi"' in resp.text

    def test_menu_has_default_theme(self, tmp_path: Path):
        """Non-save pages always get the default theme."""
        saves_dir = tmp_path / "saves"
        with _get_client(saves_dir) as client:
            resp = client.get("/menu")
        assert resp.status_code == 200
        assert 'data-theme="scifi"' in resp.text


# ---------------------------------------------------------------------------
# Quality-floor CSS/JS tests.
# ---------------------------------------------------------------------------


class TestQualityFloorCSS:
    """Required CSS constructs exist for the quality floor (U17)."""

    @property
    def _app_css(self) -> str:
        return (_STATIC_DIR / "app.css").read_text()

    def test_prefers_reduced_motion_exists(self):
        assert "prefers-reduced-motion" in self._app_css

    def test_focus_visible_exists(self):
        assert ":focus-visible" in self._app_css

    def test_responsive_overlay_exists(self):
        """Narrow viewport turns the drawer into an overlay."""
        assert "@media" in self._app_css
        assert "max-width" in self._app_css

    def test_theme_tokens_used_not_hardcoded(self):
        """CSS references --surface-tint / --border-tint, not just rgba."""
        css = self._app_css
        assert "var(--surface-tint)" in css
        assert "var(--border-tint)" in css


class TestQualityFloorJS:
    """Drawer disclosure JS: toggle, Esc, focus return (U17)."""

    @property
    def _app_js(self) -> str:
        return (_STATIC_DIR / "app.js").read_text()

    def test_esc_handler_exists(self):
        js = self._app_js
        assert "Escape" in js
        assert "toggleDrawer" in js

    def test_focus_return_exists(self):
        """Closing the drawer returns focus to the trigger."""
        assert "trigger.focus()" in self._app_js

    def test_aria_expanded_management(self):
        """JS toggles aria-expanded on open/close."""
        js = self._app_js
        assert "aria-expanded" in js
        assert '"true"' in js
        assert '"false"' in js

    def test_toggle_uses_document_delegation(self):
        """Toggle click is delegated on document so it survives OOB swaps."""
        js = self._app_js
        assert 'e.target.id === "drawer-toggle"' in js

    def test_sync_drawer_state_exists(self):
        """syncDrawerState re-applies drawer state after htmx swaps."""
        js = self._app_js
        assert "syncDrawerState" in js
        assert "htmx:afterSwap" in js

    def test_drawer_state_tracked(self):
        """drawerOpen variable persists toggle state across swaps."""
        assert "drawerOpen" in self._app_js


# ---------------------------------------------------------------------------
# Template accessibility attributes.
# ---------------------------------------------------------------------------


class TestTemplateAccessibility:
    """Templates expose the required ARIA/disclosure attributes (U17)."""

    def _adventure_html(self, saves_dir: Path) -> str:
        _create_save(saves_dir, theme_pack="scifi")
        with _get_client(saves_dir) as client:
            resp = client.get("/adventure/Hero")
        return resp.text

    def test_spine_has_aria_live(self, tmp_path: Path):
        html = self._adventure_html(tmp_path / "saves")
        assert 'aria-live="polite"' in html

    def test_drawer_has_role_region(self, tmp_path: Path):
        html = self._adventure_html(tmp_path / "saves")
        assert 'role="region"' in html
        assert "aria-label" in html

    def test_drawer_toggle_has_aria_expanded(self, tmp_path: Path):
        html = self._adventure_html(tmp_path / "saves")
        assert "aria-expanded" in html
        assert 'aria-controls="drawer"' in html

    def test_drawer_has_close_button(self, tmp_path: Path):
        html = self._adventure_html(tmp_path / "saves")
        assert "drawer-close" in html
        assert 'aria-label="Close drawer"' in html

    def test_drawer_tabs_have_aria_label(self, tmp_path: Path):
        html = self._adventure_html(tmp_path / "saves")
        assert 'aria-label="Detail categories"' in html


# ---------------------------------------------------------------------------
# U8: SSE narration and guided-retry client wiring — static JS + template checks.
# ---------------------------------------------------------------------------


class TestNarrationClientJS:
    """U8: static checks on app.js for the SSE narration + retry client."""

    @property
    def _app_js(self) -> str:
        return (_STATIC_DIR / "app.js").read_text()

    def test_eventsource_used_for_narration(self):
        """Vanilla EventSource opens the narration GET stream."""
        js = self._app_js
        assert "EventSource" in js
        assert "/narration" in js

    def test_fetch_used_for_retry(self):
        """Retry uses fetch POST with a stream reader (not EventSource)."""
        js = self._app_js
        assert "fetch" in js
        assert "/retry" in js
        assert "getReader" in js

    def test_spine_target_filter(self):
        """Narration fires only for htmx swaps whose target is #spine."""
        js = self._app_js
        assert '"spine"' in js
        assert "e.detail" in js or "detail.target" in js

    def test_single_live_source(self):
        """At most one live EventSource — existing source closed before opening."""
        js = self._app_js
        assert "narrationSource" in js
        assert "closeNarration" in js
        assert ".close()" in js

    def test_close_on_done_or_error(self):
        """EventSource is closed when done or error blocks arrive."""
        js = self._app_js
        assert '"done"' in js
        assert '"error"' in js
        assert "closeNarration" in js

    def test_receipt_blocks_skipped_client_side(self):
        """Receipt blocks are skipped — already in the POST fragment."""
        js = self._app_js
        assert "receipt" in js

    def test_llm_configured_check(self):
        """Retry control hidden unless data-llm-configured is 'true'."""
        js = self._app_js
        assert "data-llm-configured" in js
        assert '"true"' in js

    def test_retry_cap_enforced_client_side(self):
        """Client-side cap mirrors MAX_RETRIES_PER_BEAT (3)."""
        js = self._app_js
        assert "MAX_RETRIES" in js
        assert "3" in js

    def test_retry_attempt_resets_on_action_swap(self):
        """Attempt counter resets when a new action swap hits #spine."""
        js = self._app_js
        assert "retryAttempt = 0" in js

    def test_retry_steering_text_sent(self):
        """Retry POST body includes steering_text and attempt fields."""
        js = self._app_js
        assert "steering_text" in js
        assert "attempt" in js

    def test_block_renderer_handles_all_types(self):
        """Block renderer produces elements for each typed block."""
        js = self._app_js
        assert "narration-block" in js
        assert "change-block" in js
        assert "badge-block" in js
        assert "divider-block" in js
        assert "error-block" in js


class TestNarrationRegionTemplate:
    """U8: narration region and LLM data attribute in the adventure template."""

    def test_narration_stream_region_exists(self, tmp_path: Path):
        """The #narration-stream region exists in the rendered adventure page."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir, theme_pack="scifi")
        with _get_client(saves_dir) as client:
            resp = client.get("/adventure/Hero")
        assert 'id="narration-stream"' in resp.text

    def test_llm_configured_attribute_present(self, tmp_path: Path):
        """The body tag carries data-llm-configured with a boolean value."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir, theme_pack="scifi")
        with _get_client(saves_dir) as client:
            resp = client.get("/adventure/Hero")
        assert "data-llm-configured" in resp.text
        # Must be either 'true' or 'false' — not empty or unrendered.
        assert (
            'data-llm-configured="true"' in resp.text or 'data-llm-configured="false"' in resp.text
        )

    def test_narration_region_in_fragment_too(self, tmp_path: Path):
        """The narration region appears in POST fragment responses (inside spine)."""
        saves_dir = tmp_path / "saves"
        _create_save(saves_dir, theme_pack="scifi")
        with _get_client(saves_dir) as client:
            resp = client.post(
                "/adventure/Hero/action",
                data={"choice": ""},
                headers={"Origin": "http://127.0.0.1"},
            )
        assert 'id="narration-stream"' in resp.text


class TestNarrationCSS:
    """U8: typed-block CSS styles exist for the narration region."""

    @property
    def _app_css(self) -> str:
        return (_STATIC_DIR / "app.css").read_text()

    def test_narration_stream_style_exists(self):
        assert "#narration-stream" in self._app_css

    def test_narration_block_style_exists(self):
        assert ".narration-block" in self._app_css

    def test_badge_block_style_exists(self):
        assert ".badge-block" in self._app_css

    def test_change_block_style_exists(self):
        assert ".change-block" in self._app_css

    def test_divider_block_style_exists(self):
        assert ".divider-block" in self._app_css

    def test_error_block_style_exists(self):
        assert ".error-block" in self._app_css

    def test_retry_control_style_exists(self):
        assert ".retry-control" in self._app_css

    def test_retry_disabled_style_exists(self):
        assert ".retry-disabled" in self._app_css
