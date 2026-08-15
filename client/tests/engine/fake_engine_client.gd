# gdlint: ignore=max-public-methods
class_name FakeEngineClient
extends Node
## Test double for EngineClient (spec §8): same method surface, canned
## responses, scriptable errors, call log. Methods are plain (non-coroutine)
## — `await` on a plain value returns it immediately, so screens' await
## callsites work unchanged.

var base_url := ""
var responses := {}
var calls: Array = []
var contract_chargen := 1
var contract_adventure := 1
## Deterministic latency for the settings status line.
var last_rtt_ms := 12


static func ok(data: Dictionary) -> EngineResult:
	return EngineResult.ok_result(200, data)


static func err(status: int, code: String, msg: String) -> EngineResult:
	return EngineResult.err_result(status, code, msg)


func setup(p_base_url: String) -> void:
	base_url = p_base_url


# --- contract ---------------------------------------------------------------


func refresh_contracts() -> EngineResult:
	return _record("refresh_contracts", [])


## Mirrors EngineClient.contract_matches (§A2/A3): the session's
## contract_version must equal the negotiated version for its kind.
func contract_matches(session: Dictionary) -> bool:
	var version := int(session.get("contract_version", -1))
	match str(session.get("kind", "")):
		"chargen":
			return version == contract_chargen
		"adventure":
			return version == contract_adventure
	return false


func _record(method: String, args: Array) -> EngineResult:
	calls.append([method] + args)
	var canned: Variant = responses.get(method)
	if canned is Array:
		if canned.is_empty():
			return EngineResult.err_result(500, "test", "no canned responses left for " + method)
		return canned.pop_front()
	if canned is EngineResult:
		return canned
	return EngineResult.err_result(500, "test", "no canned response for " + method)


func health() -> EngineResult:
	return _record("health", [])


func llm_status() -> EngineResult:
	return _record("llm_status", [])


func list_packs() -> EngineResult:
	return _record("list_packs", [])


func list_rulesets() -> EngineResult:
	return _record("list_rulesets", [])


func list_providers() -> EngineResult:
	return _record("list_providers", [])


func get_settings() -> EngineResult:
	return _record("get_settings", [])


func put_settings(payload: Dictionary) -> EngineResult:
	return _record("put_settings", [payload])


func test_settings() -> EngineResult:
	return _record("test_settings", [])


func list_saves() -> EngineResult:
	return _record("list_saves", [])


func delete_save(save_name: String) -> EngineResult:
	return _record("delete_save", [save_name])


func duplicate_save(save_name: String, new_name: String) -> EngineResult:
	return _record("duplicate_save", [save_name, new_name])


func export_save(save_name: String) -> EngineResult:
	return _record("export_save", [save_name])


func import_save(save_name: String, document: Dictionary) -> EngineResult:
	return _record("import_save", [save_name, document])


func create_session(payload: Dictionary) -> EngineResult:
	return _record("create_session", [payload])


func resume_session(from_save: String) -> EngineResult:
	return _record("resume_session", [from_save])


func list_sessions() -> EngineResult:
	return _record("list_sessions", [])


func get_session(id: String) -> EngineResult:
	return _record("get_session", [id])


func delete_session(id: String) -> EngineResult:
	return _record("delete_session", [id])


func choose(id: String, option_id: String, origin := "player") -> EngineResult:
	return _record("choose", [id, option_id, origin])


func freetext(id: String, text: String) -> EngineResult:
	return _record("freetext", [id, text])


func suggest(id: String) -> EngineResult:
	return _record("suggest", [id])


func set_character_name(id: String, char_name: String) -> EngineResult:
	return _record("set_character_name", [id, char_name])


func promote(id: String) -> EngineResult:
	return _record("promote", [id])


func save_session(id: String, save_name: String) -> EngineResult:
	return _record("save_session", [id, save_name])


func recap(id: String) -> EngineResult:
	return _record("recap", [id])


# --- inspect (§A8) ----------------------------------------------------------


func sheet(id: String) -> EngineResult:
	return _record("sheet", [id])


func memorial(id: String) -> EngineResult:
	return _record("memorial", [id])


func audit(id: String, params: Dictionary) -> EngineResult:
	return _record("audit", [id, params])


func llm_context(id: String) -> EngineResult:
	return _record("llm_context", [id])


func odds(id: String, skill: String, characteristic: String, difficulty: String) -> EngineResult:
	return _record("odds", [id, skill, characteristic, difficulty])


func state_hash(id: String) -> EngineResult:
	return _record("state_hash", [id])


func verify(id: String) -> EngineResult:
	return _record("verify", [id])
