"""Minimal text REPL for character creation — no Textual, no web (P6.T4).

Run:  uv run python scripts/chargen_demo.py

Commands at each choice point:
  <number>   Select option by index
  suggest    Ask the Advisor for a recommendation
  say <text> Express intent in your own words (free text)
  save       Serialize and print the save envelope
  quit       Exit
"""

from __future__ import annotations

import asyncio
import sys

from src.game.chargen import CONTRACT_VERSION, ChargenSession
from src.llm.advisor import HeuristicAdvisor


def run_demo(seed: int = 42, death_mode: str = "narrative") -> None:
    """Drive a full lifepath interactively via stdin/stdout (P6.T4)."""
    advisor = HeuristicAdvisor()
    session = ChargenSession.create(
        seed=seed, pack_id="scifi", death_mode=death_mode, advisor=advisor
    )
    print(f"Andromeda Chargen — contract v{CONTRACT_VERSION}")
    print(f"Seed: {seed} | Death mode: {death_mode}\n")

    while True:
        choice = session.current_choice()
        if choice.phase == "complete":
            print("\n=== Character Complete ===")
            ch = session._engine.state.character
            print(f"Name: {ch.name or 'Unnamed'}")
            print(f"Career: {ch.career} (Rank {ch.rank})")
            print(f"Age: {ch.age} | Terms: {ch.terms}")
            print(f"Characteristics: {ch.characteristics}")
            print(f"Skills: {dict(sorted(ch.skills.items()))}")
            print(f"Credits: {ch.credits:,} Cr")
            if ch.inventory:
                print(f"Inventory: {ch.inventory}")
            break

        print(f"\n--- {choice.phase} ---")
        print(choice.prompt)
        for i, opt in enumerate(choice.options):
            tag = f"  [{i}]" if not opt.dimmed else f"  ({i})"
            line = f"{tag} {opt.label}"
            if opt.preview:
                line += f"  — {'; '.join(opt.preview)}"
            if opt.odds_line:
                line += f"  [{opt.odds_line}]"
            if opt.dimmed and opt.requirement:
                line += f"  (locked: {opt.requirement})"
            print(line)

        try:
            raw = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExited.")
            break

        if raw == "quit":
            break
        elif raw == "suggest":
            record = asyncio.run(session.suggest())
            idx = next(
                (
                    i
                    for i, o in enumerate(choice.options)
                    if o.option_id == record.selected_option_id
                ),
                None,
            )
            print(f"\nAdvisor suggests [{idx}]: {record.selected_option_id}")
            print(f"  Rationale: {record.rationale}")
            for alt in record.alternatives:
                print(f"  Considered: {alt.option_id} — {alt.why_not}")
            continue
        elif raw.startswith("say "):
            text = raw[4:].strip()
            # Without a translator, this fails gracefully
            try:
                record = asyncio.run(session.propose(text))
                print(f"  → {record.selected_option_id}: {record.rationale}")
                if record.validation != "passed":
                    print(f"  (rejected: {record.validation})")
                    continue
                result = session.choose(record.selected_option_id)
                for r in result.receipts:
                    print(f"  » {r}")
                continue
            except RuntimeError as e:
                print(f"  (unavailable: {e})")
                continue
        elif raw == "save":
            print(session.serialize())
            continue
        elif raw.isdigit():
            idx = int(raw)
            # C6: skip dimmed options when indexing so the demo driver (and
            # piped-input smoke test) doesn't try to qualify for an already-
            # left career at choose_career. Visible options are indexed 0..N
            # in display order; dimmed options are still listed but skipped
            # by numeric input.
            visible = [o for o in choice.options if not o.dimmed]
            pool = visible if visible else choice.options
            if 0 <= idx < len(pool):
                result = session.choose(pool[idx].option_id)
                for r in result.receipts:
                    print(f"  » {r}")
                continue

        print("Invalid input. Enter a number, 'suggest', 'say <text>', 'save', or 'quit'.")


if __name__ == "__main__":
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 42
    run_demo(seed=seed)
