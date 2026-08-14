extends GdUnitTestSuite
## Title screen against FakeEngineClient (mock 01: menu notes, boot readout).
## Autoloads are live in the test run; only the HTTP layer is faked.

var _fake: FakeEngineClient
var _screen: TitleScreen


func before_test() -> void:
	_fake = auto_free(FakeEngineClient.new())
	add_child(_fake)
	_screen = auto_free(TitleScreen.new())
	_screen.client_override = _fake
	add_child(_screen)


func after_test() -> void:
	# _continue() persists ui/last_played_pack and applies the pack theme —
	# restore both so later suites see the documented defaults.
	ClientSettings.set_value("ui/last_played_pack", "")
	PackThemes.apply("neutral")


func _saves_payload() -> Dictionary:
	return {
		"saves":
		[
			{
				"name": "mara",
				"base_name": "mara",
				"autosave": false,
				"theme_pack": "scifi",
				"character_name": "Mara Voss",
				"terms": 4,
				"career": "Scout",
				"alive": true,
				"mtime": Time.get_unix_time_from_system() - 7200.0,
			},
			{
				"name": "branwen",
				"base_name": "branwen",
				"autosave": false,
				"theme_pack": "fantasy",
				"character_name": "Branwen",
				"terms": 2,
				"career": "Bard",
				"alive": true,
				"mtime": Time.get_unix_time_from_system() - 259200.0,
			},
		]
	}


func test_menu_notes_and_strip_with_saves() -> void:
	_fake.responses["list_saves"] = FakeEngineClient.ok(_saves_payload())
	_fake.responses["llm_status"] = FakeEngineClient.ok(
		{
			"configured": true,
			"model": "claude-sonnet-5",
			"key_backend": "keyring",
			"degraded_line": null
		}
	)
	await _screen.screen_enter(
		{"boot_lines": ["REFEREE: LISTENING · 127.0.0.1:63216", "SAVES: OK"]}
	)
	assert_str(_screen.menu_note("continue")).is_equal("MARA VOSS · 2H AGO")
	assert_str(_screen.menu_note("chronicles")).is_equal("2 SAVES")
	assert_bool(_screen.menu_enabled("continue")).is_true()
	assert_str(_screen.boot_text()).is_equal("REFEREE: LISTENING · 127.0.0.1:63216\nSAVES: OK")
	assert_str(_screen._strip._right_text.text).is_equal("NARRATOR: CLAUDE-SONNET-5 ")


func test_no_saves_dims_continue_and_zeroes_chronicles() -> void:
	_fake.responses["list_saves"] = FakeEngineClient.ok({"saves": []})
	_fake.responses["llm_status"] = FakeEngineClient.ok(
		{
			"configured": false,
			"model": null,
			"key_backend": "",
			"degraded_line": "narration unavailable — showing mechanical outcomes"
		}
	)
	await _screen.screen_enter({"boot_lines": []})
	assert_bool(_screen.menu_enabled("continue")).is_false()
	assert_str(_screen.menu_note("chronicles")).is_equal("0 SAVES")
	assert_str(_screen._strip._right_text.text).is_equal("NARRATOR: TEMPLATES ")


func test_menu_navigation_signals() -> void:
	_fake.responses["list_saves"] = FakeEngineClient.ok(_saves_payload())
	_fake.responses["llm_status"] = FakeEngineClient.ok(
		{"configured": false, "model": null, "key_backend": "", "degraded_line": ""}
	)
	await _screen.screen_enter({"boot_lines": []})
	var nav: Array = []
	_screen.navigate.connect(func(target: String, _params: Dictionary) -> void: nav.append(target))
	_screen.press_menu("new_journey")
	_screen.press_menu("chronicles")
	_screen.press_menu("settings")
	assert_that(nav).is_equal(["new_journey", "chronicles", "settings"])


func test_continue_resumes_latest_and_navigates_to_stub() -> void:
	_fake.responses["list_saves"] = FakeEngineClient.ok(_saves_payload())
	_fake.responses["llm_status"] = FakeEngineClient.ok(
		{"configured": false, "model": null, "key_backend": "", "degraded_line": ""}
	)
	_fake.responses["resume_session"] = FakeEngineClient.ok(
		{
			"session":
			{
				"id": "s1",
				"name": "mara",
				"kind": "chargen",
				"phase": "homeworld",
				"view": {},
				"contract_version": 1
			}
		}
	)
	await _screen.screen_enter({"boot_lines": []})
	var nav: Array = []
	_screen.navigate.connect(
		func(target: String, params: Dictionary) -> void: nav.append([target, params])
	)
	_screen.press_menu("continue")
	await get_tree().process_frame  # let the async resume finish
	await get_tree().process_frame
	var resumes := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "resume_session")
	assert_that(resumes.size()).is_equal(1)
	var resume_call: Array = resumes[0]
	assert_str(str(resume_call[1])).is_equal("mara")
	assert_that(nav.size()).is_equal(1)
	assert_str(str(nav[0][0])).is_equal("stub")
	assert_str(str(nav[0][1]["session"]["id"])).is_equal("s1")
	SessionStore.clear()
