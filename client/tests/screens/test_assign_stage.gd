extends GdUnitTestSuite
## AssignStage (M3-C5): the pool-assignment stage — chips × stat matrix,
## tap-tap pairing from the option set, once-only reroll, view-only truth.

const _VIEW := {
	"choice_id": "assign_characteristics",
	"phase": "assign_characteristics",
	"prompt": "Assign pool values: [9, 11, 7]",
	"options":
	[
		{
			"option_id": "assign:0:STR",
			"label": "Assign 9 to STR",
			"preview": ["STR becomes 9"],
			"dimmed": false
		},
		{"option_id": "assign:0:DEX", "label": "Assign 9 to DEX", "preview": [], "dimmed": false},
		{"option_id": "assign:1:STR", "label": "Assign 11 to STR", "preview": [], "dimmed": false},
		{"option_id": "assign:1:INT", "label": "Assign 11 to INT", "preview": [], "dimmed": false},
		{"option_id": "reroll_pool", "label": "Reroll Pool", "preview": [], "dimmed": false},
	],
	"allows_advisor": true,
	"allows_freetext": false,
	"freetext_hint": "",
}


func _theme() -> PackTheme:
	var t := PackTheme.new()
	t.panel = Color("101830")
	t.line = Color("27345C")
	t.ink = Color("E6EBF7")
	t.muted = Color("7C88A8")
	t.accent = Color("F5A623")
	t.ok = Color("46C48A")
	t.danger = Color("E5484D")
	return t


func _fresh_stage(view: Dictionary = _VIEW) -> AssignStage:
	var stage: AssignStage = auto_free(AssignStage.new())
	add_child(stage)
	stage.setup(_theme())
	stage.build_from_view(view, func(_id: String) -> void: pass)
	return stage


func test_pool_and_unassigned_derive_from_the_option_set() -> void:
	var stage := _fresh_stage()
	# Pool values 9, 11 from the labels; STR/DEX/INT unassigned; the rest
	# settled (dimmed, not drop targets).
	assert_that(stage._pool).is_equal(["9", "11"])
	assert_int(stage._chips.size()).is_equal(2)
	# All six rows render; STR/DEX/INT live drop targets, EDU settled.
	assert_bool(stage._stat_rows.has("STR")).is_true()
	assert_bool(stage._stat_rows.has("EDU")).is_true()
	assert_float(float((stage._stat_rows["STR"] as StatRow).modulate.a)).is_equal_approx(1.0, 0.01)
	assert_float(float((stage._stat_rows["EDU"] as StatRow).modulate.a)).is_equal_approx(0.55, 0.01)


func test_stat_tap_without_an_armed_chip_does_nothing() -> void:
	var stage := _fresh_stage()
	var fired: Array = []
	stage.choose_option.connect(func(option_id: String) -> void: fired.append(option_id))
	stage._on_stat_input(_left_click(), "STR", stage._stat_rows["STR"])
	assert_that(fired).is_empty()


func test_second_chip_tap_releases_the_arm() -> void:
	var stage := _fresh_stage()
	(stage._chips[0] as Button).pressed.emit()
	assert_int(stage.armed_pool_index()).is_equal(0)
	(stage._chips[0] as Button).pressed.emit()  # same chip again — toggle off
	assert_int(stage.armed_pool_index()).is_equal(-1)


func test_reroll_button_fires_once_only_option() -> void:
	var stage := _fresh_stage()
	var fired: Array = []
	stage.choose_option.connect(func(option_id: String) -> void: fired.append(option_id))
	assert_bool(stage._reroll_btn != null)
	stage._reroll_btn.pressed.emit()
	assert_that(fired).is_equal(["reroll_pool"])


func test_spent_reroll_is_disabled() -> void:
	var view := (_VIEW as Dictionary).duplicate(true)
	for option: Dictionary in view["options"]:
		if str(option["option_id"]) == "reroll_pool":
			option["dimmed"] = true
			option["requirement"] = "Pool reroll already used"
	var stage := _fresh_stage(view)
	assert_bool(stage._reroll_btn.disabled).is_true()


func test_label_parsing_reads_the_value() -> void:
	assert_str(AssignStage._value_from_label("Assign 12 to SOC")).is_equal("12")
	assert_str(AssignStage._value_from_label("weird")).is_equal("?")


func _left_click() -> InputEventMouseButton:
	var click := InputEventMouseButton.new()
	click.pressed = true
	click.button_index = MOUSE_BUTTON_LEFT
	return click
