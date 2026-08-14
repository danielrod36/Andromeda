extends GdUnitTestSuite
## ClientSettings: defaults, roundtrip, persistence across instances.

const ClientSettingsImpl := preload("res://app/client_settings.gd")


func test_defaults_match_the_mock_positions() -> void:
	var s: Node = auto_free(ClientSettingsImpl.new())
	add_child(s)
	assert_str(str(s.get_value("reading/text_speed"))).is_equal("medium")
	assert_bool(bool(s.get_value("reading/ambient_life"))).is_true()
	assert_bool(bool(s.get_value("reading/reduced_motion"))).is_false()
	assert_that(float(s.get_value("audio/master"))).is_equal(0.7)
	assert_that(float(s.get_value("audio/music"))).is_equal(0.55)
	assert_that(float(s.get_value("audio/effects"))).is_equal(0.8)
	assert_str(str(s.get_value("ui/last_played_pack"))).is_equal("")


func test_set_persists_across_instances_and_emits() -> void:
	var s: Node = auto_free(ClientSettingsImpl.new())
	add_child(s)
	var seen: Array = []
	s.changed.connect(func(key: String, value: Variant) -> void: seen.append([key, value]))
	s.set_value("reading/text_speed", "fast")
	assert_that(seen.size()).is_equal(1)
	var fresh: Node = auto_free(ClientSettingsImpl.new())
	add_child(fresh)
	assert_str(str(fresh.get_value("reading/text_speed"))).is_equal("fast")
	# restore the default so other tests/runs are unaffected
	s.set_value("reading/text_speed", "medium")
