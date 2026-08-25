extends GdUnitTestSuite
## StoryRail (M3-C2): header, beat entry ordering (newest last), ink dimming
## of older prose, accent stamps, and the RE-TOLD suffix.


func _theme() -> PackTheme:
	var t := PackTheme.new()
	t.ink = Color("E6EBF7")
	t.muted = Color("7C88A8")
	t.accent = Color("F5A623")
	t.danger = Color("E5484D")
	return t


func _fresh_rail() -> StoryRail:
	var rail: StoryRail = auto_free(StoryRail.new())
	add_child(rail)
	rail.setup(_theme())
	return rail


func _entries(rail: StoryRail) -> VBoxContainer:
	# rail layout: [header, scroll(entries)]
	return rail.get_child(1).get_child(0)


func test_header_and_fixed_width() -> void:
	var rail := _fresh_rail()
	assert_that(rail.custom_minimum_size).is_equal(Vector2(300, 0))
	assert_str(rail.get_child(0).text).is_equal("THE STORY SO FAR")
	assert_that(rail.get_child(0).get_theme_color("font_color")).is_equal(_theme().accent)


func test_beats_land_newest_last_in_order() -> void:
	var rail := _fresh_rail()
	rail.add_beat("ORIGIN \u00B7 AGE 18", "The rain taught her patience.")
	rail.add_beat("TERM 1 \u00B7 COURIER DUTY", "She learned the beacon line.")
	rail.add_beat("TERM 2 \u00B7 SURVEY DUTY", "The charts were worth more than the pay.")
	var entries := _entries(rail)
	assert_that(entries.get_child_count()).is_equal(3)
	assert_int(rail.beat_count()).is_equal(3)
	assert_str(entries.get_child(0).get_child(0).text).is_equal("ORIGIN \u00B7 AGE 18")
	assert_str(entries.get_child(1).get_child(0).text).is_equal("TERM 1 \u00B7 COURIER DUTY")
	assert_str(entries.get_child(2).get_child(0).text).is_equal("TERM 2 \u00B7 SURVEY DUTY")
	assert_str(entries.get_child(2).get_child(1).text).is_equal(
		"The charts were worth more than the pay."
	)


func test_only_the_newest_prose_is_full_ink() -> void:
	var rail := _fresh_rail()
	rail.add_beat("ORIGIN \u00B7 AGE 18", "Old prose.")
	rail.add_beat("TERM 1 \u00B7 COURIER DUTY", "New prose.")
	var entries := _entries(rail)
	var old_prose: Label = entries.get_child(0).get_child(1)
	var new_prose: Label = entries.get_child(1).get_child(1)
	assert_that(old_prose.modulate.a).is_equal_approx(0.7, 0.001)
	assert_that(new_prose.modulate.a).is_equal(1.0)
	# Stamps stay accent on every entry, old or new.
	assert_that(entries.get_child(0).get_child(0).get_theme_color("font_color")).is_equal(
		_theme().accent
	)
	assert_that(entries.get_child(1).get_child(0).get_theme_color("font_color")).is_equal(
		_theme().accent
	)


func test_mark_last_retold_suffixes_the_last_stamp_in_danger() -> void:
	var rail := _fresh_rail()
	rail.add_beat("TERM 1 \u00B7 COURIER DUTY", "First.")
	rail.add_beat("TERM 2 \u00B7 SURVEY DUTY", "Second.")
	rail.mark_last_retold()
	var entries := _entries(rail)
	var last_stamp: Label = entries.get_child(1).get_child(0)
	var first_stamp: Label = entries.get_child(0).get_child(0)
	assert_str(last_stamp.text).is_equal("TERM 2 \u00B7 SURVEY DUTY \u2014 RE-TOLD")
	assert_that(last_stamp.get_theme_color("font_color")).is_equal(_theme().danger)
	# The earlier stamp is untouched.
	assert_str(first_stamp.text).is_equal("TERM 1 \u00B7 COURIER DUTY")
	assert_that(first_stamp.get_theme_color("font_color")).is_equal(_theme().accent)


func test_mark_last_retold_on_an_empty_rail_is_a_noop() -> void:
	var rail := _fresh_rail()
	rail.mark_last_retold()
	assert_int(rail.beat_count()).is_equal(0)
	assert_that(_entries(rail).get_child_count()).is_equal(0)


func test_rebuild_keeps_the_newest_beat_in_view() -> void:
	# The full teardown would clamp the scroll to the top, parking the
	# newest beat below the fold; the deferred snap must undo that.
	var rail := _fresh_rail()
	rail._scroll.custom_minimum_size = Vector2(300, 90)
	var long_prose := "The beacons lied about the weather for a week straight, and the crew "
	for i: int in 8:
		rail.add_beat("TERM %d \u00B7 SURVEY DUTY" % (i + 1), long_prose + str(i))
	await get_tree().create_timer(0.1).timeout  # let the deferred snap run
	var bar := rail._scroll.get_v_scroll_bar()
	assert_float(bar.max_value).is_greater(0.0)  # content genuinely overflows
	# Bottom = max − page (the scrollbar clamps there); approx absorbs the
	# integer rounding of scroll_vertical.
	assert_float(float(rail._scroll.scroll_vertical)).is_equal_approx(bar.max_value - bar.page, 2.0)
