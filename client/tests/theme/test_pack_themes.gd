extends GdUnitTestSuite
## tokens.css conformance (spec M2-D6): the four pack token sets must match
## design/mockups/final/tokens.css lines 24-27 byte-for-byte.

const PackThemesImpl := preload("res://theme/pack_themes.gd")

# id -> [bg, panel, line, ink, muted, accent, ok, danger, motif, ambience]
const EXPECTED := {
	"scifi":
	[
		"0A0F1E",
		"101830",
		"27345C",
		"E6EBF7",
		"7C88A8",
		"F5A623",
		"46C48A",
		"E5484D",
		"✦",
		["meteors", "birds"]
	],
	"fantasy":
	[
		"17120C",
		"221A10",
		"4A3A22",
		"F2E9D8",
		"9C8D76",
		"D9A02B",
		"7FA85C",
		"C24A52",
		"❧",
		["fireflies", "leaves"]
	],
	"neutral":
	["13161D", "1A1F2A", "2C3444", "E9EDF5", "7E8899", "8FA3C8", "5FC98E", "E5606C", "◆", []],
	"dead":
	["180F12", "221418", "4A2830", "E9DCD8", "96787E", "8E3A46", "7FA85C", "E5606C", "✝", []],
}


func test_four_token_sets_match_tokens_css() -> void:
	var sets: Dictionary = PackThemesImpl._build_sets()
	assert_that(sets.size()).is_equal(4)
	for id: String in EXPECTED:
		var e: Array = EXPECTED[id]
		var t: PackTheme = sets[id]
		assert_that(t.bg).is_equal(Color(e[0]))
		assert_that(t.panel).is_equal(Color(e[1]))
		assert_that(t.line).is_equal(Color(e[2]))
		assert_that(t.ink).is_equal(Color(e[3]))
		assert_that(t.muted).is_equal(Color(e[4]))
		assert_that(t.accent).is_equal(Color(e[5]))
		assert_that(t.ok).is_equal(Color(e[6]))
		assert_that(t.danger).is_equal(Color(e[7]))
		assert_that(t.motif).is_equal(e[8])
		assert_that(Array(t.ambience)).is_equal(e[9])


func test_get_theme_falls_back_to_neutral() -> void:
	var sets: Dictionary = PackThemesImpl._build_sets()
	var pt: Node = PackThemesImpl.new()
	pt._sets = sets
	assert_that(pt.get_theme("scifi").id).is_equal("scifi")
	assert_that(pt.get_theme("nonexistent").id).is_equal("neutral")
	pt.free()
