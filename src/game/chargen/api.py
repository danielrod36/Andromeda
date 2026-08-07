"""ChargenSession API — the headless contract for the Godot client (P6).

CONTRACT_VERSION 1 (2026-08-06):
  create / current_choice / choose / suggest / propose / serialize / restore

Determinism: serialize+restore preserves the RNG stream byte-for-byte.
The LLM is NEVER re-invoked on restore — advice/proposal records live
in the event log and replay deterministically.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from src.engine.commands import Engine
from src.engine.lifepath_choices import ChoicePointView, choice_point_for_phase
from src.game.lifepath import LifepathController
from src.themepacks import get_pack

if TYPE_CHECKING:
    from src.llm.advisor import SuggestionRecord
    from src.llm.translator import TranslationRecord

CONTRACT_VERSION: int = 1


class StepResult(BaseModel):
    """Result of a choose/suggest/propose call (P6.T1).

    Every response from the session carries ``contract_version`` so a
    client can reject incompatible envelopes.
    """

    view: ChoicePointView | None = None
    receipts: list[str] = []
    completed: bool = False
    contract_version: int = CONTRACT_VERSION


class ChargenSession:
    """Headless character-creation session (P6).

    Wraps ``Engine`` + ``LifepathController`` and exposes the Part 2
    ``ChoicePointView`` surface. Advisor and translator are optional
    injected callables (A1 — no ``src.llm`` import in this module).
    """

    def __init__(
        self,
        engine: Engine,
        controller: LifepathController,
        *,
        advisor: object | None = None,
        translator: object | None = None,
    ) -> None:
        self._engine = engine
        self._controller = controller
        self._advisor = advisor
        self._translator = translator

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        seed: int,
        pack_id: str = "scifi",
        *,
        death_mode: str = "narrative",
        advisor: object | None = None,
        translator: object | None = None,
    ) -> ChargenSession:
        """Create a new chargen session from scratch (P6.T1)."""
        from src.engine.state import CampaignConfig, GameState

        pack = get_pack(pack_id)
        config = CampaignConfig(
            ruleset="cepheus",
            theme_pack=pack_id,
            resolution_profile="classic",
            death_mode=death_mode,
        )
        state = GameState.new(seed=seed, campaign=config)
        engine = Engine(state)
        controller = LifepathController(engine, pack)
        return cls(engine, controller, advisor=advisor, translator=translator)

    # ------------------------------------------------------------------
    # Read current state
    # ------------------------------------------------------------------

    def current_choice(self) -> ChoicePointView:
        """Return the current decision point (P6.T1).

        Maps the controller's phase to a Part 2 ``ChoicePointView``.
        """
        phase = self._controller.determine_phase()
        return choice_point_for_phase(
            phase,
            self._engine.state,
            self._controller.pack,
            self._controller.runner.ruleset,
        )

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def choose(self, option_id: str, *, origin: str = "player") -> StepResult:
        """Apply a selection (player, advisor-confirmed, or freetext) (P6.T1).

        Raises ``ValueError`` if the option is not valid for the current phase.
        """
        choice = self.current_choice()
        valid_ids = {o.option_id for o in choice.options}
        if option_id not in valid_ids:
            raise ValueError(
                f"Invalid option '{option_id}' for phase '{choice.phase}'. "
                f"Valid: {sorted(valid_ids)}"
            )
        self._controller.apply_choice(option_id, origin=origin)
        return self._step_result()

    # ------------------------------------------------------------------
    # Advisor / Translator (P6.T2)
    # ------------------------------------------------------------------

    async def suggest(self) -> SuggestionRecord:
        """Get an advisor suggestion for the current choice (P6.T2, A2).

        Records the advice via ``record_advice`` (funnel Command) so it
        replays deterministically. Raises ``RuntimeError`` if no advisor.
        """
        if self._advisor is None:
            raise RuntimeError("No advisor configured — pass advisor= to ChargenSession.create()")
        from src.engine.lifepath_choices import build_rules_summary
        from src.game.advice import record_advice

        choice = self.current_choice()
        rules_summary = build_rules_summary(choice)
        record = await self._advisor.suggest(choice, rules_summary)
        record_advice(self._engine, record)
        return record

    async def propose(self, text: str) -> TranslationRecord:
        """Translate free text into a candidate selection (P6.T2, A3).

        Records the proposal via ``record_proposal`` (funnel Command).
        Raises ``RuntimeError`` if no translator.
        """
        if self._translator is None:
            raise RuntimeError(
                "No translator configured — pass translator= to ChargenSession.create()"
            )
        from src.engine.lifepath_choices import build_rules_summary
        from src.game.advice import record_proposal

        choice = self.current_choice()
        rules_summary = build_rules_summary(choice)
        record = await self._translator.propose(text, choice, rules_summary)
        record_proposal(self._engine, record)
        return record

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _step_result(self) -> StepResult:
        """Build a StepResult from the current controller state (P6.T1)."""
        phase = self._controller.determine_phase()
        completed = phase == "complete"
        view = None if completed else self.current_choice()
        receipts = [e.description for e in self._engine.state.events[-3:]]
        return StepResult(view=view, receipts=receipts, completed=completed)
