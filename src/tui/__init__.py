"""TUI shell for Cepheus Adventure (U4).

Rich terminal interface built on Textual. Three-panel layout:
character sheet sidebar, scrolling narrative log, choice menu.

The engine is a plain sync Python package; the TUI is a client that calls
``engine.apply(cmd)`` and updates panels via reactive ``watch_*`` methods.
Zero Textual imports in the engine library.
"""
