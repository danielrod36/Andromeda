extends GdUnitTestSuite
## SheetDrawer (M3-C4): the pushed sheet overlay — data loads from /sheet,
## ESC pops, an error toasts and pops, only verified fields render.

const _SHEET := {
	"character":
	{
		"name": "Mara Voss",
		"characteristics": {"STR": 9, "DEX": 11, "END": 7, "INT": 8, "EDU": 5, "SOC": 4},
		"skills": {"pilot": 2, "vacc_suit": 1},
		"age": 22,
		"terms": 1,
		"career": "scout",
		"rank": 1,
		"credits": 12000,
	},
	"characteristic_dms": {"STR": 1, "DEX": 1, "END": 0, "INT": 0, "EDU": -1, "SOC": -1},
	"skill_names": {"pilot": "Pilot", "vacc_suit": "Vacc Suit"},
}

var _fake: FakeEngineClient
var _drawer: SheetDrawer


func before() -> void:
	ClientSettings.use_test_path()


func before_test() -> void:
	_fake = auto_free(FakeEngineClient.new())
	add_child(_fake)
	Services.overlay = auto_free(OverlayLayer.new())
	add_child(Services.overlay)
	_drawer = auto_free(SheetDrawer.new())
	_drawer.client_override = _fake
	add_child(_drawer)


func after_test() -> void:
	Services.overlay = null
	await get_tree().process_frame
	await get_tree().process_frame


func _open(data: Dictionary = _SHEET) -> void:
	_fake.responses["sheet"] = FakeEngineClient.ok(data)
	_drawer.screen_enter({"session": {"id": "sess-c4", "kind": "chargen"}})
	await get_tree().create_timer(0.05).timeout


func _label_texts() -> Array:
	var labels: Array = []
	if not is_instance_valid(_drawer._content_box):
		return labels
	for node: Node in _drawer._content_box.find_children("*", "Label", true, false):
		labels.append((node as Label).text)
	return labels


func test_sheet_renders_name_career_terms_age_and_stats() -> void:
	await _open()
	assert_bool(_drawer._loading_label.visible).is_false()
	var labels := _label_texts()
	assert_bool(labels.has("Mara Voss")).is_true()
	assert_bool(labels.has("SCOUT · 1 TERM · AGE 22")).is_true()
	assert_bool(labels.has("SKILLS")).is_true()
	assert_bool(labels.has("PILOT-2 · VACC SUIT-1")).is_true()
	assert_bool(labels.has("CR 12000")).is_true()
	var stat_rows := _drawer._content_box.find_children("*", "StatRow", true, false)
	assert_that(stat_rows).has_size(6)


func test_unset_fields_render_gracefully() -> void:
	var empty := {
		"character": {"name": "", "characteristics": {}, "skills": {}, "age": 0, "terms": 0},
		"characteristic_dms": {},
		"skill_names": {},
	}
	await _open(empty)
	var labels := _label_texts()
	assert_bool(labels.has("NAME UNDECIDED")).is_true()
	assert_bool(not labels.has("SKILLS")).is_true()


func test_esc_pops_the_drawer() -> void:
	await _open()
	# The drawer's ESC handler routes through _pop; stub it and drive the
	# key (the stack wiring itself is exercised by the chargen suite).
	var popped := {"count": 0}
	_drawer.pop_requested.connect(func() -> void: popped["count"] += 1)
	var key := InputEventKey.new()
	key.pressed = true
	key.keycode = KEY_ESCAPE
	_drawer._unhandled_input(key)
	await get_tree().process_frame
	assert_int(int(popped["count"])).is_equal(1)


func test_error_toasts_and_pops() -> void:
	_fake.responses["sheet"] = FakeEngineClient.err(404, "session_not_found", "no such session")
	var popped := {"count": 0}
	_drawer.pop_requested.connect(func() -> void: popped["count"] += 1)
	_drawer.screen_enter({"session": {"id": "gone", "kind": "chargen"}})
	await get_tree().create_timer(0.05).timeout
	assert_int(int(popped["count"])).is_equal(1)
	assert_int(Services.overlay._toast_box.get_child_count()).is_equal(1)
