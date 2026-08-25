# gdlint: ignore=max-public-methods
extends GdUnitTestSuite
## Ceremony screen against FakeEngineClient + FakeStreamPump (mock 04):
## fate docket auto-advance, the world-intro beat (SKIP/CONTINUE/RETRY),
## the name commit, and ESC → abandon behind a confirm.
##
## Known harness artifact: this suite reports ~1 orphan per test on the
## pinned Godot 4.7.1 (gdUnit exit 101 — warnings-only; the gate passes).
## Bisected to the LineEdit creation in the name beat: with the LineEdit
## skipped the count is 0; standalone probes (LineEdit + text + focus +
## rebuild cycles, freed) report 0 orphans, so the leak is internal to the
## gdUnit harness/LineEdit interplay, not a leak in this screen's tree.

const _SESSION := {
	"id": "sess-c1",
	"name": "The Ruuth Run",
	"kind": "chargen",
	"phase": "homeworld",
	"view": null,
	"contract_version": 1,
	"seed": 482991,
	"death_mode": "narrative",
}

var _fake: FakeEngineClient
var _pump: FakeStreamPump
var _screen: CeremonyScreen


func before() -> void:
	ClientSettings.use_test_path()


func before_test() -> void:
	ClientSettings.set_value("reading/reduced_motion", false)
	# Blocks land instantly at the reader's speed — the suite drives timing
	# itself instead of racing the typewriter.
	ClientSettings.set_value("reading/text_speed", "instant")
	_fake = auto_free(FakeEngineClient.new())
	add_child(_fake)
	_pump = auto_free(FakeStreamPump.new())
	add_child(_pump)
	_fake.responses["delete_session"] = FakeEngineClient.ok({})
	Services.overlay = auto_free(OverlayLayer.new())
	add_child(Services.overlay)
	_screen = await _fresh_screen()
	# Await the beat-1 hold so most tests start at the intro beat (beat 2).
	await get_tree().create_timer(1.4).timeout


func after_test() -> void:
	ClientSettings.set_value("reading/reduced_motion", false)
	ClientSettings.set_value("reading/text_speed", "medium")
	PackThemes.apply("neutral")
	Services.overlay = null
	SessionStore.clear()


func _fresh_screen() -> CeremonyScreen:
	var screen: CeremonyScreen = auto_free(CeremonyScreen.new())
	screen.client_override = _fake
	screen.pump_override = _pump
	add_child(screen)
	screen.screen_enter({"session": _SESSION})
	return screen


## A screen stopped at the fate beat (beat 1), with its OWN pump — the
## suite-level `_pump.start_calls` must not collect the beat-1 screens'
## auto-advance calls. screen_enter is called but never awaited, so the
## ~1.2s auto-advance has not fired yet.
func _screen_at_beat_one() -> Array:
	var pump: FakeStreamPump = auto_free(FakeStreamPump.new())
	add_child(pump)
	var screen: CeremonyScreen = auto_free(CeremonyScreen.new())
	screen.client_override = _fake
	screen.pump_override = pump
	add_child(screen)
	screen.screen_enter({"session": _SESSION})
	return [screen, pump]


func _intro_blocks() -> Array:
	return [
		{"type": "narration", "content": "The Spinward frontier does not care about you."},
		{"type": "narration", "content": "A thousand beacons burn out past the jump limit."},
		{"type": "change", "content": "WORLD · SPINWARD REACH"},
		{"type": "done", "content": ""},
	]


## Fires the labeled button inside an open modal (recursive).
func _press_modal_button(root: Node, label: String) -> bool:
	for child: Node in root.get_children():
		if child is Button and (child as Button).text == label:
			(child as Button).pressed.emit()
			return true
		if _press_modal_button(child, label):
			return true
	return false


func _last_toast() -> Toast:
	var box: VBoxContainer = Services.overlay._toast_box
	if box.get_child_count() == 0:
		return null
	return box.get_child(box.get_child_count() - 1) as Toast


## Advance through beats 1+2 to the name beat (beat 3).
func _enter_name_beat() -> void:
	_pump.play_forward(_intro_blocks())
	_screen.press_continue()


# --- beat 1: fate seeded ------------------------------------------------------


func test_fate_beat_shows_the_seed_docket() -> void:
	var ctx := _screen_at_beat_one()
	var screen: CeremonyScreen = ctx[0]
	assert_bool(screen._beat_fate.visible).is_true()
	assert_str(screen._seed_label.text).is_equal("FATE SEEDED · 482991")
	assert_bool(screen._beat_intro.visible).is_false()
	assert_bool(screen._beat_name.visible).is_false()
	assert_bool(screen._intro_bar.visible).is_false()


func test_fate_beat_auto_advances_to_the_world_intro() -> void:
	var ctx := _screen_at_beat_one()
	var screen: CeremonyScreen = ctx[0]
	var pump: FakeStreamPump = ctx[1]
	await get_tree().create_timer(1.4).timeout
	assert_bool(screen._beat_fate.visible).is_false()
	assert_bool(screen._beat_intro.visible).is_true()
	assert_bool(screen._intro_bar.visible).is_true()
	# The world intro stream started on auto-advance.
	assert_that(pump.start_calls).has_size(1)
	assert_str(str(pump.start_calls[0]["beat"])).is_equal("world_intro")
	assert_str(str(pump.start_calls[0]["session_id"])).is_equal("sess-c1")


func test_fate_beat_auto_advances_fast_under_reduced_motion() -> void:
	ClientSettings.set_value("reading/reduced_motion", true)
	var ctx := _screen_at_beat_one()
	var screen: CeremonyScreen = ctx[0]
	var pump: FakeStreamPump = ctx[1]
	await get_tree().create_timer(0.6).timeout
	assert_bool(screen._beat_intro.visible).is_true()
	assert_that(pump.start_calls).has_size(1)


# --- beat 2: world intro --------------------------------------------------------


func test_intro_blocks_feed_the_typewriter() -> void:
	assert_bool(_screen._continue_btn.disabled).is_true()
	# Feed the narration blocks WITHOUT the terminator so the text grows
	# mid-stream (play_forward would finish the beat before the assert).
	_pump.block_received.emit("narration", "The Spinward frontier does not care about you.")
	var shown := _screen._prose.visible_text()
	assert_bool(shown.contains("Spinward frontier")).is_true()
	assert_bool(_screen._continue_btn.disabled).is_true()
	_pump.block_received.emit("narration", "A thousand beacons burn out past the jump limit.")
	assert_bool(_screen._prose.visible_text().contains("A thousand beacons")).is_true()
	assert_bool(_screen._continue_btn.disabled).is_true()


func test_intro_continue_unlocks_when_the_stream_finishes() -> void:
	assert_bool(_screen._continue_btn.disabled).is_true()
	assert_bool(_screen._skip_link.visible).is_true()
	_pump.play_forward(_intro_blocks())
	assert_bool(_screen._continue_btn.disabled).is_false()
	assert_bool(_screen._skip_link.visible).is_false()
	assert_bool(_screen._prose.visible_text().contains("A thousand beacons")).is_true()


func test_skip_completes_the_text_and_unlocks_continue() -> void:
	_pump.block_received.emit("narration", "The Spinward frontier does not care about you.")
	_pump.block_received.emit("narration", "A thousand beacons burn out past the jump limit.")
	_screen.press_skip()
	assert_int(_pump.stop_count).is_equal(1)
	assert_bool(_screen._prose.is_typing()).is_false()
	assert_bool(_screen._prose.visible_text().contains("A thousand beacons")).is_true()
	assert_bool(_screen._continue_btn.disabled).is_false()


func test_skip_is_ignored_once_unlocked() -> void:
	_pump.play_forward(_intro_blocks())
	var stops := _pump.stop_count
	_screen.press_skip()  # the microlink is hidden after completion
	assert_int(_pump.stop_count).is_equal(stops)


func test_intro_failure_toasts_and_offers_retry_while_continue_stays_usable() -> void:
	_pump.fail("could not reach the referee")
	assert_str(_last_toast()._message).is_equal("could not reach the referee")
	assert_str(_last_toast()._kind).is_equal("bad")
	assert_bool(_screen._retry_btn.visible).is_true()
	assert_bool(_screen._skip_link.visible).is_false()
	assert_bool(_screen._continue_btn.disabled).is_false()  # degraded path


func test_retry_re_runs_the_world_intro() -> void:
	_pump.fail("could not reach the referee")
	_screen.press_retry()
	assert_that(_pump.start_calls).has_size(2)
	assert_str(str(_pump.start_calls[1]["beat"])).is_equal("world_intro")
	assert_bool(_screen._retry_btn.visible).is_false()
	assert_bool(_screen._continue_btn.disabled).is_true()
	_pump.play_forward(_intro_blocks())
	assert_bool(_screen._continue_btn.disabled).is_false()


func test_continue_moves_to_the_name_beat() -> void:
	_pump.play_forward(_intro_blocks())
	_screen.press_continue()
	assert_bool(_screen._beat_intro.visible).is_false()
	assert_bool(_screen._intro_bar.visible).is_false()
	assert_bool(_screen._beat_name.visible).is_true()


# --- beat 3: the name ---------------------------------------------------------


func test_take_up_stays_disabled_on_empty_or_blank_input() -> void:
	_enter_name_beat()
	assert_bool(_screen._take_up_btn.disabled).is_true()
	_screen._name_edit.text = "   "
	_screen._on_name_changed(_screen._name_edit.text)
	assert_bool(_screen._take_up_btn.disabled).is_true()
	_screen._name_edit.text = "Branwen"
	_screen._on_name_changed(_screen._name_edit.text)
	assert_bool(_screen._take_up_btn.disabled).is_false()


func test_name_input_caps_at_eighty_characters() -> void:
	_enter_name_beat()
	assert_int(_screen._name_edit.max_length).is_equal(80)
	var overflow := "A".repeat(85)
	_screen._name_edit.text = overflow
	_screen._on_name_changed(_screen._name_edit.text)
	assert_int(_screen._name_edit.text.length()).is_equal(80)
	_fake.responses["set_character_name"] = (FakeEngineClient.ok(
		{"session": _named_session(_screen._name_edit.text)}
	))
	_screen.press_take_up()
	await get_tree().process_frame
	var names := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "set_character_name")
	assert_str(str(names[0][2])).is_equal("A".repeat(80))
	SessionStore.clear()


func test_name_commit_strips_edges_and_navigates_chargen() -> void:
	_enter_name_beat()
	var returned := _named_session("Branwen")
	_fake.responses["set_character_name"] = FakeEngineClient.ok({"session": returned})
	_screen._name_edit.text = "  Branwen  "
	_screen._on_name_changed(_screen._name_edit.text)
	var nav: Array = []
	_screen.navigate.connect(
		func(target: String, params: Dictionary) -> void: nav.append([target, params])
	)
	_screen.press_take_up()
	await get_tree().process_frame
	var names := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "set_character_name")
	assert_that(names).has_size(1)
	assert_str(str(names[0][1])).is_equal("sess-c1")
	assert_str(str(names[0][2])).is_equal("Branwen")
	assert_that(SessionStore.current).is_equal(returned)
	assert_that(nav).has_size(1)
	assert_str(str(nav[0][0])).is_equal("chargen")
	assert_that(nav[0][1]["session"]).is_equal(returned)
	SessionStore.clear()


func test_enter_in_the_name_field_commits() -> void:
	_enter_name_beat()
	_fake.responses["set_character_name"] = FakeEngineClient.ok(
		{"session": _named_session("Branwen")}
	)
	_screen._name_edit.text = "Branwen"
	_screen._on_name_changed(_screen._name_edit.text)
	_screen._on_name_submitted("Branwen")
	await get_tree().process_frame
	var names := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "set_character_name")
	assert_that(names).has_size(1)
	assert_str(str(names[0][2])).is_equal("Branwen")
	SessionStore.clear()


func test_name_commit_failure_toasts_and_keeps_the_beat() -> void:
	_enter_name_beat()
	_fake.responses["set_character_name"] = (FakeEngineClient.err(
		422, "invalid_choice", "name must be 80 characters or fewer"
	))
	_screen._name_edit.text = "Branwen"
	_screen._on_name_changed(_screen._name_edit.text)
	var nav: Array = []
	_screen.navigate.connect(
		func(target: String, params: Dictionary) -> void: nav.append([target, params])
	)
	_screen.press_take_up()
	await get_tree().process_frame
	assert_str(_last_toast()._message).is_equal("name must be 80 characters or fewer")
	assert_that(nav).is_empty()
	assert_bool(_screen._beat_name.visible).is_true()
	assert_bool(SessionStore.has_session()).is_false()


# --- ESC: abandon this fate ---------------------------------------------------


func _esc_key() -> InputEventKey:
	var key := InputEventKey.new()
	key.pressed = true
	key.keycode = KEY_ESCAPE
	return key


func test_esc_confirms_then_deletes_and_returns_to_title() -> void:
	_fake.responses["delete_session"] = FakeEngineClient.ok({})
	var nav: Array = []
	_screen.navigate.connect(
		func(target: String, params: Dictionary) -> void: nav.append([target, params])
	)
	_screen._unhandled_input(_esc_key())
	await get_tree().process_frame
	assert_bool(_press_modal_button(Services.overlay, "ABANDON")).is_true()
	await get_tree().process_frame
	var deletes := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "delete_session")
	assert_that(deletes).has_size(1)
	assert_str(str(deletes[0][1])).is_equal("sess-c1")
	assert_that(nav).has_size(1)
	assert_str(str(nav[0][0])).is_equal("title")


func test_esc_cancel_keeps_the_fate() -> void:
	var nav: Array = []
	_screen.navigate.connect(
		func(target: String, params: Dictionary) -> void: nav.append([target, params])
	)
	_screen._unhandled_input(_esc_key())
	await get_tree().process_frame
	assert_bool(_press_modal_button(Services.overlay, "STAY")).is_true()
	await get_tree().process_frame
	var deletes := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "delete_session")
	assert_that(deletes).is_empty()
	assert_that(nav).is_empty()


func test_esc_is_ignored_while_the_confirm_is_open() -> void:
	# The open modal owns ESC (overlay mounts after the stack — main.gd); a
	# second ESC while it is up must not stack a second confirm.
	_fake.responses["delete_session"] = FakeEngineClient.ok({})
	_screen._unhandled_input(_esc_key())
	await get_tree().process_frame
	_screen._unhandled_input(_esc_key())
	await get_tree().process_frame
	assert_bool(_press_modal_button(Services.overlay, "ABANDON")).is_true()
	await get_tree().process_frame
	var deletes := _fake.calls.filter(func(c: Array) -> bool: return c[0] == "delete_session")
	assert_that(deletes).has_size(1)


func test_screen_enter_without_a_session_navigates_title() -> void:
	var screen: CeremonyScreen = auto_free(CeremonyScreen.new())
	screen.client_override = _fake
	screen.pump_override = _pump
	add_child(screen)
	var nav: Array = []
	screen.navigate.connect(
		func(target: String, params: Dictionary) -> void: nav.append([target, params])
	)
	screen.screen_enter({"session": null})
	assert_that(nav).has_size(1)
	assert_str(str(nav[0][0])).is_equal("title")
	assert_str(screen.esc_target()).is_equal("title")


# --- helpers ------------------------------------------------------------------


func _named_session(char_name: String) -> Dictionary:
	var session := (_SESSION as Dictionary).duplicate()
	session["character_name"] = char_name
	return session
