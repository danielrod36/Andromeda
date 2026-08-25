extends GdUnitTestSuite
## RollReadout (M3-C2): receipt parsing, full/compact/table forms from canned
## RollResults (incl. natural 2/12 frames), and the stamp-landing tween.

const SURVIVAL_ROLL := {
	"stream": "survival", "ndice": 2, "sides": 6, "modifiers": 1, "rolls": [2, 6], "total": 9
}
const SURVIVAL_RECEIPT := "Survival: 2D6(8)+DM(1)=9 vs 6 -> success"
const FUMBLE_ROLL := {
	"stream": "survival", "ndice": 2, "sides": 6, "modifiers": 0, "rolls": [1, 1], "total": 2
}
const FUMBLE_RECEIPT := "Survival: 2D6(2)+DM(0)=2 vs 6 -> failure"
const BOOM_ROLL := {
	"stream": "survival", "ndice": 2, "sides": 6, "modifiers": 0, "rolls": [6, 6], "total": 12
}
const BOOM_RECEIPT := "Survival: 2D6(12)+DM(0)=12 vs 6 -> success"
const AGING_ROLL := {
	"stream": "aging", "ndice": 2, "sides": 6, "modifiers": -5, "rolls": [2, 2], "total": -1
}

var _t: PackTheme


func before_test() -> void:
	ClientSettings.use_test_path()
	ClientSettings.set_value("reading/reduced_motion", false)
	_t = PackTheme.new()
	_t.bg = Color("0A0F1E")
	_t.panel = Color("101830")
	_t.line = Color("27345C")
	_t.ink = Color("E6EBF7")
	_t.muted = Color("7C88A8")
	_t.accent = Color("F5A623")
	_t.ok = Color("46C48A")
	_t.danger = Color("E5484D")


func after_test() -> void:
	ClientSettings.set_value("reading/reduced_motion", false)


func _fresh_readout() -> RollReadout:
	var r: RollReadout = auto_free(RollReadout.new())
	add_child(r)
	r.setup(_t)
	return r


func _top_row(r: RollReadout) -> HBoxContainer:
	# root layout: [pad, top row, pad]
	assert_that(r.get_child_count()).is_equal(3)
	return r.get_child(1)


# ---- parse_receipt ----------------------------------------------------------


func test_parse_receipt_reads_the_example_line() -> void:
	var parsed := RollReadout.parse_receipt(SURVIVAL_RECEIPT)
	(
		assert_that(parsed)
		. is_equal(
			{
				"label": "Survival",
				"dm": 1,
				"total": 9,
				"target": 6,
				"outcome": "success",
				"tier": "",
			}
		)
	)


func test_parse_receipt_reads_negative_dm_and_tier() -> void:
	var parsed := RollReadout.parse_receipt("Advancement: 2D6(5)+DM(-2)=3 vs 7 -> failure narrow")
	assert_that(parsed["dm"]).is_equal(-2)
	assert_that(parsed["target"]).is_equal(7)
	assert_that(parsed["outcome"]).is_equal("failure")
	assert_that(parsed["tier"]).is_equal("narrow")


func test_parse_receipt_rejects_malformed_lines() -> void:
	assert_dict(RollReadout.parse_receipt("")).is_empty()
	assert_dict(RollReadout.parse_receipt("no colon at all")).is_empty()
	assert_dict(RollReadout.parse_receipt("Survival: 2D6(8)+DM(1)=9 vs 6")).is_empty()
	assert_dict(RollReadout.parse_receipt("Survival: garbage")).is_empty()
	assert_dict(RollReadout.parse_receipt(": 2D6(8)+DM(1)=9 vs 6 -> success")).is_empty()
	assert_dict(RollReadout.parse_receipt("Survival: 2D6(8)+DM(1)=9 -> success")).is_empty()


# ---- full form --------------------------------------------------------------


func test_full_form_renders_dice_chips_total_target_and_verdict() -> void:
	var r := _fresh_readout()
	r.show_full(SURVIVAL_ROLL, SURVIVAL_RECEIPT)
	var top := _top_row(r)
	assert_that(top.get_child_count()).is_equal(6)

	var dice: HBoxContainer = top.get_child(0)
	assert_that(dice.get_child_count()).is_equal(2)  # one PipDie per roll
	assert_that(dice.get_child(0).pip_value).is_equal(2)
	assert_that(dice.get_child(1).pip_value).is_equal(6)
	assert_that(dice.get_child(0).custom_minimum_size).is_equal(Vector2(30, 30))

	var chip: Label = top.get_child(1).get_child(0)
	assert_str(chip.text).is_equal("+1 SURVIVAL")
	assert_that(chip.get_theme_color("font_color")).is_equal(_t.ok)

	assert_str(top.get_child(2).text).is_equal("=")
	assert_str(top.get_child(3).text).is_equal("9")
	assert_str(top.get_child(4).text).is_equal("vs 6")

	var verdict: Label = top.get_child(5)
	assert_str(verdict.text).is_equal("SUCCESS")
	assert_that(verdict.get_theme_color("font_color")).is_equal(_t.ok)
	assert_that(r._frame_mode).is_equal("line")


func test_full_form_failure_verdict_is_danger() -> void:
	var r := _fresh_readout()
	r.show_full(FUMBLE_ROLL, FUMBLE_RECEIPT)
	var verdict: Label = null
	for node: Node in _top_row(r).get_children():
		if node is Label and (node as Label).text == "FAILURE":
			verdict = node
	assert_that(verdict).is_not_null()
	assert_that(verdict.get_theme_color("font_color")).is_equal(_t.danger)


func test_full_form_negative_dm_chip_is_danger() -> void:
	var r := _fresh_readout()
	r.show_full(AGING_ROLL, "Aging: 2D6(4)+DM(-5)=-1 vs 4 -> failure")
	var chip: Label = _top_row(r).get_child(1).get_child(0)
	assert_str(chip.text).is_equal("\u22125 AGING")
	assert_that(chip.get_theme_color("font_color")).is_equal(_t.danger)


func test_full_form_unparseable_receipt_falls_back_to_roll_modifiers() -> void:
	var r := _fresh_readout()
	r.show_full(SURVIVAL_ROLL, "not a receipt line")
	var top := _top_row(r)
	# dice + chip + = + total — no vs, no verdict
	assert_that(top.get_child_count()).is_equal(4)
	var chip: Label = top.get_child(1).get_child(0)
	assert_str(chip.text).is_equal("+1")


func test_full_form_natural_2_gets_the_accent_frame() -> void:
	var r := _fresh_readout()
	r.show_full(FUMBLE_ROLL, FUMBLE_RECEIPT)
	assert_that(r._frame_mode).is_equal("accent")


func test_full_form_natural_12_gets_the_ok_frame() -> void:
	var r := _fresh_readout()
	r.show_full(BOOM_ROLL, BOOM_RECEIPT)
	assert_that(r._frame_mode).is_equal("ok")


# ---- compact form -----------------------------------------------------------


func test_compact_form_renders_pips_and_chips_only() -> void:
	var r := _fresh_readout()
	r.show_compact(SURVIVAL_ROLL, SURVIVAL_RECEIPT)
	var top := _top_row(r)
	assert_that(top.get_child_count()).is_equal(2)  # dice + chip; no verdict/target
	var dice: HBoxContainer = top.get_child(0)
	assert_that(dice.get_child_count()).is_equal(2)
	assert_that(dice.get_child(0).custom_minimum_size).is_equal(Vector2(18, 18))
	var chip: Label = top.get_child(1).get_child(0)
	assert_str(chip.text).is_equal("+1 SURVIVAL")
	assert_that(r._frame_mode).is_equal("line")
	assert_that(r.custom_minimum_size).is_equal(Vector2(0, 34))


# ---- table form -------------------------------------------------------------


func test_table_form_renders_dice_chip_total_and_result() -> void:
	var r := _fresh_readout()
	r.show_table(AGING_ROLL, "AGING TABLE: \u22122 PHYSICAL \u00D72 SLOTS")
	var top := _top_row(r)
	assert_that(top.get_child_count()).is_equal(5)  # dice, chip, =, total, result
	var chip: Label = top.get_child(1).get_child(0)
	assert_str(chip.text).is_equal("\u22125")  # no receipt → modifier only
	assert_that(chip.get_theme_color("font_color")).is_equal(_t.danger)
	assert_str(top.get_child(3).text).is_equal("\u22121")
	assert_str(top.get_child(4).text).is_equal("\u2192 AGING TABLE: \u22122 PHYSICAL \u00D72 SLOTS")
	assert_that(r._frame_mode).is_equal("line")


# ---- stamp landing ----------------------------------------------------------


func test_stamp_landing_tweens_in_when_motion_allowed() -> void:
	var r := _fresh_readout()
	r.show_full(SURVIVAL_ROLL, SURVIVAL_RECEIPT)
	assert_that(r.scale).is_equal(Vector2(0.9, 0.9))
	assert_that(r.modulate.a).is_equal_approx(0.2, 0.001)
	await get_tree().create_timer(0.25).timeout
	assert_that(r.scale).is_equal(Vector2.ONE)
	assert_that(r.modulate.a).is_equal(1.0)


func test_reduced_motion_snaps_the_landing() -> void:
	ClientSettings.set_value("reading/reduced_motion", true)
	var r := _fresh_readout()
	r.show_full(SURVIVAL_ROLL, SURVIVAL_RECEIPT)
	assert_that(r.scale).is_equal(Vector2.ONE)
	assert_that(r.modulate.a).is_equal(1.0)


func test_presentation_tree_never_swallows_clicks() -> void:
	# The readout overlays interactive stages; every node in its subtree
	# must pass clicks through (bare Controls default to STOP).
	var r := _fresh_readout()
	r.show_full(SURVIVAL_ROLL, SURVIVAL_RECEIPT)
	assert_int(r.mouse_filter).is_equal(Control.MOUSE_FILTER_IGNORE)
	assert_int(r.get_child(0).mouse_filter).is_equal(Control.MOUSE_FILTER_IGNORE)  # pad
	assert_int(r.get_child(2).mouse_filter).is_equal(Control.MOUSE_FILTER_IGNORE)  # pad
	var top: HBoxContainer = r.get_child(1)
	assert_int(top.mouse_filter).is_equal(Control.MOUSE_FILTER_IGNORE)
	for node: Node in top.get_children():
		assert_int(node.mouse_filter).is_equal(Control.MOUSE_FILTER_IGNORE)


func test_zero_dm_receipt_parses_with_verdict_and_no_chip() -> void:
	# The server omits +DM(0) entirely (lifepath.py:1785) — the DM segment
	# must be optional or every zero-DM roll loses its verdict.
	var zero_dm := "Survival: 2D6(8)=9 vs 6 -> success"
	var parsed := RollReadout.parse_receipt(zero_dm)
	assert_int(int(parsed["dm"])).is_equal(0)
	assert_int(int(parsed["total"])).is_equal(9)
	assert_int(int(parsed["target"])).is_equal(6)
	assert_str(str(parsed["outcome"])).is_equal("success")
	var r := _fresh_readout()
	r.show_full(SURVIVAL_ROLL, zero_dm)
	var texts := _label_texts(r)
	assert_bool(texts.has("vs 6")).is_true()
	assert_bool(texts.has("SUCCESS")).is_true()
	assert_bool(not texts.has("+0")).is_true()  # zero DM renders no chip


func test_reenlistment_shape_parses_and_keeps_text_target() -> void:
	# `Re-enlistment: 2D6=7 vs 6 -> success` and the `vs —` variant.
	var parsed := RollReadout.parse_receipt("Re-enlistment: 2D6=7 vs 6 -> success")
	assert_str(str(parsed["label"])).is_equal("Re-enlistment")
	assert_int(int(parsed["dm"])).is_equal(0)
	assert_int(int(parsed["total"])).is_equal(7)
	var dash := RollReadout.parse_receipt("Re-enlistment: 2D6=7 vs \u2014 -> success")
	assert_str(str(dash["target"])).is_equal("\u2014")  # non-numeric stays text
	var r := _fresh_readout()
	r.show_full(
		{"stream": "lifepath", "ndice": 2, "sides": 6, "modifiers": 0, "rolls": [3, 4], "total": 7},
		"Re-enlistment: 2D6=7 vs \u2014 -> success"
	)
	assert_bool(_label_texts(r).has("vs \u2014")).is_true()


func test_non_2d6_rolls_never_get_natural_frames() -> void:
	# 3D6 summing 12 (or a lone die showing 2) is not a natural — no frame.
	var three_d := {
		"stream": "cascade", "ndice": 3, "sides": 6, "modifiers": 0, "rolls": [3, 4, 5], "total": 12
	}
	var r := _fresh_readout()
	r.show_full(three_d, "Cascade: 2D6(12)=12 vs 8 -> success")
	assert_str(r._frame_mode).is_equal("line")


func test_back_to_back_show_calls_never_overlap_tweens() -> void:
	var r := _fresh_readout()
	r.show_full(SURVIVAL_ROLL, SURVIVAL_RECEIPT)
	r.show_full(FUMBLE_ROLL, FUMBLE_RECEIPT)  # kills the first landing
	await get_tree().create_timer(0.3).timeout
	assert_that(r.scale).is_equal(Vector2.ONE)
	assert_that(r.modulate.a).is_equal(1.0)


func _label_texts(r: RollReadout) -> Array:
	var texts: Array = []
	for node: Node in r.find_children("*", "Label", true, false):
		texts.append((node as Label).text)
	return texts
