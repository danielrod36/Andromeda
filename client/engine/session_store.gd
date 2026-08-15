extends Node
## Autoload: SessionStore — the in-memory SessionRef (spec §4). Holds zero
## game truth: the current SessionEnvelope (§A3) and nothing else. Any
## reconnect re-fetches GET /v1/sessions/{id} via EngineClient.

signal session_changed(session: Dictionary)

var current: Dictionary = {}


func has_session() -> bool:
	return not current.is_empty()


func set_current(session: Dictionary) -> void:
	current = session
	session_changed.emit(current)


func clear() -> void:
	current = {}
	session_changed.emit(current)


func session_id() -> String:
	return str(current.get("id", ""))
