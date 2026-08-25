extends GdUnitTestSuite
## TypewriterProse (M3-C2): per-character feed at the reader's speed, instant
## change/badge lines, skip, the once-per-stream all_text_shown, and the
## reduced-motion collapse.

const SENTENCE := "The rain on Ruuth Prime taught her patience before the service ever could."


func before() -> void:
	ClientSettings.use_test_path()


func before_test() -> void:
	ClientSettings.set_value("reading/text_speed", "medium")
	ClientSettings.set_value("reading/reduced_motion", false)


func after_test() -> void:
	ClientSettings.set_value("reading/text_speed", "medium")
	ClientSettings.set_value("reading/reduced_motion", false)


func _fresh_prose() -> TypewriterProse:
	var prose: TypewriterProse = auto_free(TypewriterProse.new())
	add_child(prose)
	prose.setup(_theme())
	return prose


func _theme() -> PackTheme:
	var t := PackTheme.new()
	t.ink = Color("E6EBF7")
	t.muted = Color("7C88A8")
	t.accent = Color("F5A623")
	return t


func test_medium_speed_types_partway_at_half_a_second() -> void:
	var prose := _fresh_prose()
	prose.feed("narration", SENTENCE)
	await get_tree().create_timer(0.5).timeout
	var shown := prose.visible_text()
	# Partial: some chars landed (caret attached), the full sentence has not.
	assert_int(shown.length()).is_greater(0)
	assert_int(shown.length()).is_less(SENTENCE.length())
	assert_bool(shown.ends_with(TypewriterProse.CARET)).is_true()
	assert_bool(prose.is_typing()).is_true()


func test_medium_speed_completes_on_its_own() -> void:
	var prose := _fresh_prose()
	prose.feed("narration", SENTENCE)
	await _await_idle(prose)
	assert_bool(prose.is_typing()).is_false()
	assert_str(prose.visible_text()).is_equal(SENTENCE)


## Poll-until-idle with a generous deadline: per-char timers quantize to
## frame boundaries, so a fixed 3s window with exact asserts flakes under
## CI load. The deadline only bounds the wait; asserts stay exact.
func _await_idle(prose: TypewriterProse, deadline := 8.0) -> void:
	var waited := 0.0
	while prose.is_typing() and waited < deadline:
		await get_tree().create_timer(0.05).timeout
		waited += 0.05


func test_instant_speed_shows_everything_at_once() -> void:
	ClientSettings.set_value("reading/text_speed", "instant")
	var prose := _fresh_prose()
	prose.feed("narration", SENTENCE)
	assert_str(prose.visible_text()).is_equal(SENTENCE)
	assert_bool(prose.is_typing()).is_false()


func test_reduced_motion_always_types_instantly() -> void:
	ClientSettings.set_value("reading/reduced_motion", true)
	var prose := _fresh_prose()
	prose.feed("narration", SENTENCE)
	assert_str(prose.visible_text()).is_equal(SENTENCE)
	assert_bool(prose.is_typing()).is_false()


func test_skip_lands_everything_buffered() -> void:
	var prose := _fresh_prose()
	prose.feed("narration", SENTENCE)
	prose.feed("narration", "The second sentence arrives later.")
	await get_tree().create_timer(0.1).timeout
	prose.skip()
	assert_str(prose.visible_text()).is_equal(SENTENCE + " " + "The second sentence arrives later.")
	assert_bool(prose.is_typing()).is_false()


func test_done_emits_all_text_shown_exactly_once() -> void:
	var prose := _fresh_prose()
	var emissions: Array = []
	prose.all_text_shown.connect(func() -> void: emissions.append(1))
	prose.feed("narration", SENTENCE)
	prose.skip()
	prose.feed("done", "")
	assert_that(emissions).has_size(1)
	prose.feed("done", "")  # a repeated terminator never re-emits
	assert_that(emissions).has_size(1)
	assert_str(prose.visible_text()).is_equal(SENTENCE)


func test_narration_after_done_starts_a_new_stream() -> void:
	var prose := _fresh_prose()
	var emissions: Array = []
	prose.all_text_shown.connect(func() -> void: emissions.append(1))
	prose.feed("narration", SENTENCE)
	prose.feed("done", "")
	assert_that(emissions).has_size(1)
	prose.feed("narration", "A fresh beat begins.")
	prose.skip()
	prose.feed("done", "")
	assert_that(emissions).has_size(2)


func test_change_and_badge_lines_land_instantly() -> void:
	var prose := _fresh_prose()
	prose.feed("change", "END +1")
	prose.feed("badge", "COMMISSIONED")
	assert_str(prose.visible_text()).is_equal("END +1\nCOMMISSIONED")
	assert_bool(prose.is_typing()).is_false()


func test_change_lands_after_the_text_typed_so_far() -> void:
	# A change block mid-typing snaps the partial narration home first — the
	# chronology (prose then change) must survive the interrupt.
	var prose := _fresh_prose()
	prose.feed("narration", "Half a story")
	await get_tree().create_timer(0.15).timeout
	prose.feed("change", "END +1")
	assert_str(prose.visible_text()).is_equal("Half a story\nEND +1")
	assert_bool(prose.is_typing()).is_false()


func test_setup_enables_scroll_following_and_prose_font() -> void:
	var prose := _fresh_prose()
	var rich := prose.get_child(0)
	assert_bool(rich.scroll_following).is_true()
	assert_bool(rich.bbcode_enabled).is_true()


func test_bracketed_prose_renders_literally() -> void:
	# Wire content is never trusted bbcode: [sighs] must survive, real tags
	# like [b] must not parse, and stray [/color] must not eat our wrappers.
	ClientSettings.set_value("reading/text_speed", "instant")
	var prose := _fresh_prose()
	prose.feed("narration", "[sighs] The [b]bold[/b] move [/color] ends.")
	assert_str(prose.visible_text()).is_equal("[sighs] The [b]bold[/b] move [/color] ends.")
	assert_bool(str(prose._rich.get_parsed_text()).contains("sighs")).is_true()


func test_exit_tree_mid_typing_lands_and_re_add_types_again() -> void:
	# Screens push/pop; a typewriter leaving the tree mid-sentence must not
	# resume on a dead instance or stay frozen when re-added.
	var prose := _fresh_prose()
	prose.feed("narration", SENTENCE)
	await get_tree().create_timer(0.15).timeout
	assert_bool(prose.is_typing()).is_true()
	remove_child(prose)
	assert_bool(prose.is_typing()).is_false()  # landed + cancelled pump
	add_child(prose)
	prose.feed("narration", "Fresh line after re-add.")
	assert_bool(prose.is_typing()).is_true()
	prose.skip()
	assert_str(prose.visible_text()).is_equal(SENTENCE + " Fresh line after re-add.")
