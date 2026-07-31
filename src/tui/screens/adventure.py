"""Adventure screen — scene display, structured options, free-text input (U7).

Three-panel layout matching the lifepath screen: character sheet sidebar,
scrolling narrative log, and choice menu at the bottom. The adventure screen
adds:

- Scene scaffold display (oracle-derived focus, situation, NPC hints).
- Structured options (2-4 pre-mapped checks) + a free-text input slot.
- Free-text classification display: the interpreted check is shown to the
  player before resolution. Player may accept, reject to rephrase, or fall
  back to a structured option (AE5).

Phase flow::

    hook_offered -> hook_decision (accept/refuse)
    -> scene_active (scaffold + options)
    -> resolving (check resolution + consequences)
    -> mission_active (next scene or resolve)
    -> back to hook_offered

Phase state is reconstructable from GameState (AE8).
"""

from __future__ import annotations

from typing import ClassVar

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Input, Label, OptionList

from src.engine.death import DefeatContext, get_death_strategy
from src.engine.mission import Mission, MissionEnding, MissionEngine
from src.engine.scene import SceneCheckResult, SceneEngine
from src.engine.skills import skill_display_name
from src.engine.state import Injury
from src.llm.state_view import build_curated_view_for_scene
from src.tui.widgets.character_sheet import CharacterSheetWidget
from src.tui.widgets.choice_menu import ChoiceMenuWidget
from src.tui.widgets.narrative_log import NarrativeLogWidget

#: Degraded-mode status surfaces (Task 24 — plan wording).
STATUS_NARRATION_UNAVAILABLE = "narration unavailable — showing mechanical outcomes"
STATUS_CONNECTION_LOST = "connection lost — template narration"


class AdventureScreen(Screen):
    """Three-panel adventure screen with scene display and free-text input.

    Layout::

        +-----------+-------------------+
        | Character | Narrative Log     |
        | Sheet     |                   |
        |           +-------------------+
        |           | Status / Input    |
        +-----------+-------------------+
        | Choice Menu / Options         |
        +-------------------------------+

    Tab/Shift-Tab cycles focus between panels. Number keys 1-9 select
    structured options. Enter submits free-text input.
    """

    CSS = """
    AdventureScreen {
        layout: vertical;
    }
    #adv-main-area {
        height: 1fr;
    }
    #adv-char-sheet {
        width: 28;
        height: 100%;
    }
    #adv-content-area {
        width: 1fr;
        height: 100%;
    }
    #adv-narrative-log {
        height: 1fr;
    }
    #adv-status-bar {
        height: 1;
        background: $boost;
        color: $text-muted;
        padding: 0 1;
    }
    #adv-input {
        height: 3;
        border: round $accent;
        padding: 0 1;
    }
    #adv-choice-menu {
        height: 9;
    }
    AdventureScreen.narrow #adv-char-sheet { display: none; }
    AdventureScreen.narrow.show-sheet #adv-char-sheet { display: block; width: 100%; height: 40%; }
    AdventureScreen.narrow.show-sheet #adv-content-area { height: 1fr; }
    AdventureScreen.narrow.show-sheet #adv-main-area { layout: vertical; }
    AdventureScreen.short #adv-choice-menu { height: 6; }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("tab", "focus_next", "Next panel"),
        Binding("shift+tab", "focus_previous", "Prev panel"),
        Binding("c", "toggle_sheet", "Char sheet"),
        Binding("pageup", "scroll_log_up", "Log up", show=False),
        Binding("pagedown", "scroll_log_down", "Log down", show=False),
        Binding("home", "scroll_log_home", "Log top", show=False),
        Binding("end", "scroll_log_end", "Log end", show=False),
    ]

    #: Phase state machine — always_update so refreshes happen on re-entry.
    phase = reactive("init", always_update=True)
    _mounted = False

    # Transient adventure state. ``None`` means "not live": hooks are
    # generated on demand in ``_offer_hook`` and scenes in ``_present_scene``
    # only when the corresponding slot is empty, so re-entering a phase
    # (``always_update``) never discards live content.
    _current_hook = None
    _current_scene = None
    _current_mission = None
    _pending_freetext = None
    _freetext_draft: str | None = None
    #: LLM adapter — None when no LLM is configured (template-only mode).
    _adapter = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="adv-main-area"):
            yield CharacterSheetWidget(id="adv-char-sheet")
            with Vertical(id="adv-content-area"):
                yield NarrativeLogWidget(id="adv-narrative-log")
                yield Label(
                    "[dim]Adventure mode — no LLM connected[/dim]",
                    id="adv-status-bar",
                )
        yield ChoiceMenuWidget(id="adv-choice-menu")
        yield Input(
            placeholder="Or type your own action and press Enter...",
            id="adv-input",
        )
        yield Footer()

    def on_mount(self) -> None:
        """Initialize: show character sheet, resume context, set phase."""
        self._adapter = self.app.create_llm_adapter()
        self._update_character_sheet()
        self._reconstruct_mission_if_needed()
        self._show_adventure_context()
        self._update_status_bar()
        self.phase = self._determine_phase()
        # Focus the choice menu for immediate interaction.
        self.query_one(ChoiceMenuWidget).option_list.focus()
        self._mounted = True
        self.call_after_refresh(self._apply_responsive_layout)

    def on_resize(self, event) -> None:
        """Re-evaluate layout when terminal is resized."""
        if self._mounted:
            self._apply_responsive_layout()

    def _apply_responsive_layout(self) -> None:
        """Toggle CSS classes based on terminal dimensions."""
        w, h = self.size.width, self.size.height
        if w < 100:
            self.add_class("narrow")
        else:
            self.remove_class("narrow")
            self.remove_class("show-sheet")
        if h < 24:
            self.add_class("short")
        else:
            self.remove_class("short")

    def action_toggle_sheet(self) -> None:
        """Toggle the character sheet on narrow terminals."""
        if self.has_class("narrow"):
            self.toggle_class("show-sheet")

    def _reconstruct_mission_if_needed(self) -> None:
        """Reconstruct ``_current_mission`` from ``state.active_mission`` on resume.

        On resume from save where ``state.active_mission`` is not None, the
        in-memory ``_current_mission`` was never set (it is only set in
        ``_do_accept_mission``). Without reconstruction, ``_do_resolve_mission``
        crashes with ``AttributeError``.
        """
        if not hasattr(self, "_current_mission") or self._current_mission is None:
            state = self.app.engine.state
            if state.active_mission is not None:
                self._current_mission = Mission.from_dict(state.active_mission)

    # ------------------------------------------------------------------
    # Phase determination — fully reconstructable from GameState (AE8).
    # ------------------------------------------------------------------

    def _determine_phase(self) -> str:
        """Determine the current adventure phase from engine state."""
        state = self.app.engine.state

        # No active mission: offer a hook.
        if state.active_mission is None:
            return "hook_offered"

        # Active mission: playing scenes.
        return "scene_active"

    def _show_adventure_context(self) -> None:
        """Show adventure context on entry or resume."""
        state = self.app.engine.state
        char = state.character

        self._narrate("=== Adventure Mode ===")

        if char.name:
            self._narrate(f"Character: {char.name}")

        if state.active_mission:
            mission = state.active_mission
            hook = mission.get("hook", {})
            self._narrate(
                f"Active mission: {hook.get('patron', 'Unknown patron')} — "
                f"{hook.get('objective', 'Unknown objective')}"
            )
        else:
            self._narrate("No active mission. Seeking opportunities...")

    # ------------------------------------------------------------------
    # Reactive watcher — updates choices whenever phase changes.
    # ------------------------------------------------------------------

    def watch_phase(self, old_phase: str, new_phase: str) -> None:
        """Refresh the choice menu when phase changes."""
        self._update_choices()

    # ------------------------------------------------------------------
    # Choice management.
    # ------------------------------------------------------------------

    def _update_choices(self) -> None:
        """Populate the choice menu based on current phase."""
        if self.phase == "hook_offered":
            self._offer_hook()
        elif self.phase == "scene_active":
            self._present_scene()

    # ------------------------------------------------------------------
    # Hook phase.
    # ------------------------------------------------------------------

    def _offer_hook(self) -> None:
        """Display the current mission hook, generating one if none is live.

        Generation happens only when ``_current_hook`` is empty — re-entering
        ``hook_offered`` (e.g. after a refusal) re-displays the live hook
        instead of rolling a second, discarded one.
        """
        if self._current_hook is None:
            mission_engine = self._get_mission_engine()
            self._current_hook = mission_engine.generate_hook()

        self._narrate("--- Mission Hook ---")
        self._narrate(f"Patron: {self._current_hook.patron}")
        self._narrate(f"Objective: {self._current_hook.objective}")
        self._narrate(f"Complication: {self._current_hook.complication}")
        self._narrate(f"Reward: {self._current_hook.reward}")

        cm = self.query_one(ChoiceMenuWidget)
        cm.set_choices(
            "A patron approaches with a job:",
            [
                ("Accept Mission", "accept_mission"),
                ("Refuse — Look for Another Job", "refuse_mission"),
            ],
        )

    def _do_accept_mission(self) -> None:
        """Accept the current hook and enter scene play."""
        mission_engine = self._get_mission_engine()
        self._current_mission = mission_engine.accept_mission(self._current_hook)
        # The hook is consumed and the next scene must be freshly generated.
        self._current_hook = None
        self._current_scene = None
        self._narrate("Mission accepted. The adventure begins!")
        self._post_step()
        self.phase = "scene_active"

    def _do_refuse_mission(self) -> None:
        """Refuse the hook; the engine generates a replacement (R23)."""
        mission_engine = self._get_mission_engine()
        self._current_hook = mission_engine.refuse_mission()
        self._narrate("You decline. Another opportunity arises...")
        self._post_step()
        # Stay in hook_offered; _offer_hook displays the replacement hook
        # (it does not generate a second one).
        self.phase = "hook_offered"

    # ------------------------------------------------------------------
    # Scene phase.
    # ------------------------------------------------------------------

    def _present_scene(self) -> None:
        """Generate and present a scene with options.

        Re-entry with a live scene (e.g. after the player rejects a free-text
        interpretation) re-displays the current scene's options instead of
        generating a replacement scene and checkpoint snapshot. Callers that
        want the next scene beat clear ``_current_scene`` before assigning
        ``phase = "scene_active"``.
        """
        if self._current_scene is None:
            # Take a checkpoint snapshot at scene start (F4 cycle) for
            # checkpoint death mode (AE3).
            state = self.app.engine.state
            if state.campaign.death_mode == "checkpoint":
                self.app.checkpoint_mgr.take_snapshot(state)

            scene_engine = self._get_scene_engine()
            self._current_scene = scene_engine.run_scene()
            scaffold = self._current_scene.scaffold

            self._narrate("--- New Scene ---")
            self._narrate(f"Focus: {scaffold.focus} — {scaffold.focus_description}")
            self._narrate(f"Situation: {scaffold.situation}")
            if scaffold.npc_hint:
                self._narrate(f"NPC: {scaffold.npc_hint}")

        # Build choice list from the current scene's options (new or live).
        cm = self.query_one(ChoiceMenuWidget)
        pack = self.app.pack
        choices = [
            (
                f"{i + 1}. {opt.label} ({skill_display_name(pack, opt.skill)}, {opt.difficulty})",
                f"option:{i}",
            )
            for i, opt in enumerate(self._current_scene.options)
        ]
        # Task 19: progress-gated ending options replace the single
        # "Resolve Mission" button. "Push for the ending" only appears once
        # the player has cleared the hook's min_scenes gate; "Abandon the
        # mission" is always offered (player agency).
        mission = self.app.engine.state.active_mission or {}
        scenes_done = int(mission.get("scenes_completed", 0))
        min_scenes = int(mission.get("min_scenes", 3))
        if scenes_done >= min_scenes:
            choices.append(("Push for the ending", "push_for_ending"))
        else:
            self._narrate(
                f"[dim](Progress: {scenes_done}/{min_scenes} scenes — "
                "resolve unlocks at the target.)[/dim]"
            )
        choices.append(("Abandon the mission", "abandon_mission"))
        cm.set_choices("Choose your action:", choices)

    def _do_resolve_option(self, option_index: int) -> None:
        """Resolve the selected structured option."""
        scene_engine = self._get_scene_engine()
        option = self._current_scene.options[option_index]

        self._narrate(f"You attempt: {option.label}")
        check_result = scene_engine.resolve_scene(self._current_scene.scaffold, option)

        self._narrate(self._mechanics_line(check_result))

        # Apply consequences.
        consequences = scene_engine.apply_consequences(check_result, self._current_scene.scaffold)
        for c in consequences:
            self._narrate(f"  -> {c}")

        # Check for defeat (F5): life-threatening MISS or severe injury.
        if self._check_and_handle_defeat(check_result, option, consequences):
            return  # Defeat handled; phase already updated.

        # Task 24: stream scene narration via LLM or template.
        self._narrate_scene_result(check_result, option, consequences)

        self._post_step()
        # Move to the next scene beat: clear the live scene so re-entering
        # scene_active generates a fresh one.
        self._current_scene = None
        self.phase = "scene_active"

    def _do_push_for_ending(self) -> None:
        """Push for the ending: a final check decides success vs. failure.

        Task 19: the player may only attempt this once ``scenes_completed``
        has reached ``min_scenes``. The current scene's first option is the
        ending check — a strong or weak hit resolves the mission as SUCCESS;
        a MISS resolves it as FAILURE. Consequences come from the mission
        hook's pack-supplied ending text (not hardcoded).
        """
        scene_engine = self._get_scene_engine()
        mission_engine = self._get_mission_engine()
        mission = self._current_mission

        # Use the current scene's first option as the climactic check.
        # If there's no live scene (e.g. entry via a saved mid-mission
        # state), generate one so the ending still rolls dice.
        if self._current_scene is None:
            self._current_scene = scene_engine.run_scene()
        option = self._current_scene.options[0]
        scaffold = self._current_scene.scaffold

        self._narrate(f"=== Pushing for the ending: {option.label} ===")
        check_result = scene_engine.resolve_scene(scaffold, option)
        self._narrate(self._mechanics_line(check_result))

        from src.rulesets.base import OutcomeQuality

        if check_result.quality in (OutcomeQuality.STRONG_HIT.value, OutcomeQuality.WEAK_HIT.value):
            ending = MissionEnding.SUCCESS
            ending_text = mission.success_text
        else:
            ending = MissionEnding.FAILURE
            ending_text = mission.failure_text

        # Consequences: pack-supplied ending text first, then any mechanical
        # consequences the scene engine produced (injuries, etc.).
        consequences: list[str] = []
        if ending_text:
            consequences.append(ending_text)
        scene_consequences = scene_engine.apply_consequences(check_result, scaffold)
        for c in scene_consequences:
            self._narrate(f"  -> {c}")
        # Defeat check (life-threatening miss / severe injury) takes priority
        # over the mission ending narration if it triggers.
        if self._check_and_handle_defeat(check_result, option, scene_consequences):
            return

        mission_engine.resolve_mission(mission, ending, consequences)

        for c in consequences:
            self._narrate(f"  -> {c}")
        self._narrate(f"Mission resolved: {ending.value}.")
        self._current_scene = None
        self._current_hook = None
        self._post_step()
        self.phase = "hook_offered"

    def _do_abandon_mission(self) -> None:
        """Abandon the active mission (always allowed; player agency).

        Task 19: abandonment bypasses the min_scenes gate. Consequences
        come from the mission hook's ``abandonment_text`` if the pack
        supplies one.
        """
        mission_engine = self._get_mission_engine()
        mission = self._current_mission

        consequences: list[str] = []
        if mission.abandonment_text:
            consequences.append(mission.abandonment_text)

        mission_engine.resolve_mission(mission, MissionEnding.ABANDONMENT, consequences)

        for c in consequences:
            self._narrate(f"  -> {c}")
        self._narrate("Mission abandoned. Looking for the next opportunity...")
        self._current_scene = None
        self._current_hook = None
        self._post_step()
        self.phase = "hook_offered"

    # ------------------------------------------------------------------
    # Defeat detection and handling (F5, R8).
    # ------------------------------------------------------------------

    def _check_and_handle_defeat(
        self,
        check_result,
        option,
        consequences: list[str],
    ) -> bool:
        """Detect catastrophic outcomes and invoke the death strategy (F5).

        Triggers defeat when:
        - The check result is a MISS on a life-threatening action, OR
        - A severe injury was applied as a consequence.

        When defeat is triggered, invokes the appropriate death strategy via
        ``get_death_strategy`` and applies the result. Returns ``True`` if
        defeat was handled (caller should skip the normal post-step).
        """
        from src.rulesets.base import OutcomeQuality

        is_defeat = False
        reason = ""

        # Condition 1: MISS on a life-threatening check.
        if check_result.quality == OutcomeQuality.MISS.value and getattr(
            option, "life_threatening", False
        ):
            is_defeat = True
            reason = f"a failed life-threatening {skill_display_name(self.app.pack, check_result.skill)} check"

        # Condition 2: severe injury applied as a consequence.
        if not is_defeat:
            state = self.app.engine.state
            has_severe = any(
                isinstance(e, Injury) and e.severity == "severe" for e in state.entities
            )
            # Check if a severe injury was just added in this consequence.
            if (
                has_severe
                and check_result.quality == OutcomeQuality.MISS.value
                and any("severe" in c.lower() or "serious" in c.lower() for c in consequences)
            ):
                is_defeat = True
                reason = f"accumulated severe injuries during {skill_display_name(self.app.pack, check_result.skill)}"

        if not is_defeat:
            return False

        return self._handle_defeat(reason)

    def _handle_defeat(self, reason: str) -> bool:
        """Invoke the death strategy and apply the defeat result (F5, R8).

        Constructs the appropriate :class:`DeathStrategy` via
        :func:`get_death_strategy`, routes mutations through the funnel when
        possible, narrates the outcome, and updates the phase.

        Returns ``True`` to signal the caller that defeat was handled.
        """
        state = self.app.engine.state
        death_mode = state.campaign.death_mode

        checkpoint_mgr = self.app.checkpoint_mgr
        strategy = get_death_strategy(
            death_mode,
            checkpoint=checkpoint_mgr,
            engine=self.app.engine,
        )
        context = DefeatContext(
            reason=reason,
            scene_label=getattr(self._current_scene.scaffold, "focus", "unknown"),
        )
        result = strategy.handle_defeat(state, context)

        self._narrate(f"=== DEFEAT ({death_mode}) ===")
        self._narrate(result.message)

        if result.restored_state is not None:
            # Checkpoint mode: swap in the restored state. swap_state also
            # rebinds the engine's LiveRoller to the restored RNG streams —
            # otherwise post-rewind rolls would advance the abandoned
            # branch's streams and break determinism (AE3).
            self.app.engine.swap_state(result.restored_state)

        # The scene that produced the defeat is over; the next scene beat
        # (a replay of scene start after checkpoint restore) generates fresh.
        self._current_scene = None

        if not result.play_continues:
            # Ironman: character is dead. Offer restart via hook phase.
            self._update_character_sheet()
            self._post_step()
            self.phase = "hook_offered"
        else:
            # Checkpoint or Narrative: play continues.
            self._update_character_sheet()
            self._post_step()
            self.phase = "scene_active"

        return True

    # ------------------------------------------------------------------
    # Free-text input handling (AE5).
    # ------------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle free-text input submission (AE5).

        The LLM (or template classifier) interprets the free text into an
        engine-known check. The interpreted check is shown to the player
        for confirmation before resolution.
        """
        if event.input.id != "adv-input":
            return

        text = event.value.strip()
        if not text:
            return

        # Only process free-text during scene phase.
        if self.phase != "scene_active":
            self._narrate("Free-text is only available during scenes.")
            event.input.value = ""
            return

        scene_engine = self._get_scene_engine()
        classification = scene_engine.classify_freetext(
            text,
            self._current_scene.scaffold,
            llm_classifier=self._make_llm_classifier(),
        )

        if classification is None:
            # Escape user text: the log renders Rich markup, and raw input
            # like "[/]" would otherwise crash with a MarkupError.
            self._narrate(
                f"Could not interpret '{escape(text)}'. "
                "Try rephrasing or select a structured option."
            )
            event.input.value = ""
            return

        # Show the interpreted check to the player (AE5).
        check = classification.interpreted_check
        pack = self.app.pack
        self._narrate(
            f"Interpreted as: {check.label} (skill: {skill_display_name(pack, check.skill)}, "
            f"difficulty: {check.difficulty})"
        )

        # Offer accept/reject choices.
        cm = self.query_one(ChoiceMenuWidget)
        cm.set_choices(
            "Confirm interpreted action:",
            [
                ("Accept — Proceed with this check", "accept_freetext"),
                ("Reject — Rephrase or pick an option", "reject_freetext"),
            ],
        )

        # Store the interpreted check for resolution. Preserve the typed text
        # so a rejection can restore it for rephrasing (Task 20).
        self._pending_freetext = check
        self._freetext_draft = text
        event.input.value = ""

    def _do_accept_freetext(self) -> None:
        """Accept the interpreted free-text check and resolve it."""
        scene_engine = self._get_scene_engine()
        option = self._pending_freetext

        self._narrate(f"You attempt: {option.label}")
        check_result = scene_engine.resolve_scene(self._current_scene.scaffold, option)
        self._narrate(self._mechanics_line(check_result))

        consequences = scene_engine.apply_consequences(check_result, self._current_scene.scaffold)
        for c in consequences:
            self._narrate(f"  -> {c}")

        self._pending_freetext = None
        self._freetext_draft = None

        # Check for defeat (F5): life-threatening MISS or severe injury.
        if self._check_and_handle_defeat(check_result, option, consequences):
            return  # Defeat handled; phase already updated.

        # Task 24: stream scene narration via LLM or template.
        self._narrate_scene_result(check_result, option, consequences)

        self._post_step()
        # Move to the next scene beat (fresh scene on phase re-entry).
        self._current_scene = None
        self.phase = "scene_active"

    def _do_reject_freetext(self) -> None:
        """Reject the interpreted check; return to the SAME scene's options.

        The live scene is kept, so re-entering scene_active re-displays its
        structured options rather than generating a replacement scene.
        The typed free-text is restored into the Input for rephrasing and the
        Input is focused (Task 20).
        """
        self._narrate("Interpretation rejected. Choose an option or rephrase.")
        self._pending_freetext = None
        # Restore the typed text for rephrasing and focus the input.
        inp = self.query_one("#adv-input", Input)
        if self._freetext_draft is not None:
            inp.value = self._freetext_draft
        inp.focus()
        self.phase = "scene_active"

    # ------------------------------------------------------------------
    # Event handlers.
    # ------------------------------------------------------------------

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Dispatch choice selection to the appropriate handler."""
        option_id = event.option.id
        if option_id is None:
            return

        if option_id == "accept_mission":
            self._do_accept_mission()
        elif option_id == "refuse_mission":
            self._do_refuse_mission()
        elif option_id == "push_for_ending":
            self._do_push_for_ending()
        elif option_id == "abandon_mission":
            self._do_abandon_mission()
        elif option_id == "accept_freetext":
            self._do_accept_freetext()
        elif option_id == "reject_freetext":
            self._do_reject_freetext()
        elif option_id.startswith("option:"):
            idx = int(option_id.split(":", 1)[1])
            self._do_resolve_option(idx)

    # ------------------------------------------------------------------
    # Scene narration (Task 24 — LLM or template).
    # ------------------------------------------------------------------

    def _narrate_scene_result(self, check_result, option, consequences) -> None:
        """Dispatch scene narration to LLM (async worker) or template (sync).

        On LLM failure, sets the status bar to the appropriate degraded-mode
        surface string so the player understands why the narration changed.
        """
        if self._adapter is None:
            return  # No LLM — mechanical outcomes already narrated.

        scaffold = self._current_scene.scaffold
        outcome_facts = [
            f"Action: {option.label}",
            f"Skill: {check_result.skill} ({check_result.quality}, effect {check_result.effect:+d})",
        ] + [f"Consequence: {c}" for c in consequences]

        self.run_worker(self._narrate_scene_async(scaffold, outcome_facts))

    async def _narrate_scene_async(self, scaffold, outcome_facts: list[str]) -> None:
        """Worker: fetch scene narration from the LLM, display it."""
        if not self._mounted or self.app.engine is None:
            return
        try:
            state = self.app.engine.state
            view = build_curated_view_for_scene(
                state,
                [scaffold.focus_description, scaffold.situation],
            )
            result = await self._adapter.narrate_scene(scaffold, outcome_facts, view)
            if result.prose:
                self._narrate(result.prose)
            if result.llm_failed:
                self._update_status_bar(result.failure_kind)
        except Exception:
            # Never raise from narration — template outcomes already shown.
            pass

    def _make_llm_classifier(self):
        """Build a sync classifier closure for SceneEngine.classify_freetext.

        Captures the adapter, state, and pack to provide the view and
        valid_skill_ids the adapter needs. Returns ``None`` when no adapter
        is configured.
        """
        if self._adapter is None:
            return None
        adapter = self._adapter
        state = self.app.engine.state
        pack = self.app.pack

        def classifier(text: str, scaffold):
            view = build_curated_view_for_scene(
                state,
                [scaffold.focus_description, scaffold.situation],
                text,
            )
            valid_skill_ids = set(pack.skills.keys())
            return adapter.classify_freetext(text, scaffold, view, valid_skill_ids)

        return classifier

    # ------------------------------------------------------------------
    # UI helpers.
    # ------------------------------------------------------------------

    def _mechanics_line(self, result: SceneCheckResult) -> str:
        """Build the inline mechanics line from a check result (Task 20).

        Format::

            2D6 [4, 2] = 6  DM +2 → 8 vs 8 — <tier> (Effect +0)

        Classic profile labels the tier as ``Success``/``Failure`` (binary);
        narrative profile uses ``Strong hit``/``Weak hit``/``Miss`` (PbtA).
        An untrained check appends ``(untrained)``.
        """
        dice = ", ".join(str(d) for d in result.dice)
        raw = result.raw_roll
        total = raw + result.total_dm
        profile = self.app.engine.state.campaign.resolution_profile
        if profile == "classic":
            tier = "Success" if result.success else "Failure"
        else:
            tier = {
                "strong_hit": "Strong hit",
                "weak_hit": "Weak hit",
                "miss": "Miss",
            }[result.quality]
        trained_note = "" if result.trained else " (untrained)"
        return (
            f"2D6 [{dice}] = {raw}  DM {result.total_dm:+d} → {total} "
            f"vs 8 — {tier} (Effect {result.effect:+d}){trained_note}"
        )

    def _narrate(self, text: str) -> None:
        """Add a line to the narrative log."""
        self.query_one(NarrativeLogWidget).add_line(text)

    def _update_status_bar(self, failure_kind: str | None = None) -> None:
        """Update the status bar to reflect LLM state (Task 24).

        On normal operation shows the connected model or template mode.
        On narration failure, shows the degraded-mode surface matching the
        failure kind.
        """
        from textual.widgets import Label

        bar = self.query_one("#adv-status-bar", Label)
        if failure_kind == "provider_error":
            bar.update(f"[yellow]{STATUS_CONNECTION_LOST}[/yellow]")
            return
        if failure_kind == "retry_exhausted":
            bar.update(f"[yellow]{STATUS_NARRATION_UNAVAILABLE}[/yellow]")
            return
        if self._adapter is not None:
            provider = self.app.llm_settings.provider
            model = self.app.llm_settings.model
            bar.update(f"[green]LLM: {provider}/{model}[/green]")
        else:
            bar.update("[dim]Adventure mode — no LLM connected[/dim]")

    def _update_character_sheet(self) -> None:
        """Refresh the character sheet from engine state."""
        self.query_one(CharacterSheetWidget).update_from_state(self.app.engine.state)

    def _post_step(self) -> None:
        """Common post-step actions: update sheet, auto-save (AE8)."""
        self._update_character_sheet()
        self.app.save_game()

    # ------------------------------------------------------------------
    # Engine accessors.
    # ------------------------------------------------------------------

    def _get_mission_engine(self) -> MissionEngine:
        """Get or create a mission engine."""
        if not hasattr(self, "_mission_engine_cache") or self._mission_engine_cache is None:
            self._mission_engine_cache = MissionEngine(self.app.engine, self.app.pack)
        return self._mission_engine_cache

    def _get_scene_engine(self) -> SceneEngine:
        """Get or create a scene engine."""
        if not hasattr(self, "_scene_engine_cache") or self._scene_engine_cache is None:
            self._scene_engine_cache = SceneEngine(self.app.engine, self.app.pack)
        return self._scene_engine_cache

    # ------------------------------------------------------------------
    # Scroll actions for the narrative log.
    # ------------------------------------------------------------------

    def action_scroll_log_up(self) -> None:
        self.query_one(NarrativeLogWidget).scroll_page_up()

    def action_scroll_log_down(self) -> None:
        self.query_one(NarrativeLogWidget).scroll_page_down()

    def action_scroll_log_home(self) -> None:
        self.query_one(NarrativeLogWidget).scroll_home()

    def action_scroll_log_end(self) -> None:
        self.query_one(NarrativeLogWidget).scroll_end()

    # ------------------------------------------------------------------
    # Focus delegation.
    # ------------------------------------------------------------------

    def action_focus_next(self) -> None:
        self.app.action_focus_next()

    def action_focus_previous(self) -> None:
        self.app.action_focus_previous()
