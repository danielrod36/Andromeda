extends GdUnitTestSuite
## StatRow (M3-C2): name/value/DM chip rendering, sign-driven chip colors,
## the drop hint, and the cur → new preview.


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


func _fresh_row() -> StatRow:
	var row: StatRow = auto_free(StatRow.new())
	add_child(row)
	row.setup(_theme())
	return row


func _cells(row: StatRow) -> Array:
	var hbox: HBoxContainer = row.get_child(0)
	return [hbox.get_child(0), hbox.get_child(1), hbox.get_child(2)]


func test_set_stat_renders_name_value_and_dm_chip() -> void:
	var row := _fresh_row()
	row.set_stat("STR", 9, "DM +1")
	var cells := _cells(row)
	assert_str(cells[0].text).is_equal("STR")
	assert_str(cells[1].text).is_equal("9")
	assert_str(cells[2].text).is_equal("DM +1")
	assert_that(row.custom_minimum_size).is_equal(Vector2(0, 40))


func test_dm_chip_colors_follow_the_sign() -> void:
	var row := _fresh_row()
	row.set_stat("STR", 9, "DM +1")
	assert_that(_cells(row)[2].get_theme_color("font_color")).is_equal(_theme().ok)

	row.set_stat("END", 7, "DM +0")
	assert_that(_cells(row)[2].get_theme_color("font_color")).is_equal(_theme().muted)

	row.set_stat("END", 3, "DM \u22121")
	assert_that(_cells(row)[2].get_theme_color("font_color")).is_equal(_theme().danger)

	row.set_stat("EDU", 6, "")
	assert_that(_cells(row)[2].get_theme_color("font_color")).is_equal(_theme().muted)


func test_dm_sign_reads_the_numeric_value_not_the_glyphs() -> void:
	# "DM +0" is zero — muted, never ok-green; "-2" (ASCII minus) is danger.
	assert_int(StatRow._dm_sign("DM +0")).is_equal(0)
	assert_int(StatRow._dm_sign("+0")).is_equal(0)
	assert_int(StatRow._dm_sign("DM +2")).is_equal(1)
	assert_int(StatRow._dm_sign("\u22122")).is_equal(-1)
	assert_int(StatRow._dm_sign("DM -3")).is_equal(-1)
	assert_int(StatRow._dm_sign("")).is_equal(0)


func test_drop_hint_tints_value_accent_and_border() -> void:
	var row := _fresh_row()
	row.set_stat("END", 7, "DM +0")
	row.set_drop_hint(true)
	var sb := row.get_theme_stylebox("panel") as StyleBoxFlat
	assert_that(sb.border_color).is_equal(_theme().accent)
	assert_that(_cells(row)[1].get_theme_color("font_color")).is_equal(_theme().accent)

	row.set_drop_hint(false)
	assert_that(sb.border_color).is_equal(_theme().line)
	assert_that(_cells(row)[1].get_theme_color("font_color")).is_equal(_theme().ink)


func test_preview_renders_cur_arrow_new_with_drop_coloring() -> void:
	var row := _fresh_row()
	row.set_stat("STR", 8, "DM +1")
	row.set_preview(6)
	var value: Label = _cells(row)[1]
	assert_str(value.text).is_equal("8 \u2192 6")
	assert_that(value.get_theme_color("font_color")).is_equal(_theme().danger)

	row.set_preview(10)
	assert_str(value.text).is_equal("8 \u2192 10")
	assert_that(value.get_theme_color("font_color")).is_equal(_theme().ok)


func test_clear_preview_restores_the_plain_value() -> void:
	var row := _fresh_row()
	row.set_stat("DEX", 11, "DM +1")
	row.set_preview(8)
	row.clear_preview()
	assert_str(_cells(row)[1].text).is_equal("11")
	assert_that(_cells(row)[1].get_theme_color("font_color")).is_equal(_theme().ink)


func test_clear_preview_keeps_the_drop_hint_tint() -> void:
	var row := _fresh_row()
	row.set_stat("END", 7, "DM +0")
	row.set_drop_hint(true)
	row.set_preview(5)
	row.clear_preview()
	assert_str(_cells(row)[1].text).is_equal("7")
	assert_that(_cells(row)[1].get_theme_color("font_color")).is_equal(_theme().accent)
