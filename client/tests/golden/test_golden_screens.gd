# gdlint: ignore=constant-string-as-default-argument
extends GdUnitTestSuite
## Golden layouts for the four M2 screens (spec M2-D9). Self-skips under the
## headless dummy renderer; runs under xvfb-run/CI and WSLg. Regenerate
## baselines deliberately:
## GOLDEN_UPDATE=1 ANDROMEDA_DISPLAY=1 xvfb-run -a tools/run_client_tests.sh

var _fake: FakeEngineClient


func before_test() -> void:
	if not GoldenAssert.supported():
		return
	_fake = auto_free(FakeEngineClient.new())
	add_child(_fake)
	_fake.responses["llm_status"] = FakeEngineClient.ok(
		{
			"configured": true,
			"model": "claude-sonnet-5",
			"key_backend": "keyring",
			"degraded_line": null
		}
	)
	# determinism: empty save list — relative-time docket notes rot baselines
	_fake.responses["list_saves"] = FakeEngineClient.ok({"saves": []})
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
						"presets": ["claude-sonnet-5"],
						"default_base_url": "https://api.anthropic.com",
						"needs_base_url": false,
					}
				]
			}
		)
	)
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
					}
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


func after_test() -> void:
	if not GoldenAssert.supported():
		return
	ClientSettings.set_value("ui/last_played_pack", "")
	PackThemes.apply("neutral")


func _shoot(screen: BaseScreen, baseline_name: String, params: Dictionary) -> void:
	add_child(auto_free(screen))
	await screen.screen_enter(params)
	await get_tree().process_frame
	await get_tree().process_frame
	var result: Dictionary = GoldenAssert.capture(screen, baseline_name)
	assert_bool(result["match"]).override_failure_message(str(result["stats"])).is_true()


func test_title_golden() -> void:
	if not GoldenAssert.supported():
		return
	var screen := TitleScreen.new()
	screen.client_override = _fake
	await _shoot(
		screen,
		"title",
		{
			"boot_lines":
			[
				"REFEREE: LISTENING · 127.0.0.1:63216",
				"SAVES: OK · DICE STREAMS: PRIMED",
			]
		}
	)


func test_settings_golden() -> void:
	if not GoldenAssert.supported():
		return
	var screen := SettingsScreen.new()
	screen.client_override = _fake
	await _shoot(screen, "settings", {})


func test_chronicles_golden() -> void:
	if not GoldenAssert.supported():
		return
	var screen := ChroniclesScreen.new()
	screen.client_override = _fake
	await _shoot(screen, "chronicles", {})


func test_new_journey_golden() -> void:
	if not GoldenAssert.supported():
		return
	var screen := NewJourneyScreen.new()
	screen.client_override = _fake
	add_child(auto_free(screen))
	await screen.screen_enter({})
	screen._seed_value = 482991  # determinism pin (see task header)
	screen._render_cards()
	await get_tree().process_frame
	await get_tree().process_frame
	var result: Dictionary = GoldenAssert.capture(screen, "new_journey")
	assert_bool(result["match"]).override_failure_message(str(result["stats"])).is_true()
