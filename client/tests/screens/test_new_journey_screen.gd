extends GdUnitTestSuite
## New Journey against FakeEngineClient (mock 03: the launch manifest).

var _fake: FakeEngineClient
var _screen: NewJourneyScreen


func before_test() -> void:
	ClientSettings.use_test_path()
	_fake = auto_free(FakeEngineClient.new())
	add_child(_fake)
	_fake.responses["list_packs"] = (
		FakeEngineClient
		. ok(
			{
				"packs":
				[
					{
						"id": "scifi",
						"name": "Frontier Sci-Fi",
						"description": "The Cepheus frontier.",
						"career_count": 25,
						"skill_count": 57,
						"has_cascades": true,
						"has_draft": false,
						"theme":
						{"motif": "✦", "accent": "amber", "ambience": ["meteors", "birds"]},
						"has_intro": true,
					},
					{
						"id": "fantasy",
						"name": "Sword & Sorcery",
						"description": "An original fantasy pack.",
						"career_count": 10,
						"skill_count": 40,
						"has_cascades": false,
						"has_draft": false,
						"theme":
						{"motif": "❧", "accent": "gold", "ambience": ["fireflies", "leaves"]},
						"has_intro": true,
					},
				]
			}
		)
	)
	_fake.responses["list_rulesets"] = (
		FakeEngineClient
		. ok(
			{
				"rulesets":
				[
					{
						"id": "cepheus",
						"name": "Cepheus Engine",
						"characteristics": [],
						"difficulty_ladder": {},
						"resolution_target": 8,
						"resolution_profiles": ["classic", "narrative"],
						"death_modes": ["checkpoint", "ironman", "narrative"],
					}
				]
			}
		)
	)
	_fake.responses["llm_status"] = FakeEngineClient.ok(
		{
			"configured": true,
			"model": "claude-sonnet-5",
			"key_backend": "keyring",
			"degraded_line": null
		}
	)
	_fake.responses["get_settings"] = (
		FakeEngineClient
		. ok(
			{
				"provider": "anthropic",
				"model": "claude-sonnet-5",
				"base_url": "",
				"max_retries": 3,
				"is_configured": true,
				"key_backend": "keyring",
				"key_tail": "wxyz",
			}
		)
	)
	_fake.responses["list_saves"] = FakeEngineClient.ok({"saves": []})
	Services.overlay = auto_free(OverlayLayer.new())
	add_child(Services.overlay)
	_screen = auto_free(NewJourneyScreen.new())
	_screen.client_override = _fake
	add_child(_screen)
	await _screen.screen_enter({})


func after_test() -> void:
	# BEGIN persists ui/last_played_pack and applies the pack theme
	ClientSettings.set_value("ui/last_played_pack", "")
	PackThemes.apply("neutral")
	Services.overlay = null


func test_manifest_sections_render_with_defaults() -> void:
	assert_that(_screen._pack_cards.size()).is_equal(2)
	assert_that(_screen._profile_cards.size()).is_equal(2)
	assert_that(_screen._death_cards.size()).is_equal(3)
	assert_str(_screen.selected_pack).is_equal("scifi")
	assert_str(_screen.selected_profile).is_equal("narrative")
	assert_str(_screen.selected_death).is_equal("narrative")
	assert_str(_screen._narrator_line.text).is_equal(
		"NARRATOR: CLAUDE-SONNET-5 ● · TEMPLATES IF IT EVER FAILS"
	)
	assert_str(_screen._cap_line.text).is_equal("SPEND CAP: 4 CALLS PER BEAT")


func test_seed_is_six_digits_and_rerollable() -> void:
	var first := _screen._seed_label.text
	assert_bool(first.is_valid_int()).is_true()
	assert_bool(int(first) >= 100000 and int(first) <= 999999).is_true()
	var seen := {first: true}
	for i: int in 3:
		_screen.press_reroll()
		seen[_screen._seed_label.text] = true
	assert_bool(seen.size() > 1).is_true()


func test_begin_requires_a_name() -> void:
	_screen._name_edit.text = ""
	_screen.press_begin()
	await get_tree().process_frame
	var creates := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "create_session")
	assert_bool(creates.is_empty()).is_true()


func test_begin_rejects_name_collision() -> void:
	_fake.responses["list_saves"] = (
		FakeEngineClient
		. ok(
			{
				"saves":
				[
					{
						"name": "mara",
						"base_name": "mara",
						"autosave": false,
						"theme_pack": "scifi",
						"character_name": "Mara",
						"terms": 1,
						"career": "Scout",
						"alive": true,
						"mtime": 1.0,
					}
				]
			}
		)
	)
	_screen._name_edit.text = "MARA"
	_screen.press_begin()
	await get_tree().process_frame
	await get_tree().process_frame
	var creates := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "create_session")
	assert_bool(creates.is_empty()).is_true()


func test_begin_aborts_when_save_list_fails() -> void:
	_fake.responses["list_saves"] = FakeEngineClient.err(500, "io", "save list unavailable")
	_fake.responses["create_session"] = _ok_session("The Ruuth Run")
	_screen._name_edit.text = "The Ruuth Run"
	_screen.press_begin()
	await get_tree().process_frame
	await get_tree().process_frame
	var creates := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "create_session")
	assert_bool(creates.is_empty()).is_true()  # must not blind-create past a failed pre-check


func test_begin_creates_session_and_navigates() -> void:
	_fake.responses["create_session"] = _ok_session("The Ruuth Run")
	_screen._name_edit.text = "The Ruuth Run"
	var nav: Array = []
	_screen.navigate.connect(
		func(target: String, params: Dictionary) -> void: nav.append([target, params])
	)
	_screen.press_begin()
	await get_tree().process_frame
	await get_tree().process_frame
	var creates := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "create_session")
	assert_that(creates.size()).is_equal(1)
	var payload: Dictionary = creates[0][1]
	assert_str(str(payload["kind"])).is_equal("chargen")
	assert_str(str(payload["name"])).is_equal("The Ruuth Run")
	assert_str(str(payload["pack_id"])).is_equal("scifi")
	assert_str(str(payload["profile"])).is_equal("narrative")
	assert_str(str(payload["death_mode"])).is_equal("narrative")
	assert_bool(payload["seed"] is int).is_true()
	assert_str(str(nav[0][0])).is_equal("ceremony")
	SessionStore.clear()


func test_begin_double_press_creates_once() -> void:
	_fake.responses["create_session"] = _ok_session("The Ruuth Run")
	_screen._name_edit.text = "The Ruuth Run"
	_screen.press_begin()
	_screen.press_begin()  # double-press during the create await
	await get_tree().process_frame
	await get_tree().process_frame
	var creates := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "create_session")
	assert_that(creates.size()).is_equal(1)
	SessionStore.clear()


func test_select_card_keeps_name_edit_focus_and_caret() -> void:
	_screen._name_edit.text = "Ruuth"
	_screen._name_text = "Ruuth"  # text_changed fires for user edits only
	_screen._name_edit.grab_focus()
	_screen._name_edit.caret_column = 3
	_screen.select_card("pack", "fantasy")
	assert_bool(_screen._name_edit.has_focus()).is_true()
	assert_that(_screen._name_edit.caret_column).is_equal(3)
	assert_str(_screen._name_edit.text).is_equal("Ruuth")


func _ok_session(name: String) -> EngineResult:
	return (
		FakeEngineClient
		. ok(
			{
				"session":
				{
					"id": "new1",
					"name": name,
					"kind": "chargen",
					"phase": "homeworld",
					"view": {},
					"contract_version": 1,
				}
			}
		)
	)
