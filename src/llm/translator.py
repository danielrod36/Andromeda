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
