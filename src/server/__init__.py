"""Andromeda sidecar server — FastAPI over 127.0.0.1, NDJSON streaming (M0.6).

The server wraps the engine's session contracts and owns autosave, key
storage, and the LLM adapter. The Godot client holds zero game truth.
"""
