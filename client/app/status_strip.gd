class_name StatusStrip
extends Control
## The cockpit strip (spec §6): left "ENGINE SYNC ✓ · v0.1.0"; right
## "NARRATOR: <MODEL> ●" when configured, "NARRATOR: TEMPLATES ○" when not.
## Dot only (parent §6.6) — operator detail lives in Settings.

const CLIENT_VERSION := "0.1.0"

var pack_theme: PackTheme:
	set(v):
		pack_theme = v
		queue_redraw()

var _left_sync: Label
var _left_tick: Label
var _left_version: Label
var _right_text: Label
var _right_dot: Label


func _ready() -> void:
	custom_minimum_size = Vector2(0, 27)
	var row := HBoxContainer.new()
	row.set_anchors_preset(Control.PRESET_FULL_RECT)
	row.add_theme_constant_override("separation", 0)
	add_child(row)
	var left := HBoxContainer.new()
	left.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	left.add_theme_constant_override("separation", 0)
	row.add_child(left)
	_left_sync = Label.new()
	left.add_child(_left_sync)
	_left_tick = Label.new()
	left.add_child(_left_tick)
	_left_version = Label.new()
	left.add_child(_left_version)
	var right := HBoxContainer.new()
	right.alignment = BoxContainer.ALIGNMENT_END
	row.add_child(right)
	_right_text = Label.new()
	right.add_child(_right_text)
	_right_dot = Label.new()
	right.add_child(_right_dot)
	restyle()
	refresh({})


func restyle() -> void:
	if pack_theme == null:
		return
	for label: Label in [_left_sync, _left_version, _right_text]:
		label.add_theme_font_override("font", Fonts.data())
		label.add_theme_font_size_override("font_size", 10)
		label.add_theme_color_override("font_color", pack_theme.muted)
	for label: Label in [_left_tick, _right_dot]:
		label.add_theme_font_override("font", Fonts.data())
		label.add_theme_font_size_override("font_size", 10)
	_left_tick.add_theme_color_override("font_color", pack_theme.ok)


## status = the /v1/llm/status payload (§A2); {} renders the unconfigured state.
func refresh(status: Dictionary) -> void:
	var configured := bool(status.get("configured", false))
	_left_sync.text = "ENGINE SYNC "
	_left_tick.text = "✓"
	_left_version.text = " · v" + CLIENT_VERSION
	if configured:
		_right_text.text = "NARRATOR: %s " % str(status.get("model", "")).to_upper()
		_right_dot.text = "●"
		if pack_theme != null:
			_right_dot.add_theme_color_override("font_color", pack_theme.ok)
	else:
		_right_text.text = "NARRATOR: TEMPLATES "
		_right_dot.text = "○"
		if pack_theme != null:
			_right_dot.add_theme_color_override("font_color", pack_theme.muted)


func _draw() -> void:
	if pack_theme == null:
		return
	# rgba(8,10,16,.9) panel + 2px top border (tokens.css .strip).
	draw_rect(Rect2(Vector2.ZERO, size), Color(8.0 / 255, 10.0 / 255, 16.0 / 255, 0.9))
	draw_rect(Rect2(Vector2.ZERO, Vector2(size.x, 2)), pack_theme.line)


## Mock 05 strip: narrator on the left, plain status text on the right.
func show_narrator_left(status: Dictionary) -> void:
	var configured := bool(status.get("configured", false))
	if configured:
		_left_sync.text = "NARRATOR: %s " % str(status.get("model", "")).to_upper()
	else:
		_left_sync.text = "NARRATOR: TEMPLATES "
	_left_tick.text = "●" if configured else "○"
	_left_version.text = ""
	if pack_theme != null:
		_left_tick.add_theme_color_override(
			"font_color", pack_theme.ok if configured else pack_theme.muted
		)


func set_right_plain(text: String) -> void:
	_right_text.text = text
	_right_dot.text = ""
