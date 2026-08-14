# gdlint: ignore=max-public-methods
class_name EngineClient
extends Node
## Typed async client for the v1 sidecar API (§A1–A8). One method per route;
## every method returns an EngineResult. The error envelope is parsed exactly
## once, in _request. One HTTPRequest node per call — a few requests/second
## never justifies pool lifecycle risk.

var base_url := ""
var contract_chargen := 0
var contract_adventure := 0
## Round-trip time of the last request, for the settings latency line.
var last_rtt_ms := 0


func setup(p_base_url: String) -> void:
	base_url = p_base_url


# --- core ------------------------------------------------------------------


func _request(method: HTTPClient.Method, path: String, body: Variant = null) -> EngineResult:
	var req := HTTPRequest.new()
	add_child(req)
	var headers := PackedStringArray()
	var payload := ""
	if body != null:
		headers.append("Content-Type: application/json")
		payload = JSON.stringify(body)
	var start := Time.get_ticks_msec()
	var err := req.request(base_url + path, headers, method, payload)
	if err != OK:
		req.queue_free()
		return _transport_error()
	var completed: Array = await req.request_completed
	req.queue_free()
	last_rtt_ms = Time.get_ticks_msec() - start
	return _from_response(completed)


static func _transport_error() -> EngineResult:
	return EngineResult.err_result(
		0, "transport_error", "could not reach the referee — is the sidecar running?"
	)


static func _from_response(completed: Array) -> EngineResult:
	var result: int = completed[0]
	var code: int = completed[1]
	var raw: PackedByteArray = completed[3]
	if result != HTTPRequest.RESULT_SUCCESS:
		return _transport_error()
	if code == 204:
		return EngineResult.ok_result(code, {})
	var text := raw.get_string_from_utf8()
	var parsed: Variant = JSON.parse_string(text)
	if parsed == null:
		return EngineResult.err_result(
			code, "bad_response", "the referee answered with something unreadable"
		)
	if code >= 400:
		var error_code := "http_%d" % code
		var message := text
		if parsed is Dictionary and parsed.has("error"):
			var envelope: Dictionary = parsed["error"]
			error_code = str(envelope.get("code", "unknown"))
			message = str(envelope.get("message", ""))
		return EngineResult.err_result(code, error_code, message)
	if not (parsed is Dictionary):
		parsed = {"value": parsed}
	return EngineResult.ok_result(code, parsed)


func _enc(value: String) -> String:
	return value.uri_encode()


# --- contract ---------------------------------------------------------------


func refresh_contracts() -> EngineResult:
	var res: EngineResult = await health()
	if res.ok:
		var versions: Dictionary = res.data.get("contract_versions", {})
		contract_chargen = int(versions.get("chargen", 0))
		contract_adventure = int(versions.get("adventure", 0))
	return res


## True when the SessionEnvelope's contract_version matches /health (§A2/A3).
func contract_matches(session: Dictionary) -> bool:
	var version := int(session.get("contract_version", -1))
	match str(session.get("kind", "")):
		"chargen":
			return version == contract_chargen
		"adventure":
			return version == contract_adventure
	return false


# --- meta (§A2) -------------------------------------------------------------


func health() -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/health")


func llm_status() -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/llm/status")


# --- config (§A6) -----------------------------------------------------------


func list_packs() -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/config/packs")


func list_rulesets() -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/config/rulesets")


func list_providers() -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/config/providers")


# --- settings (§A7) ---------------------------------------------------------


func get_settings() -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/settings/llm")


func put_settings(payload: Dictionary) -> EngineResult:
	return await _request(HTTPClient.METHOD_PUT, "/v1/settings/llm", payload)


func test_settings() -> EngineResult:
	return await _request(HTTPClient.METHOD_POST, "/v1/settings/llm/test", {})


# --- saves (§A5) ------------------------------------------------------------


func list_saves() -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/saves")


func delete_save(save_name: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_DELETE, "/v1/saves/" + _enc(save_name))


func duplicate_save(save_name: String, new_name: String) -> EngineResult:
	return await _request(
		HTTPClient.METHOD_POST,
		"/v1/saves/" + _enc(save_name) + "/duplicate",
		{"new_name": new_name}
	)


func export_save(save_name: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/saves/" + _enc(save_name) + "/export")


func import_save(save_name: String, document: Dictionary) -> EngineResult:
	return await _request(
		HTTPClient.METHOD_POST, "/v1/saves/import", {"name": save_name, "document": document}
	)


# --- sessions (§A3) ---------------------------------------------------------


func create_session(payload: Dictionary) -> EngineResult:
	return await _request(HTTPClient.METHOD_POST, "/v1/sessions", payload)


func resume_session(from_save: String) -> EngineResult:
	return await _request(
		HTTPClient.METHOD_POST,
		"/v1/sessions",
		# name is required by CreateSessionRequest even when from_save governs
		# routing (§A3); the registry names the session after the save anyway.
		{"name": from_save, "from_save": from_save}
	)


func list_sessions() -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/sessions")


func get_session(id: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/sessions/" + _enc(id))


func delete_session(id: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_DELETE, "/v1/sessions/" + _enc(id))


func choose(id: String, option_id: String, origin := "player") -> EngineResult:
	return await _request(
		HTTPClient.METHOD_POST,
		"/v1/sessions/" + _enc(id) + "/choose",
		{"option_id": option_id, "origin": origin}
	)


func freetext(id: String, text: String) -> EngineResult:
	return await _request(
		HTTPClient.METHOD_POST, "/v1/sessions/" + _enc(id) + "/freetext", {"text": text}
	)


func suggest(id: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_POST, "/v1/sessions/" + _enc(id) + "/suggest", {})


func set_character_name(id: String, char_name: String) -> EngineResult:
	return await _request(
		HTTPClient.METHOD_POST, "/v1/sessions/" + _enc(id) + "/name", {"name": char_name}
	)


func promote(id: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_POST, "/v1/sessions/" + _enc(id) + "/promote", {})


func save_session(id: String, save_name: String) -> EngineResult:
	return await _request(
		HTTPClient.METHOD_POST, "/v1/sessions/" + _enc(id) + "/save", {"name": save_name}
	)


# --- inspect (§A8) ----------------------------------------------------------


func recap(id: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/sessions/" + _enc(id) + "/recap")


func sheet(id: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/sessions/" + _enc(id) + "/sheet")


func memorial(id: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/sessions/" + _enc(id) + "/memorial")


func audit(id: String, params: Dictionary) -> EngineResult:
	var query := PackedStringArray()
	for key: String in ["kind", "stream", "since", "page", "per_page"]:
		if params.has(key) and str(params[key]) != "":
			query.append("%s=%s" % [key, str(params[key]).uri_encode()])
	var path := "/v1/sessions/" + _enc(id) + "/audit"
	if not query.is_empty():
		path += "?" + "&".join(query)
	return await _request(HTTPClient.METHOD_GET, path)


func llm_context(id: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/sessions/" + _enc(id) + "/llm-context")


func odds(id: String, skill: String, characteristic: String, difficulty: String) -> EngineResult:
	return await _request(
		HTTPClient.METHOD_POST,
		"/v1/sessions/" + _enc(id) + "/odds",
		{"skill": skill, "characteristic": characteristic, "difficulty": difficulty}
	)


func state_hash(id: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_GET, "/v1/sessions/" + _enc(id) + "/hash")


func verify(id: String) -> EngineResult:
	return await _request(HTTPClient.METHOD_POST, "/v1/sessions/" + _enc(id) + "/verify", {})
