"""Theme-pack theming resolution — neutral module (U17, R19).

Maps a campaign's ``theme_pack`` identifier to a CSS ``data-theme`` attribute
value.  Unknown or missing packs fall back to ``"scifi"`` (the default
palette defined in ``:root``).

Keeping this logic in ``src/game/`` (not in the web layer) follows KTD-7:
UX-feature logic lives in neutral modules that both shells can consume.
"""

from __future__ import annotations

#: Theme packs that have a token-set definition in ``tokens.css``.
KNOWN_THEMES: frozenset[str] = frozenset({"scifi", "fantasy"})

#: Fallback when the campaign's pack has no token definition.
DEFAULT_THEME: str = "scifi"


def resolve_theme_attr(theme_pack: str | None) -> str:
    """Return a valid ``data-theme`` value for *theme_pack*.

    Unknown, empty, or ``None`` packs return :data:`DEFAULT_THEME` so the
    page always gets a complete token set.
    """
    if theme_pack and theme_pack in KNOWN_THEMES:
        return theme_pack
    return DEFAULT_THEME
