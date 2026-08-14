extends GdUnitTestSuite
## Settings screen against FakeEngineClient (mock 05).

var _fake: FakeEngineClient
var _screen: SettingsScreen


func before_test() -> void:
	_fake = auto_free(FakeEngineClient.new())
	add_child(_fake)
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
	await _screen.screen_enter({})


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
