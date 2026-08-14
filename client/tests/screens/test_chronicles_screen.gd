extends GdUnitTestSuite
## Chronicles against FakeEngineClient (mock 02): dockets, preview, lifecycle.

var _fake: FakeEngineClient
var _screen: ChroniclesScreen


func _now() -> float:
	return Time.get_unix_time_from_system()


func _saves_payload() -> Dictionary:
	return {
		"saves":
		[
			{
				"name": "mara.autosave",
				"base_name": "mara",
				"autosave": true,
				"theme_pack": "scifi",
				"character_name": "Mara Voss",
				"terms": 4,
				"career": "Scout",
				"alive": true,
				"mtime": _now() - 7200.0,
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
				"mtime": _now() - 259200.0,
			},
			{
				"name": "rook",
				"base_name": "rook",
				"autosave": false,
				"theme_pack": "scifi",
				"character_name": "Rook (DEX-7)",
				"terms": 6,
				"career": "Marine",
				"alive": false,
				"mtime": _now() - 604800.0,
			},
		]
	}


func _envelope(save_name: String) -> Dictionary:
	return {
		"session":
		{
			"id": "sess-" + save_name,
			"name": save_name,
			"kind": "adventure",
			"phase": "scene",
			"view": {"phase": "scene", "game_over": false},
			"contract_version": 1,
		}
	}


func before_test() -> void:
	ClientSettings.use_test_path()
	_fake = auto_free(FakeEngineClient.new())
	add_child(_fake)
	_fake.responses["list_saves"] = FakeEngineClient.ok(_saves_payload())
	_fake.responses["resume_session"] = [
		FakeEngineClient.ok(_envelope("mara")),
		FakeEngineClient.ok(_envelope("branwen")),
		FakeEngineClient.ok(_envelope("mara")),
	]
	_fake.responses["recap"] = FakeEngineClient.ok(
		{
			"lines": ["The crew took on a job.", "Unresolved: the beacon's debt"],
			"source": "template"
		}
	)
	_fake.responses["delete_session"] = FakeEngineClient.ok({})
	_fake.responses["delete_save"] = FakeEngineClient.ok({"deleted": ["mara.json"]})
	_fake.responses["duplicate_save"] = FakeEngineClient.ok({"created": ["mara-2.json"]})
	Services.overlay = auto_free(OverlayLayer.new())
	add_child(Services.overlay)
	_screen = auto_free(ChroniclesScreen.new())
	_screen.client_override = _fake
	add_child(_screen)
	await _screen.screen_enter({})
	# let the auto-selection of the first docket finish
	await get_tree().process_frame
	await get_tree().process_frame


func after_test() -> void:
	# flush deferred frees (the screen rebuilds detach+queue_free dozens of
	# nodes per test) so the orphan monitor sees a clean tree
	await get_tree().process_frame
	await get_tree().process_frame
	Services.overlay = null
	ClientSettings.set_value("ui/last_played_pack", "")
	PackThemes.apply("neutral")


func test_dockets_render_sorted_with_import_slot() -> void:
	# 3 saves + the import slot; autosave (newest mtime) first.
	assert_that(_screen.docket_count()).is_equal(4)
	assert_str(_screen._spines[0].text_content).is_equal("AUTO·2H")
	assert_str(_screen._spines[1].text_content).is_equal("MANUAL")
	assert_str(_screen._spines[2].text_content).is_equal("✝ R.I.P.")


func test_first_docket_auto_selected_with_recap() -> void:
	var resumes := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "resume_session")
	assert_that(resumes.size()).is_equal(1)
	assert_str(str(resumes[0][1])).is_equal("mara")
	assert_str(_screen._preview_name.text).is_equal("Mara Voss")
	assert_that(_screen._preview_prose.get_child_count()).is_equal(2)


func test_selection_change_deletes_previous_preview() -> void:
	await _screen.select_docket(1)
	await get_tree().process_frame
	await get_tree().process_frame
	var deletes := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "delete_session")
	assert_that(deletes.size()).is_equal(1)
	assert_str(str(deletes[0][1])).is_equal("sess-mara")
	var resumes := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "resume_session")
	assert_str(str(resumes[1][1])).is_equal("branwen")


func test_resume_promotes_preview_and_navigates() -> void:
	var nav: Array = []
	_screen.navigate.connect(
		func(target: String, params: Dictionary) -> void: nav.append([target, params])
	)
	_screen.press_action("resume")
	await get_tree().process_frame
	await get_tree().process_frame
	assert_str(str(nav[0][0])).is_equal("stub")
	assert_str(str(nav[0][1]["session"]["id"])).is_equal("sess-mara")
	assert_str(SessionStore.session_id()).is_equal("sess-mara")
	# promoted — exit must NOT delete it
	_screen.screen_exit()
	await get_tree().process_frame
	var deletes := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "delete_session")
	assert_that(deletes.size()).is_equal(0)
	SessionStore.clear()


func test_exit_deletes_unpromoted_preview() -> void:
	_screen.screen_exit()
	await get_tree().process_frame
	await get_tree().process_frame
	var deletes := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "delete_session")
	assert_that(deletes.size()).is_equal(1)
	assert_str(str(deletes[0][1])).is_equal("sess-mara")


func test_delete_flow_confirms_then_deletes() -> void:
	_screen.press_action("delete")
	await get_tree().process_frame
	# answer the confirm modal
	var modal: Node = Services.overlay.get_child(Services.overlay.get_child_count() - 1)
	modal._answer(true)
	await get_tree().process_frame
	await get_tree().process_frame
	var deletes := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "delete_save")
	assert_that(deletes.size()).is_equal(1)
	assert_str(str(deletes[0][1])).is_equal("mara")
