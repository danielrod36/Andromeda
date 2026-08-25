class_name StatRow
extends PanelContainer
## One characteristic row (mockup 06 .statrow): name · value · DM chip,
## with the dashed-target drop hint and the `cur → new` aging/injury preview
## (07b). Chips color by sign: + ok, − danger, 0/empty muted.

var _theme: PackTheme
var _name_label: Label
var _value_label: Label
var _dm_label: Label
var _drop := false
var _name := ""
var _value_text := ""
var _dm_text := ""
var _preview_text := ""
var _preview_color := Color.WHITE


func setup(t: PackTheme) -> void:
	_theme = t
	custom_minimum_size = Vector2(0, 40)
	var sb := StyleBoxFlat.new()
	sb.bg_color = t.panel
	sb.set_border_width_all(2)
	sb.border_color = t.line
	sb.content_margin_left = 12
	sb.content_margin_right = 12
	sb.content_margin_top = 8
	sb.content_margin_bottom = 8
	add_theme_stylebox_override("panel", sb)
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)
	row.alignment = BoxContainer.ALIGNMENT_CENTER
	add_child(row)
	_name_label = Fonts.label("", Fonts.inter(), 12, t.ink)
	row.add_child(_name_label)
	_value_label = Fonts.label("", Fonts.data_semibold(), 16, t.ink)
	row.add_child(_value_label)
	_dm_label = Fonts.label("", Fonts.data(), 10, t.muted)
	row.add_child(_dm_label)


## Renders one characteristic. `dm_text` is the screen-provided chip text
## ("DM +1", "+1", "+0", "" — sign alone drives the color).
func set_stat(name: String, value: Variant, dm_text: String) -> void:
	_name = name
	_value_text = str(value).replace("-", "\u2212")
	_dm_text = dm_text
	_name_label.text = name
	_value_label.text = _value_text
	_value_label.add_theme_color_override("font_color", _theme.accent if _drop else _theme.ink)
	_dm_label.text = dm_text
	var sign := _dm_sign(dm_text)
	var color := _theme.muted
	if sign > 0:
		color = _theme.ok
	elif sign < 0:
		color = _theme.danger
	_dm_label.add_theme_color_override("font_color", color)


## Pool assignment target: dashed accent border + accent value (mock 06).
func set_drop_hint(on: bool) -> void:
	_drop = on
	var sb := get_theme_stylebox("panel") as StyleBoxFlat
	sb.border_color = _theme.accent if on else _theme.line
	if _value_label != null:
		_value_label.add_theme_color_override("font_color", _theme.accent if on else _theme.ink)


## Aging/injury preview: `cur → new`, new in danger when lower, ok when
## higher (07b). Replaces the value cell until clear_preview().
func set_preview(new_value: Variant) -> void:
	var cur_text := _value_text
	var new_text := str(new_value).replace("-", "\u2212")
	var cur_num := _num_from(cur_text)
	var new_num := _num_from(new_text)
	if new_num > cur_num:
		_preview_color = _theme.ok
	elif new_num < cur_num:
		_preview_color = _theme.danger
	else:
		_preview_color = _theme.ink
	_preview_text = "%s \u2192 %s" % [cur_text, new_text]
	_value_label.text = _preview_text
	_value_label.add_theme_color_override("font_color", _preview_color)


## Back to the plain value (and the drop hint's color when active).
func clear_preview() -> void:
	_preview_text = ""
	_value_label.text = _value_text
	_value_label.add_theme_color_override("font_color", _theme.accent if _drop else _theme.ink)


## Value in a display string ("9", "\u22121") — NAN when not numeric (no
## baseline set yet; set_preview then colors neutrally).
static func _num_from(text: String) -> float:
	var normalized := text.replace("\u2212", "-")
	return normalized.to_float() if normalized.is_valid_float() else NAN


## Sign of the FIRST number token in the chip text: "DM +1"/"+1" → 1,
## "\u22122"/"DM -3" → -1, "DM +0"/""/"DM +0 -2" → 0. Only the leading
## signed integer counts — later tokens never flip it.
static func _dm_sign(text: String) -> int:
	var s := text.replace("\u2212", "-").strip_edges()
	var i := 0
	while i < s.length() and not (s[i].is_valid_int() or s[i] == "+" or s[i] == "-"):
		i += 1
	if i >= s.length():
		return 0
	var negative := false
	if s[i] == "+" or s[i] == "-":
		negative = s[i] == "-"
		i += 1
	var digits := ""
	while i < s.length() and s[i].is_valid_int():
		digits += s[i]
		i += 1
	if digits.is_empty() or digits.to_int() == 0:
		return 0
	return -1 if negative else 1
