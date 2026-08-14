extends GdUnitTestSuite
## EngineClient integration against the real sidecar (one boot per suite).
##
## SAFETY: never send `provider` or `api_key` changes from tests — a provider
## switch deletes the stored key server-side (§A7). The settings roundtrip
## below touches max_retries only.

var _sidecar: SidecarProcess
var _client: EngineClient


func before() -> void:
	_sidecar = SidecarProcess.new()
	add_child(_sidecar)
	var outcome := {"ok": false, "reason": ""}
	_sidecar.booted.connect(func(_url: String, _p: int) -> void: outcome["ok"] = true)
	_sidecar.boot_failed.connect(func(reason: String) -> void: outcome["reason"] = reason)
	_sidecar.spawn()
	var waited := 0.0
	while not outcome["ok"] and outcome["reason"] == "" and waited < 20.0:
		await get_tree().create_timer(0.1).timeout
		waited += 0.1
	if outcome["reason"] != "":
		push_error("sidecar boot failed: " + outcome["reason"])
	_client = EngineClient.new()
	add_child(_client)
	_client.setup(_sidecar.base_url)


func after() -> void:
	_sidecar.kill()


func _unique_name() -> String:
	return "m2-itest-%d" % int(Time.get_unix_time_from_system() * 1000.0)


func test_health_and_contracts() -> void:
	var res: EngineResult = await _client.refresh_contracts()
	assert_bool(res.ok).is_true()
	assert_str(str(res.data.get("status"))).is_equal("ok")
	assert_that(_client.contract_chargen).is_equal(1)
	assert_that(_client.contract_adventure).is_equal(1)


func test_llm_status_shape() -> void:
	var res: EngineResult = await _client.llm_status()
	assert_bool(res.ok).is_true()
	# configured depends on the machine's key store — assert shape, not value.
	assert_bool(res.data.has("configured")).is_true()
	assert_bool(res.data.has("key_backend")).is_true()
	if not bool(res.data["configured"]):
		assert_str(str(res.data["degraded_line"])).is_equal(
			"narration unavailable — showing mechanical outcomes"
		)


func test_config_packs() -> void:
	var res: EngineResult = await _client.list_packs()
	assert_bool(res.ok).is_true()
	var by_id := {}
	for pack: Dictionary in res.data["packs"]:
		by_id[pack["id"]] = pack
	assert_bool(by_id.has("scifi")).is_true()
	assert_bool(by_id.has("fantasy")).is_true()
	var scifi: Dictionary = by_id["scifi"]
	assert_that(int(scifi["career_count"])).is_equal(25)
	assert_bool(bool(scifi["has_cascades"])).is_true()
	assert_str(str(scifi["theme"]["motif"])).is_equal("✦")
	assert_str(str(scifi["theme"]["accent"])).is_equal("amber")
	assert_that(Array(scifi["theme"]["ambience"])).is_equal(["meteors", "birds"])


func test_config_rulesets_and_providers() -> void:
	var rules: EngineResult = await _client.list_rulesets()
	assert_bool(rules.ok).is_true()
	var cepheus: Dictionary = rules.data["rulesets"][0]
	assert_that(Array(cepheus["resolution_profiles"])).is_equal(["classic", "narrative"])
	var death_modes := Array(cepheus["death_modes"])
	death_modes.sort()
	assert_that(death_modes).is_equal(["checkpoint", "ironman", "narrative"])

	var providers: EngineResult = await _client.list_providers()
	assert_bool(providers.ok).is_true()
	var by_id := {}
	for p: Dictionary in providers.data["providers"]:
		by_id[p["id"]] = p
	assert_str(str(by_id["anthropic"]["label"])).is_equal("Anthropic")
	assert_bool(Array(by_id["anthropic"]["presets"]).has("claude-sonnet-5")).is_true()


func test_settings_roundtrip_max_retries_only() -> void:
	var before: EngineResult = await _client.get_settings()
	assert_bool(before.ok).is_true()
	var original := int(before.data["max_retries"])
	var payload := before.data.duplicate()
	payload["max_retries"] = original + 1
	payload.erase("is_configured")
	payload.erase("key_backend")
	payload.erase("key_tail")
	payload["api_key"] = null  # keep the stored key (§A7)
	var put: EngineResult = await _client.put_settings(payload)
	assert_bool(put.ok).is_true()
	assert_that(int(put.data["max_retries"])).is_equal(original + 1)
	payload["max_retries"] = original
	var restored: EngineResult = await _client.put_settings(payload)
	assert_bool(restored.ok).is_true()
	assert_that(int(restored.data["max_retries"])).is_equal(original)


func test_settings_test_endpoint_never_raises() -> void:
	var res: EngineResult = await _client.test_settings()
	assert_bool(res.ok).is_true()  # transport ok; body carries ok:true/false
	assert_bool(res.data.has("ok")).is_true()
	if not bool(res.data["ok"]):
		assert_str(str(res.data["error"])).is_not_empty()


func test_session_lifecycle_and_envelope() -> void:
	var name := _unique_name()
	var created: EngineResult = await _client.create_session(
		{"kind": "chargen", "name": name, "seed": 482991, "pack_id": "scifi"}
	)
	assert_bool(created.ok).is_true()
	var session: Dictionary = created.data["session"]
	for key: String in ["id", "name", "kind", "phase", "view", "contract_version"]:
		assert_bool(session.has(key)).is_true()
	assert_str(session["kind"]).is_equal("chargen")
	assert_that(int(session["contract_version"])).is_equal(1)
	assert_bool(_client.contract_matches(session)).is_true()
	# §A3: chargen view is a ChoicePointView.
	var view: Dictionary = session["view"]
	assert_bool(view.has("choice_id")).is_true()
	assert_bool(view.has("options")).is_true()
	assert_bool(not Array(view["options"]).is_empty()).is_true()

	var fetched: EngineResult = await _client.get_session(session["id"])
	assert_bool(fetched.ok).is_true()
	var deleted: EngineResult = await _client.delete_session(session["id"])
	assert_bool(deleted.ok).is_true()
	var gone: EngineResult = await _client.get_session(session["id"])
	assert_bool(gone.ok).is_false()
	assert_that(gone.status).is_equal(404)
	assert_str(gone.error_code).is_equal("session_not_found")
	assert_str(gone.error_message).is_not_empty()


func test_saves_crud_cycle() -> void:
	var name := _unique_name()
	var created: EngineResult = await _client.create_session({"kind": "chargen", "name": name})
	assert_bool(created.ok).is_true()
	var session_id := str(created.data["session"]["id"])
	# GET forces the autosave to disk (routes_sessions.py:133).
	await _client.get_session(session_id)

	var saves: EngineResult = await _client.list_saves()
	assert_bool(saves.ok).is_true()
	var entry := {}
	for s: Dictionary in saves.data["saves"]:
		if s["base_name"] == name:
			entry = s
	assert_bool(not entry.is_empty()).is_true()
	assert_bool(bool(entry["autosave"])).is_true()
	assert_str(str(entry["theme_pack"])).is_equal("scifi")
	assert_bool(bool(entry["alive"])).is_true()

	var dup: EngineResult = await _client.duplicate_save(name, name + "-copy")
	assert_bool(dup.ok).is_true()
	assert_bool(not Array(dup.data["created"]).is_empty()).is_true()

	var exported: EngineResult = await _client.export_save(name)
	assert_bool(exported.ok).is_true()
	assert_bool(int(exported.data.get("save_version", 0)) >= 1).is_true()

	var imported: EngineResult = await _client.import_save(name + "-imp", exported.data)
	assert_bool(imported.ok).is_true()
	assert_str(str(imported.data["name"])).is_equal(name + "-imp")

	var conflict: EngineResult = await _client.import_save(name + "-imp", exported.data)
	assert_bool(conflict.ok).is_false()
	assert_str(conflict.error_code).is_equal("save_conflict")

	assert_bool((await _client.delete_save(name + "-imp")).ok).is_true()
	assert_bool((await _client.delete_save(name + "-copy")).ok).is_true()
	assert_bool((await _client.delete_save(name)).ok).is_true()
	var missing: EngineResult = await _client.delete_save(name)
	assert_bool(missing.ok).is_false()
	assert_str(missing.error_code).is_equal("save_not_found")
	await _client.delete_session(session_id)


func test_resume_infers_kind() -> void:
	var name := _unique_name()
	var created: EngineResult = await _client.create_session({"kind": "chargen", "name": name})
	assert_bool(created.ok).is_true()
	await _client.get_session(created.data["session"]["id"])  # autosave
	var resumed: EngineResult = await _client.resume_session(name)
	assert_bool(resumed.ok).is_true()
	assert_str(str(resumed.data["session"]["kind"])).is_equal("chargen")
	await _client.delete_session(resumed.data["session"]["id"])
	await _client.delete_session(created.data["session"]["id"])
	await _client.delete_save(name)


func test_choose_returns_events() -> void:
	var name := _unique_name()
	var created: EngineResult = await _client.create_session(
		{"kind": "chargen", "name": name, "seed": 7}
	)
	assert_bool(created.ok).is_true()
	var session: Dictionary = created.data["session"]
	var options: Array = session["view"]["options"]
	var option_id := str(options[0]["option_id"])
	var chosen: EngineResult = await _client.choose(session["id"], option_id)
	assert_bool(chosen.ok).is_true()
	assert_bool(chosen.data.has("session")).is_true()
	assert_bool(chosen.data.has("result")).is_true()
	assert_bool(chosen.data.has("events")).is_true()
	for e: Dictionary in chosen.data["events"]:
		for key: String in ["seq", "kind", "command_type", "description", "changes"]:
			assert_bool(e.has(key)).is_true()
	await _client.delete_session(session["id"])
	await _client.delete_save(name)


func test_freetext_and_suggest_envelopes() -> void:
	var name := _unique_name()
	var created: EngineResult = await _client.create_session({"kind": "chargen", "name": name})
	var session_id := str(created.data["session"]["id"])
	var ft: EngineResult = await _client.freetext(session_id, "a wandering scout")
	# Without a configured translator: 422 translator_unavailable. With one:
	# ok. Accept either; assert the envelope is well-formed.
	if not ft.ok:
		assert_str(ft.error_code).is_equal("translator_unavailable")
		assert_str(ft.error_message).is_not_empty()
	var sg: EngineResult = await _client.suggest(session_id)
	if not sg.ok:
		assert_str(sg.error_code).is_equal("advisor_unavailable")
		assert_str(sg.error_message).is_not_empty()
	await _client.delete_session(session_id)
	await _client.delete_save(name)
