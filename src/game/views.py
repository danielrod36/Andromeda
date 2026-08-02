"""View models for the game flow layer (U5).

These are UI-agnostic data structures returned by the flow controllers.
The TUI renders them as Textual widgets; the web shell renders them as
Jinja templates. Neither layer needs to understand the other's rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChoiceOption:
    """A single selectable choice in a phase view.

    Attributes:
        label: Display text for the option.
        option_id: Stable identifier the flow layer uses to route selection.
        description: Optional secondary line (odds, requirements, etc.).
        dimmed: When True, the option is rule-gated and renders dimmed (U14).
        requirement: Human-readable reason for the gate (when dimmed).
    """

    label: str
    option_id: str
    description: str = ""
    dimmed: bool = False
    requirement: str = ""


@dataclass
class PhaseView:
    """A UI-agnostic snapshot of the current game phase (U5).

    The flow controller returns this after each step. Shells render it
    without needing to inspect GameState directly.

    Attributes:
        phase: The current phase identifier (e.g. "choose_career", "scene_active").
        prompt: Instructional text shown above the choices.
        choices: Selectable options for this phase.
        receipts: Engine receipt lines to display (dice rolls, outcomes).
        narration: LLM or template narration text (may be empty).
        ledger_cards: Compact term/milestone summaries for the spine.
        drawer_pinned: When True, the drawer should stay visible (lifepath assignment).
    """

    phase: str
    prompt: str = ""
    choices: list[ChoiceOption] = field(default_factory=list)
    receipts: list[str] = field(default_factory=list)
    narration: str = ""
    ledger_cards: list[str] = field(default_factory=list)
    drawer_pinned: bool = False
