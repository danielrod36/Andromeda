"""Tests for vendored fonts and @font-face declarations (U9, R15).

Covers:
- Each woff2 file exists, is non-empty, and has the woff2 magic bytes.
- ``tokens.css`` references every file in a @font-face block.
- Favicon link present in every full-page template.
- Material benefit events produce a positive change-line.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_FONTS_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "web" / "static" / "fonts"
_TOKENS_CSS = (
    Path(__file__).resolve().parent.parent.parent / "src" / "web" / "static" / "tokens.css"
)
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "web" / "templates"

#: The seven woff2 files we vendor from fontsource 5.3.0.
_EXPECTED_FONTS = [
    "literata-latin-400-normal.woff2",
    "literata-latin-700-normal.woff2",
    "literata-latin-400-italic.woff2",
    "ibm-plex-sans-latin-400-normal.woff2",
    "ibm-plex-sans-latin-700-normal.woff2",
    "ibm-plex-mono-latin-400-normal.woff2",
    "ibm-plex-mono-latin-700-normal.woff2",
]


class TestVendoredFonts:
    """U9: woff2 files exist, are valid, and referenced in CSS."""

    @pytest.mark.parametrize("filename", _EXPECTED_FONTS)
    def test_font_file_exists(self, filename: str):
        path = _FONTS_DIR / filename
        assert path.exists(), f"Missing font file: {filename}"

    @pytest.mark.parametrize("filename", _EXPECTED_FONTS)
    def test_font_file_non_empty(self, filename: str):
        path = _FONTS_DIR / filename
        assert path.stat().st_size > 100, f"Font file too small: {filename}"

    @pytest.mark.parametrize("filename", _EXPECTED_FONTS)
    def test_font_has_woff2_magic(self, filename: str):
        """Every woff2 file starts with the 'wOF2' magic bytes."""
        path = _FONTS_DIR / filename
        magic = path.read_bytes()[:4]
        assert magic == b"wOF2", f"Bad woff2 magic in {filename}: {magic!r}"

    @pytest.mark.parametrize("filename", _EXPECTED_FONTS)
    def test_font_referenced_in_tokens_css(self, filename: str):
        css = _TOKENS_CSS.read_text()
        assert filename in css, f"Font file {filename} not referenced in tokens.css"

    def test_font_face_blocks_present(self):
        """tokens.css has @font-face declarations for all three families."""
        css = _TOKENS_CSS.read_text()
        # Literata has three declarations (400, 700, italic-400).
        assert css.count("@font-face") >= 7
        assert '"Literata"' in css
        assert '"IBM Plex Sans"' in css
        assert '"IBM Plex Mono"' in css


class TestFaviconLink:
    """U9: every full-page template includes a favicon link to prevent 404."""

    @pytest.mark.parametrize(
        "template_name",
        [
            "menu.html",
            "config.html",
            "saves.html",
            "adventure.html",
            "lifepath.html",
            "memorial.html",
            "inspector.html",
        ],
    )
    def test_template_has_favicon(self, template_name: str):
        path = _TEMPLATES_DIR / template_name
        html = path.read_text()
        assert 'rel="icon"' in html, f"Missing favicon link in {template_name}"


class TestMaterialBenefitChangeLine:
    """U9: material benefit events produce a positive change-line (R16)."""

    def test_material_benefit_produces_positive_change_line(self):
        from src.engine.audit import Event, EventKind
        from src.game.change_lines import derive_change_line

        event = Event(
            seq=1,
            kind=EventKind.STATE_CHANGE,
            command_type="lifepath_benefit",
            description="material benefit",
            changes={
                "benefit_type": "material",
                "result_text": "Ship's boat",
            },
        )
        line = derive_change_line(event)
        assert line is not None
        assert "Ship's boat" in line.text
        assert line.css_class == "change-positive"

    def test_cash_benefit_still_produces_change_line(self):
        from src.engine.audit import Event, EventKind
        from src.game.change_lines import derive_change_line

        event = Event(
            seq=2,
            kind=EventKind.STATE_CHANGE,
            command_type="lifepath_benefit",
            description="cash benefit",
            changes={
                "benefit_type": "cash",
                "result_text": "Cr 50,000",
            },
        )
        line = derive_change_line(event)
        assert line is not None
        assert "Cr 50,000" in line.text
        assert line.css_class == "change-positive"

    def test_benefit_without_result_text_no_change_line(self):
        from src.engine.audit import Event, EventKind
        from src.game.change_lines import derive_change_line

        event = Event(
            seq=3,
            kind=EventKind.STATE_CHANGE,
            command_type="lifepath_benefit",
            description="empty benefit",
            changes={
                "benefit_type": "material",
                "result_text": "",
            },
        )
        assert derive_change_line(event) is None
