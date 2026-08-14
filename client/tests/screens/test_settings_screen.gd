extends GdUnitTestSuite
## Settings screen against FakeEngineClient (mock 05).

const _EXPORT_DIR := "user://gdunit_export_test"

var _fake: FakeEngineClient
var _screen: SettingsScreen


func before_test() -> void:
	_fake = auto_free(FakeEngineClient.new())
	add_child(_fake)
	_reset_export_dir()
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
	_fake.responses["list_providers"] = (
		FakeEngineClient
		. ok(
			{
				"providers":
				[
					{
						"id": "anthropic",
						"label": "Anthropic",
						"presets":
						["claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5-20251001"],
						"default_base_url": "https://api.anthropic.com",
						"needs_base_url": false,
					},
					{
						"id": "openrouter",
						"label": "OpenRouter",
						"presets": ["anthropic/claude-sonnet-5"],
						"default_base_url": "https://openrouter.ai/api",
						"needs_base_url": false,
					},
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
	_fake.responses["list_saves"] = FakeEngineClient.ok({"saves": []})
	_fake.responses["put_settings"] = (
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
	_screen = auto_free(SettingsScreen.new())
	_screen.client_override = _fake
	add_child(_screen)
	# failure-path toasts (load + export) need a live overlay
	Services.overlay = auto_free(OverlayLayer.new())
	add_child(Services.overlay)
	await _screen.screen_enter({})


func after_test() -> void:
	_reset_export_dir()
	Services.overlay = null


func test_fields_populate_from_server() -> void:
	assert_str(_screen._provider_option.get_item_text(_screen._provider_option.selected)).is_equal(
		"Anthropic"
	)
	assert_str(_screen._model_option.get_item_text(_screen._model_option.selected)).is_equal(
		"claude-sonnet-5"
	)
	assert_str(_screen._retries_edit.text).is_equal("3")
	assert_str(_screen._key_status.text).is_equal("sk-…wxyz · OS KEYRING")
	assert_str(_screen._data_line.text).is_equal("saves/ · 0 chronicles · autosaves on")
	assert_bool(_screen._provider_warning.visible).is_false()


func test_provider_switch_shows_the_key_warning() -> void:
	var idx := -1
	for i: int in _screen._provider_option.item_count:
		if _screen._provider_option.get_item_text(i) == "OpenRouter":
			idx = i
	_screen.select_provider_index(idx)
	assert_bool(_screen._provider_warning.visible).is_true()
	assert_str(_screen._provider_warning.text).is_equal(
		"Switching provider clears the stored key — re-enter it for the new provider."
	)


func test_test_connection_ok_line() -> void:
	_fake.responses["test_settings"] = FakeEngineClient.ok(
		{"ok": true, "models": ["claude-sonnet-5"]}
	)
	_screen.press_test()
	await get_tree().process_frame
	await get_tree().process_frame
	assert_str(_screen._conn_status.text).is_equal("✓ CONNECTION OK · claude-sonnet-5 · 12ms")


func test_test_connection_failure_line_is_verbatim() -> void:
	_fake.responses["test_settings"] = FakeEngineClient.ok(
		{"ok": false, "error": "No API key stored"}
	)
	_screen.press_test()
	await get_tree().process_frame
	await get_tree().process_frame
	assert_str(_screen._conn_status.text).is_equal("✗ No API key stored")


func test_save_sends_null_api_key_and_confirms() -> void:
	_screen.press_save()
	await get_tree().process_frame
	await get_tree().process_frame
	var puts := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "put_settings")
	assert_that(puts.size()).is_equal(1)
	var payload: Dictionary = puts[0][1]
	assert_str(str(payload["provider"])).is_equal("anthropic")
	assert_str(str(payload["model"])).is_equal("claude-sonnet-5")
	assert_bool(payload.has("api_key")).is_true()
	assert_that(payload["api_key"]).is_equal(null)
	assert_str(_screen._strip._right_text.text).is_equal("SETTINGS SAVED")


func test_reentry_resets_replace_key_mode() -> void:
	_screen._replace_key_mode = true  # a mode left over from a prior visit
	await _screen.screen_enter({})
	assert_bool(_screen._replace_key_mode).is_false()
	assert_bool(_screen._key_edit.visible).is_false()
	# a routine SAVE now sends the null key without any REMOVE-KEY confirm
	_screen.press_save()
	await get_tree().process_frame
	await get_tree().process_frame
	var puts := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "put_settings")
	assert_that(puts.size()).is_equal(1)
	assert_that(puts[0][1]["api_key"]).is_equal(null)


func test_save_list_failure_toasts_and_dashes_count() -> void:
	_fake.responses["list_saves"] = FakeEngineClient.err(500, "io", "save list unavailable")
	await _screen.screen_enter({})
	assert_str(_screen._data_line.text).is_equal("saves/ · — chronicles · autosaves on")
	assert_str(_last_toast()._message).is_equal("save list unavailable")


func test_export_all_writes_each_chronicle_and_reports() -> void:
	_fake.responses["list_saves"] = FakeEngineClient.ok(
		{"saves": [_save_entry("mara"), _save_entry("branwen")]}
	)
	_fake.responses["export_save"] = [
		FakeEngineClient.ok({"name": "mara", "kind": "chargen"}),
		FakeEngineClient.ok({"name": "branwen", "kind": "chargen"}),
	]
	_screen._on_export_dir(true, PackedStringArray([_EXPORT_DIR]), 0)
	await get_tree().process_frame
	var exports := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "export_save")
	assert_that(exports.size()).is_equal(2)
	assert_bool(FileAccess.file_exists(_EXPORT_DIR.path_join("mara.json"))).is_true()
	assert_bool(FileAccess.file_exists(_EXPORT_DIR.path_join("branwen.json"))).is_true()
	assert_str(_last_toast()._message).is_equal("EXPORTED 2/2 CHRONICLES → " + _EXPORT_DIR)
	assert_str(_last_toast()._kind).is_equal("ok")


func test_export_all_continues_past_failures_and_reports() -> void:
	_fake.responses["list_saves"] = FakeEngineClient.ok(
		{"saves": [_save_entry("mara"), _save_entry("branwen")]}
	)
	_fake.responses["export_save"] = [
		FakeEngineClient.ok({"name": "mara", "kind": "chargen"}),
		FakeEngineClient.err(500, "engine", "save blew up"),
	]
	_screen._on_export_dir(true, PackedStringArray([_EXPORT_DIR]), 0)
	await get_tree().process_frame
	var exports := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "export_save")
	assert_that(exports.size()).is_equal(2)  # the failure did not abort the batch
	assert_bool(FileAccess.file_exists(_EXPORT_DIR.path_join("mara.json"))).is_true()
	assert_bool(FileAccess.file_exists(_EXPORT_DIR.path_join("branwen.json"))).is_false()
	assert_str(_last_toast()._message).is_equal("EXPORTED 1/2 CHRONICLES → " + _EXPORT_DIR)
	assert_str(_last_toast()._kind).is_equal("bad")


func test_export_all_declined_overwrite_aborts_everything() -> void:
	var f := FileAccess.open(_EXPORT_DIR.path_join("mara.json"), FileAccess.WRITE)
	f.store_string("{}")
	f.close()
	_fake.responses["list_saves"] = FakeEngineClient.ok(
		{"saves": [_save_entry("mara"), _save_entry("branwen")]}
	)
	_fake.responses["export_save"] = FakeEngineClient.ok({"name": "mara", "kind": "chargen"})
	_screen._on_export_dir(true, PackedStringArray([_EXPORT_DIR]), 0)
	_press_modal_button(Services.overlay, "CANCEL")  # one confirm for the batch
	await get_tree().process_frame
	var exports := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "export_save")
	assert_bool(exports.is_empty()).is_true()
	assert_int(Services.overlay._toast_box.get_child_count()).is_equal(0)  # nothing exported


func _save_entry(base_name: String) -> Dictionary:
	return {
		"name": base_name,
		"base_name": base_name,
		"autosave": false,
		"theme_pack": "scifi",
		"character_name": base_name,
		"terms": 1,
		"career": "Scout",
		"alive": true,
		"mtime": 1.0,
	}


func _last_toast() -> Toast:
	var box: VBoxContainer = Services.overlay._toast_box
	if box.get_child_count() == 0:
		return null
	return box.get_child(box.get_child_count() - 1) as Toast


## Fires the labeled button inside an open confirm modal (recursive).
func _press_modal_button(root: Node, label: String) -> bool:
	for child: Node in root.get_children():
		if child is Button and (child as Button).text == label:
			(child as Button).pressed.emit()
			return true
		if _press_modal_button(child, label):
			return true
	return false


func _reset_export_dir() -> void:
	DirAccess.make_dir_recursive_absolute(_EXPORT_DIR)
	for file: String in DirAccess.get_files_at(_EXPORT_DIR):
		DirAccess.remove_absolute(_EXPORT_DIR.path_join(file))
