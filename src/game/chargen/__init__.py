"""ChargenSession — headless, versioned character-creation module (P6).

A self-contained deliverable: the complete chargen flow with advisor
and free-text support, driven by a simple session API. No UI framework.
"""

from src.game.chargen.api import CONTRACT_VERSION, ChargenSession, StepResult

__all__ = ["CONTRACT_VERSION", "ChargenSession", "StepResult"]
