# gdlint: ignore=max-public-methods
extends GdUnitTestSuite
## ChargenScreen generic stage (M3-C4): any ChoicePointView renders and is
## playable; the BeatDirector pipeline drives receipts/prose/envelope; the
## shell routes complete→reveal and adventure→stub; reconnect re-fetches.

const _SESSION := {
	"id": "sess-c4",
	"name": "Mara Voss",
	"kind": "chargen",
	"phase": "roll_characteristics",
	"contract_version": 1,
	"seed": 42,
	"death_mode": "narrative",
}

var _fake: FakeEngineClient
var _pump: FakeStreamPump
var _screen: ChargenScreen


static func view_for(phase: String) -> Dictionary:
	return {
		"choice_id": "x",
		"phase": phase,
		"prompt": "Prompt for %s." % phase,
		"options":
		[
			{
				"option_id": "first",
				"label": "First",
				"description": "",
				"preview": ["PV ONE"],
				"odds_line": "DM +1 vs 6+ · 72% FAVORABLE",
				"dimmed": false,
				"requirement": null
			},
			{
				"option_id": "second",
				"label": "Second",
				"description": "",
				"preview": [],
				"odds_line": "DM +0 vs 8+ · 42% CHANCY",
				"dimmed": false,
				"requirement": null
			},
			{
				"option_id": "locked",
				"label": "Locked",
				"description": "",
				"preview": [],
				"odds_line": null,
				"dimmed": true,
				"requirement": "NEEDS EDU 8+"
			},
		],
		"allows_advisor": true,
		"allows_freetext": false,
		"freetext_hint": "",
	}


func before() -> void:
	ClientSettings.use_test_path()


func before_test() -> void:
	ClientSettings.set_value("reading/reduced_motion", true)
	ClientSettings.set_value("reading/text_speed", "instant")
	_fake = auto_free(FakeEngineClient.new())
	add_child(_fake)
	_pump = auto_free(FakeStreamPump.new())
	add_child(_pump)
	_fake.responses["get_session"] = FakeEngineClient.ok({"session": _SESSION})
	var after_choose := (_SESSION as Dictionary).duplicate()
	after_choose["phase"] = "choose_commission"
	after_choose["view"] = view_for("choose_commission")
	_fake.responses["choose"] = FakeEngineClient.ok(
		{"session": after_choose, "result": {}, "events": []}
	)
	_screen = auto_free(ChargenScreen.new())
	_screen.client_override = _fake
	_screen.pump_override = _pump
	add_child(_screen)
	_screen.screen_enter({"session": _SESSION})
	await get_tree().process_frame


func after_test() -> void:
	ClientSettings.set_value("reading/reduced_motion", false)
	ClientSettings.set_value("reading/text_speed", "medium")
	PackThemes.apply("neutral")
	Services.overlay = null
	SessionStore.clear()
	await get_tree().process_frame
	await get_tree().process_frame


func _apply(phase: String) -> void:
	var session := (_SESSION as Dictionary).duplicate()
	session["phase"] = phase
	session["view"] = view_for(phase)
	_screen._apply_envelope(session)


func _cards() -> Array:
	return _screen._cards


# --- generic stage ------------------------------------------------------------


func test_stage_renders_prompt_cards_dimming_and_odds_colors() -> void:
	_apply("choose_career")
	await get_tree().process_frame
	assert_bool(is_instance_valid(_screen._prompt_label)).is_true()
	assert_str(_screen._prompt_label.text).is_equal("Prompt for choose_career.")
	assert_that(_cards()).has_size(3)
	var first: Dictionary = _cards()[0]
	assert_bool(first["dimmed"]).is_false()
	var locked: Dictionary = _cards()[2]
	assert_bool(locked["dimmed"]).is_true()
	assert_float(float((locked["card"] as Control).modulate.a)).is_equal_approx(0.45, 0.01)
	# Odds bands: 72% ok, 42% accent (parsed from the trailing percent).
	var odds_labels := (_cards()[0]["card"] as Control).find_children("*", "Label", true, false)
	var ok_line: Label = odds_labels[1]
	assert_that(ok_line.get_theme_color("font_color")).is_equal(_screen._theme.ok)
	var odds2 := (_cards()[1]["card"] as Control).find_children("*", "Label", true, false)
	assert_that((odds2[1] as Label).get_theme_color("font_color")).is_equal(_screen._theme.accent)


func test_trailing_percent_parses_bands() -> void:
	assert_int(ChargenScreen._trailing_percent("DM +1 vs 6+ · 72% FAVORABLE")).is_equal(72)
	assert_int(ChargenScreen._trailing_percent("58% · MODEST")).is_equal(58)
	assert_int(ChargenScreen._trailing_percent("no percent here")).is_equal(-1)
	assert_int(ChargenScreen._trailing_percent("odds 8 vs 6")).is_equal(-1)


func test_card_press_runs_the_director_with_the_option_id() -> void:
	_apply("run_survival")
	await get_tree().process_frame
	(_cards()[0]["button"] as Button).pressed.emit()
	await get_tree().process_frame
	var runs := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "choose")
	assert_that(runs).has_size(1)
	assert_str(str(runs[0][1])).is_equal("sess-c4")
	assert_str(str(runs[0][2])).is_equal("first")


func test_cards_disable_while_a_beat_is_in_flight() -> void:
	_apply("choose_skills")
	await get_tree().process_frame
	(_cards()[0]["button"] as Button).pressed.emit()
	assert_int(_screen._director.state).is_equal(BeatDirector.State.NARRATING)
	# Mid-beat: every card disabled, including the non-dimmed pair.
	for entry: Dictionary in _cards():
		assert_bool((entry["button"] as Button).disabled).is_true()
	_pump.play_forward([{"type": "narration", "content": "Done."}, {"type": "done", "content": ""}])
	await get_tree().process_frame
	await get_tree().process_frame  # let beat_finished rebuild the stage
	await get_tree().process_frame
	assert_int(_screen._director.state).is_equal(BeatDirector.State.IDLE)
	for entry: Dictionary in _cards():
		var expected: bool = bool(entry["dimmed"])
		assert_bool((entry["button"] as Button).disabled).is_equal(expected)


func test_receipts_render_as_compact_readouts() -> void:
	_apply("run_survival")
	await get_tree().process_frame
	var events := [
		{
			"seq": 1,
			"kind": "roll",
			"command_type": "roll",
			"description": "Survival: 2D6(8)+DM(1)=9 vs 6 -> success",
			"roll":
			{
				"stream": "survival",
				"ndice": 2,
				"sides": 6,
				"modifiers": 1,
				"rolls": [2, 6],
				"total": 9
			}
		},
		{
			"seq": 2,
			"kind": "state_change",
			"command_type": "set_flag",
			"description": "",
			"roll": null
		},
	]
	_screen._on_receipts(events)
	await get_tree().process_frame
	assert_that(_screen._receipts_box.get_child_count()).is_equal(1)  # only the roll event
	assert_bool(_screen._receipts_box.get_child(0) is RollReadout).is_true()


func test_beat_finished_reapplies_the_envelope() -> void:
	_apply("choose_skills")
	await get_tree().process_frame
	var next := (_SESSION as Dictionary).duplicate()
	next["phase"] = "choose_commission"
	next["view"] = view_for("choose_commission")
	_screen._on_beat_finished(next)
	await get_tree().process_frame
	assert_str(_screen._session["phase"]).is_equal("choose_commission")
	assert_that(_cards()).has_size(3)  # rebuilt from the new view


# --- routing ------------------------------------------------------------------


func test_complete_envelope_routes_to_reveal() -> void:
	var nav: Array = []
	_screen.navigate.connect(
		func(target: String, params: Dictionary) -> void: nav.append([target, params])
	)
	var done := (_SESSION as Dictionary).duplicate()
	done["phase"] = "complete"
	done["view"] = null
	_screen._apply_envelope(done)
	assert_that(nav).has_size(1)
	assert_str(str(nav[0][0])).is_equal("reveal")


func test_adventure_kind_routes_to_stub() -> void:
	var nav: Array = []
	_screen.navigate.connect(
		func(target: String, params: Dictionary) -> void: nav.append([target, params])
	)
	var adventure := (_SESSION as Dictionary).duplicate()
	adventure["kind"] = "adventure"
	_screen.screen_enter({"session": adventure})
	assert_that(nav).has_size(1)
	assert_str(str(nav[0][0])).is_equal("stub")


func test_screen_enter_without_a_session_navigates_title() -> void:
	var fresh: ChargenScreen = auto_free(ChargenScreen.new())
	fresh.client_override = _fake
	fresh.pump_override = _pump
	add_child(fresh)
	var nav: Array = []
	fresh.navigate.connect(
		func(target: String, params: Dictionary) -> void: nav.append([target, params])
	)
	fresh.screen_enter({"session": null})
	assert_that(nav).has_size(1)
	assert_str(str(nav[0][0])).is_equal("title")


func test_pop_reentry_with_empty_params_resumes_the_live_session() -> void:
	# pop() re-enters with EMPTY params — the live session means resume,
	# never eject to title (the sheet drawer's close path).
	_apply("choose_career")
	await get_tree().process_frame
	var nav: Array = []
	_screen.navigate.connect(
		func(target: String, params: Dictionary) -> void: nav.append([target, params])
	)
	_screen.screen_enter({})
	assert_that(nav).is_empty()  # no ejection
	assert_str(_screen._session["phase"]).is_equal("choose_career")


func test_reconnect_fetches_the_fresh_envelope() -> void:
	var fresh := (_SESSION as Dictionary).duplicate()
	fresh["phase"] = "assign_characteristics"
	fresh["view"] = view_for("assign_characteristics")
	_fake.responses["get_session"] = FakeEngineClient.ok({"session": fresh})
	_screen.screen_enter({"session": _SESSION})
	await get_tree().create_timer(0.1).timeout
	assert_str(_screen._session["phase"]).is_equal("assign_characteristics")


func test_kicker_uses_chapter_language() -> void:
	assert_str(_screen._kicker_text("roll_characteristics")).is_equal("◤ CHAPTER I — ORIGIN")
	assert_str(_screen._kicker_text("choose_career")).is_equal("◤ CHAPTER II — A TRADE")
	assert_str(_screen._kicker_text("run_survival")).is_equal("◤ CHAPTER III — THE TERMS")
	assert_str(_screen._kicker_text("mustering_out")).is_equal("◤ MUSTERING OUT")
	assert_str(_screen._kicker_text("complete")).is_equal("◤ THE CHARGEN SHELL")
