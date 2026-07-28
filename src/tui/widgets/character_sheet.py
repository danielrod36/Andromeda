"""Character sheet sidebar widget — displays character stats and skills (R16)."""
from __future__ import annotations

from textual.widgets import Static

from src.engine.state import GameState

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

    def render_content(self, state: GameState | None = None) -> str:
        """Build the character sheet text from engine state."""
        if state is None:
            return "[dim]No character loaded.[/dim]"

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

        # Skills.
        if char.skills:
            lines.append("[bold]Skills[/bold]")
            for skill, level in sorted(char.skills.items()):
                label = skill.replace("_", " ").title()
                lines.append(f"  {label}-{level}")
            lines.append("")

        # Status indicators.
        if not char.alive:
            lines.append("[bold red]DECEASED[/bold red]")

        # Campaign info footer.
        campaign = state.campaign
        lines.append("")
        lines.append("[dim]── Campaign ──[/dim]")
        lines.append(f"[dim]Profile: {campaign.resolution_profile}[/dim]")
        lines.append(f"[dim]Death: {campaign.death_mode}[/dim]")

        return "\n".join(lines)

    def update_from_state(self, state: GameState | None = None) -> None:
        """Refresh the displayed character sheet from engine state."""
        self.update(self.render_content(state))
