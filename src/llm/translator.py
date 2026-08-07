"""Free-text translator: map player intent onto engine-enumerated candidates (P5).

ADR A3 — candidate-constrained translation. The engine enumerates the legal
candidates (the ``ChoicePointView``'s options); the LLM may only pick one.
The proposal passes a heuristic compliance gate and is recorded via
``RecordProposalCommand`` (ADR A2/A10) — the LLM never mutates state.
"""

from __future__ import annotations

import hashlib
import json
import logging

from pydantic import BaseModel

from src.engine.lifepath_choices import ChoicePointView

logger = logging.getLogger(__name__)

#: Prompt contract version for translator proposals (P5.T1, ADR A9).
TRANSLATOR_PROMPT_VERSION = "translator.v1"


class TranslationRecord(BaseModel):
    """Recorded free-text translation proposal (P5.T1).

    Master-locked shape plus the additive ``rejection_reason`` field (see
    part-5 Changelog): on a rejection it carries the gate reason for the UI
    while ``rationale`` preserves the model's own words.
    """

    choice_id: str
    text: str
    selected_option_id: str | None
    rationale: str
    context_hash: str
    validation: str  # "passed" | "rejected_no_match" | "rejected_invalid"
    rejection_reason: str = ""


def context_hash_for(choice: ChoicePointView) -> str:
    """Fingerprint the exact candidate list the model saw (P5.T1).

    A recorded proposal is auditable against the precise options on offer:
    same options → same hash; any label/preview/dimmed change → new hash.
    """
    canonical = json.dumps(choice.model_dump(), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Candidate → controller dispatch resolution (P5.T3, ADR A3).
# ---------------------------------------------------------------------------

#: Static option ids handled by ``LifepathController.apply_choice``
#: (src/game/lifepath.py:887-1001). Drift-guarded by TestDispatchIdFor.
_STATIC_DISPATCH_IDS: frozenset[str] = frozenset(
    {
        "roll_pool",
        "fallback_retry",
        "fallback_draft",
        "fallback_drifter",
        "career_change_new",
        "career_change_muster",
        "begin_term",
        "commission_attempt",
        "commission_decline",
        "advancement_attempt",
        "advancement_decline",
        "roll_aging",
        "roll_mishap",
        "crisis_pay",
        "crisis_scar",
        "reenlist_continue",
        "reenlist_muster",
        "claim_cash",
        "claim_material",
        "begin_adventure",
        "auto_advance",
    }
)

#: Prefix-dispatched option ids (``apply_choice`` routes via ``startswith``).
_DISPATCH_PREFIXES: tuple[str, ...] = (
    "assign:",
    "bg_skill:",
    "career:",
    "skill_table:",
    "aging_stat:",
    "injury_stat:",
)


def dispatch_id_for(option_id: str) -> str | None:
    """Resolve an option_id to its controller dispatch key (P5.T3).

    Returns the exact id for static keys, the matched prefix for templated
    keys, or ``None`` when no ``LifepathController.apply_choice`` branch would
    handle it — the hard dispatch gate (b) of :meth:`Translator.propose`.
    """
    if option_id in _STATIC_DISPATCH_IDS:
        return option_id
    for prefix in _DISPATCH_PREFIXES:
        if option_id.startswith(prefix) and option_id != prefix:
            return prefix
    return None
