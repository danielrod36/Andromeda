"""Character sheet sidebar widget — displays character stats and skills (R16)."""

from __future__ import annotations

from textual.widgets import Static

from src.engine.skills import skill_display_name
from src.engine.state import GameState, Injury
from src.themepacks.base import LoadedThemePack

_CHARACTERISTIC_ORDER = ("STR", "DEX", "END", "INT", "EDU", "SOC")


class CharacterSheetWidget(Static):
    """Sidebar panel showing the character sheet.

    Updated via :meth:`update_from_state` after every engine state change.
    Text labels are used alongside any colour coding so information is
    accessible without colour perception.
    """

    can_focus = True  # Allow Tab focus cycling between panels.

    DEFAULT_CSS = """
    CharacterSheetWidget {
        height: 1fr;
        border: round $primary;
        padding: 0 1;
        background: $surface;
        overflow-y: auto;
    }
    """

    def render_content(
        self,
        state: GameState | None = None,
        pack: LoadedThemePack | None = None,
    ) -> str:
        """Build the character sheet text from engine state.

        ``pack`` is used to render skill display names via
        :func:`skill_display_name`. When omitted, the widget falls back to
        ``self.app.pack`` if the widget is mounted; when no pack is available
        at all, skill ids are shown title-cased (the prior behavior).
        """
        if state is None:
            return "[dim]No character loaded.[/dim]"

        if pack is None:
            # Best-effort pack lookup; the widget may be rendered outside an
            # active app (tests, headless/web shell). NoActiveAppError is a
            # RuntimeError, so getattr's default does not catch it.
            try:
                pack = getattr(self.app, "pack", None)
            except Exception:
                pack = None

        char = state.character
        lines: list[str] = []

        # Header.
        name = char.name or "Unnamed"
        lines.append(f"[bold]{name}[/bold]")
        lines.append("")

        # Career and status.
        career_display = char.career.title() if char.career else "Unemployed"
        lines.append(f"Career: {career_display}")
        if char.rank > 0:
            lines.append(f"Rank: {char.rank}")
        lines.append(f"Age: {char.age}  Terms: {char.terms}")
        lines.append("")

        # Characteristics.
        lines.append("[bold]Characteristics[/bold]")
        for stat in _CHARACTERISTIC_ORDER:
            val = char.characteristics.get(stat)
            if val is not None:
                # Text label alongside colour: high = green, low = red.
                if val >= 9:
                    tag = " [green](strong)[/green]"
                elif val <= 5:
                    tag = " [red](weak)[/red]"
                else:
                    tag = ""
                lines.append(f"  {stat}: {val}{tag}")
            else:
                lines.append(f"  {stat}: --")
        lines.append("")

        # Skills — render via pack display names when available (FR1).
        if char.skills:
            lines.append("[bold]Skills[/bold]")
            for skill_id, level in sorted(char.skills.items()):
                label = (
                    skill_display_name(pack, skill_id)
                    if pack is not None
                    else skill_id.replace("_", " ").title()
                )
                lines.append(f"  {label}-{level}")
            lines.append("")

        # Status indicators.
        if not char.alive:
            lines.append("[bold red]DECEASED[/bold red]")

        # --- Load-bearing state the engine tracks but the prior sheet hid ---
        # (Phase 1 #2 / ADV-2 / TUI-2): Fallen London quality-sidebar pattern.
        injuries = [e for e in state.entities if isinstance(e, Injury)]
        if injuries:
            lines.append("")
            lines.append("[bold]Injuries[/bold]")
            for inj in injuries:
                color = "red" if inj.severity == "severe" else "yellow"
                lines.append(f"  [{color}]{inj.severity.title()}[/{color}] {inj.name}")

        # Resources: credits + inventory.
        if char.credits or char.inventory:
            lines.append("")
            lines.append("[bold]Resources[/bold]")
            lines.append(f"  Credits: {char.credits}")
            for item in char.inventory:
                lines.append(f"  • {item}")

        # Active mission + open threads — the player's current "why".
        mission_obj = state.active_mission or {}
        hook = mission_obj.get("hook") if isinstance(mission_obj, dict) else None
        if hook and isinstance(hook, dict):
            objective = hook.get("objective")
            if objective:
                scenes_done = int(mission_obj.get("scenes_completed", 0))
                min_scenes = int(mission_obj.get("min_scenes", 0))
                lines.append("")
                lines.append("[bold]Mission[/bold]")
                lines.append(f"  {objective}")
                if min_scenes:
                    lines.append(f"[dim]  Progress: {scenes_done}/{min_scenes} scenes[/dim]")

        if state.open_threads:
            lines.append("")
            lines.append(f"[bold]Open Threads ({len(state.open_threads)})[/bold]")
            for thread in state.open_threads:
                lines.append(f"  • {thread}")

        # Campaign info footer.
        campaign = state.campaign
        lines.append("")
        lines.append("[dim]── Campaign ──[/dim]")
        lines.append(f"[dim]Profile: {campaign.resolution_profile}[/dim]")
        lines.append(f"[dim]Death: {campaign.death_mode}[/dim]")

        return "\n".join(lines)

    def update_from_state(
        self,
        state: GameState | None = None,
        pack: LoadedThemePack | None = None,
    ) -> None:
        """Refresh the displayed character sheet from engine state."""
        self.update(self.render_content(state, pack=pack))
