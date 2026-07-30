"""Template narration for lifepath outcomes — no LLM required (AE7).

Generates one-line prose per term outcome from mechanical events. This is the
v0.1 standalone narration layer and the fallback for v0.2+ when no LLM is
configured.

Templates reference career name, skill names, characteristic names, and roll
margins to produce contextual prose that reflects the mechanical outcome.
"""

from __future__ import annotations

from src.engine.lifepath import (
    LifepathResult,
    MusteringOutResult,
    QualificationResult,
    TermResult,
)


class Narrator:
    """Template-based narrator for lifepath results.

    Each method returns a single prose line (or list of lines for full
    lifepath) suitable for display in the narrative log.
    """

    # ------------------------------------------------------------------
    # Qualification narration.
    # ------------------------------------------------------------------

    def narrate_qualification(self, result: QualificationResult) -> str:
        if result.success:
            if result.margin >= 3:
                return (
                    f"You excel in the {result.career_name} entrance "
                    f"exams and are accepted with honors."
                )
            else:
                return f"You pass the {result.career_name} qualification and begin your career."
        else:
            return (
                f"Your application for the {result.career_name} is rejected "
                f"(rolled {result.adjusted_total} vs {result.target})."
            )

    # ------------------------------------------------------------------
    # Term narration.
    # ------------------------------------------------------------------

    def narrate_term(self, result: TermResult) -> str:
        """Produce one-line prose for a single term's mechanical outcome."""
        parts: list[str] = [f"Term {result.term_number}: You serve as a {result.career_name}."]

        # Survival outcome.
        if result.died:
            parts.append(
                f"Disaster strikes — you do not survive the term "
                f"(rolled {result.survival_total} vs {result.survival_target})."
            )
            return " ".join(parts)

        if result.mishap:
            parts.append(
                f"A serious mishap ends your {result.career_name} career "
                f"(rolled {result.survival_total} vs {result.survival_target})."
            )
            return " ".join(parts)

        if result.survival_margin <= 1:
            parts.append("You narrowly escape a close call in the line of duty.")
        else:
            parts.append("You complete your duties without major incident.")

        # Advancement outcome.
        if result.advancement_success:
            title = f" to {result.rank_title}" if result.rank_title else ""
            parts.append(f"Your competence is recognized — you are promoted{title}.")
        else:
            parts.append("You are passed over for advancement this term.")

        # Skill acquisitions.
        skill_parts: list[str] = []
        char_parts: list[str] = []
        for gain in result.skill_gains:
            if gain.gain_type == "skill":
                skill_parts.append(gain.gain_name)
            else:
                char_parts.append(f"+1 {gain.gain_name}")

        if skill_parts:
            parts.append(f"You develop your skills: {', '.join(skill_parts)}.")
        if char_parts:
            parts.append(f"Your characteristics improve: {', '.join(char_parts)}.")

        # Aging effects.
        if result.aging_reductions:
            reduced = ", ".join(f"{k} -{v}" for k, v in result.aging_reductions.items())
            parts.append(f"The years take their toll ({reduced}).")

        return " ".join(parts)

    # ------------------------------------------------------------------
    # Mustering out narration.
    # ------------------------------------------------------------------

    def narrate_mustering_out(self, result: MusteringOutResult) -> str:
        parts: list[str] = [
            (
                f"After {result.terms_served} term(s) of service as a "
                f"{result.career_name}, you muster out."
            )
        ]
        if result.cash_benefits:
            parts.append(f"Cash: {', '.join(result.cash_benefits)}.")
        if result.material_benefits:
            parts.append(f"Benefits: {', '.join(result.material_benefits)}.")
        return " ".join(parts)

    # ------------------------------------------------------------------
    # Full lifepath narration.
    # ------------------------------------------------------------------

    def narrate_lifepath(self, result: LifepathResult) -> list[str]:
        """Produce a list of prose lines covering the full lifepath."""
        lines: list[str] = []

        # Characteristics summary.
        char_line = ", ".join(f"{k} {v}" for k, v in result.characteristics.items())
        lines.append(f"Characteristics: {char_line}.")

        if result.qualification:
            lines.append(self.narrate_qualification(result.qualification))

        for term in result.terms:
            lines.append(self.narrate_term(term))

        if result.mustering_out:
            lines.append(self.narrate_mustering_out(result.mustering_out))

        if not result.character_alive:
            lines.append("Your character did not survive character generation.")

        return lines
