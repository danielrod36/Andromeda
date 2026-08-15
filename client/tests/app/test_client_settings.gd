extends GdUnitTestSuite
## ClientSettings: defaults, roundtrip, persistence across instances.

const ClientSettingsImpl := preload("res://app/client_settings.gd")

const TEST_PATH := "user://settings-test.cfg"


func before() -> void:
	ClientSettings.use_test_path()


## Every instance must be redirected too — the path is per-instance state, so
## a plain new() would still target the developer's real settings.cfg.
func _fresh() -> Node:
	var s: Node = auto_free(ClientSettingsImpl.new())
	s.use_test_path()
	add_child(s)
	return s


func test_defaults_match_the_mock_positions() -> void:
	var s: Node = _fresh()
	assert_str(str(s.get_value("reading/text_speed"))).is_equal("medium")
	assert_bool(bool(s.get_value("reading/ambient_life"))).is_true()
	assert_bool(bool(s.get_value("reading/reduced_motion"))).is_false()
	assert_that(float(s.get_value("audio/master"))).is_equal(0.7)
	assert_that(float(s.get_value("audio/music"))).is_equal(0.55)
	assert_that(float(s.get_value("audio/effects"))).is_equal(0.8)
	assert_str(str(s.get_value("ui/last_played_pack"))).is_equal("")


func test_set_persists_across_instances_and_emits() -> void:
	var s: Node = _fresh()
	var seen: Array = []
	s.changed.connect(func(key: String, value: Variant) -> void: seen.append([key, value]))
	s.set_value("reading/text_speed", "fast")
	assert_that(seen.size()).is_equal(1)
	var fresh: Node = _fresh()
	assert_str(str(fresh.get_value("reading/text_speed"))).is_equal("fast")
	# restore the default so other tests/runs are unaffected
	s.set_value("reading/text_speed", "medium")


func test_malformed_key_returns_default_without_raising() -> void:
	var s: Node = _fresh()
	# no "/" — the old key.split("/")[1] raised here; now it warns and falls
	# back to the DEFAULTS lookup (null for a key DEFAULTS doesn't know)
	assert_that(s.get_value("no-section-key")).is_null()
	var seen: Array = []
	s.changed.connect(func(_key: String, _value: Variant) -> void: seen.append(1))
	s.set_value("also-malformed", true)  # bails without saving or emitting
	assert_that(seen.size()).is_equal(0)


func test_set_value_save_is_atomic_no_tmp_lingers() -> void:
	var s: Node = _fresh()
	s.set_value("audio/master", 0.5)
	# the tmp sibling must be swapped away, never left next to the real file
	assert_bool(FileAccess.file_exists(TEST_PATH + ".tmp")).is_false()
	assert_bool(FileAccess.file_exists(TEST_PATH)).is_true()
	# restore the default so later suites/goldens see documented defaults
	s.set_value("audio/master", 0.7)
