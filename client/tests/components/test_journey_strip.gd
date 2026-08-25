extends GdUnitTestSuite
## JourneyStrip (M3-C2): phase → segment mapping for every chargen phase,
## the here-marker, done dimming, and the all-done states.


func _theme() -> PackTheme:
	var t := PackTheme.new()
	t.ink = Color("E6EBF7")
	t.muted = Color("7C88A8")
	t.accent = Color("F5A623")
	t.line = Color("27345C")
	return t


func _fresh_strip() -> JourneyStrip:
	var strip: JourneyStrip = auto_free(JourneyStrip.new())
	add_child(strip)
	strip.setup(_theme())
	return strip


## Segment labels sit at even child indices (odd indices are · separators).
func _segment_labels(strip: JourneyStrip) -> Array:
	var labels: Array = []
	var children := strip.get_children()
	for i: int in children.size():
		if i % 2 == 0:
			labels.append(children[i])
	return labels


func test_every_phase_maps_to_its_segment() -> void:
	var cases := {
		"roll_characteristics": 1,
		"assign_characteristics": 2,
		"choose_background_skills": 3,
		"choose_career": 4,
		"choose_qualification_fallback": 4,
		"choose_career_change": 4,
		"run_survival": 5,
		"choose_commission": 5,
		"choose_advancement": 5,
		"choose_skills": 5,
		"choose_specialization": 5,
		"choose_basic_training_skill": 5,
		"run_aging": 5,
		"choose_aging_reduction": 5,
		"mishap_roll": 5,
		"choose_injury_stat": 5,
		"choose_crisis_resolution": 5,
		"re_enlist": 5,
		"mustering_out": 6,
		"muster_out_allocate": 6,
	}
	for phase: String in cases:
		var strip := _fresh_strip()
		strip.set_phase(phase)
		var labels := _segment_labels(strip)
		assert_that(labels.size()).is_equal(7)
		var expected: int = cases[phase]
		for i: int in labels.size():
			var label: Label = labels[i]
			if i < expected:
				assert_bool(label.text.begins_with("\u25B8")).is_false()
				assert_that(label.modulate.a).is_equal_approx(0.55, 0.001)  # dimmed ink
			elif i == expected:
				assert_str(label.text).is_equal("\u25B8 %s" % JourneyStrip.SEGMENTS[i])
				assert_that(label.get_theme_color("font_color")).is_equal(_theme().accent)
			else:
				assert_bool(label.text.begins_with("\u25B8")).is_false()
				assert_that(label.modulate.a).is_equal_approx(0.55, 0.001)  # future muted


func test_strip_layout_is_seven_segments_and_six_separators() -> void:
	var strip := _fresh_strip()
	strip.set_phase("assign_characteristics")
	assert_that(strip.get_child_count()).is_equal(13)
	assert_str(strip.get_child(1).text).is_equal("\u00B7")
	assert_that(strip.get_child(1).get_theme_color("font_color")).is_equal(_theme().muted)
	assert_str(strip.get_child(0).text).is_equal("ORIGIN")
	assert_str(strip.get_child(4).text).is_equal("\u25B8 ASSIGN")
	assert_str(strip.get_child(12).text).is_equal("MUSTER")


func test_origin_is_done_for_every_chargen_phase() -> void:
	# The ceremony precedes the shell: once any chargen phase is live,
	# ORIGIN is past — dimmed, never marked current.
	for phase: String in JourneyStrip.SEGMENT_BY_PHASE:
		var strip := _fresh_strip()
		strip.set_phase(phase)
		var origin: Label = strip.get_child(0)
		assert_str(origin.text).is_equal("ORIGIN")
		assert_that(origin.modulate.a).is_equal_approx(0.55, 0.001)


func test_complete_shows_the_whole_journey_done() -> void:
	var strip := _fresh_strip()
	strip.set_phase("complete")
	var labels := _segment_labels(strip)
	for label: Label in labels:
		assert_bool(label.text.begins_with("\u25B8")).is_false()
		assert_that(label.modulate.a).is_equal_approx(0.55, 0.001)


func test_unknown_phase_shows_the_whole_journey_done() -> void:
	var strip := _fresh_strip()
	strip.set_phase("not_a_phase")
	var labels := _segment_labels(strip)
	for label: Label in labels:
		assert_bool(label.text.begins_with("\u25B8")).is_false()


func test_set_phase_redraws_without_leaving_children() -> void:
	var strip := _fresh_strip()
	strip.set_phase("roll_characteristics")
	strip.set_phase("run_survival")
	assert_that(strip.get_child_count()).is_equal(13)
	assert_str(strip.get_child(10).text).is_equal("\u25B8 TERMS")
