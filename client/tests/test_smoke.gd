extends GdUnitTestSuite
## Scaffold smoke test (M2.1): right engine, fonts on disk.


func test_godot_version_is_4_7_1() -> void:
	assert_str(str(Engine.get_version_info()["string"])).contains("4.7.1")


func test_fonts_are_on_disk() -> void:
	var fonts := [
		"res://assets/fonts/spacegrotesk/SpaceGrotesk-Variable.ttf",
		"res://assets/fonts/chakrapetch/ChakraPetch-SemiBold.ttf",
		"res://assets/fonts/atkinsonhyperlegible/AtkinsonHyperlegible-Regular.ttf",
		"res://assets/fonts/ibmplexmono/IBMPlexMono-Medium.ttf",
		"res://assets/fonts/vt323/VT323-Regular.ttf",
	]
	for path: String in fonts:
		assert_bool(FileAccess.file_exists(path)).is_true()
