class_name AssignStage
extends VBoxContainer
## The pool-assignment stage (mockup 06a): six pool chips over a 3×2 stat
## matrix. Tap a chip (armed, dashed), tap a stat row — the pair commits via
## the option the server already offered (`assign:{pool_index}:{STAT}`).
## The once-only reroll rides as a ghost button. Zero truth beyond the view:
## legal pairs and pool values derive from the option set itself.

signal choose_option(option_id: String)

var _theme: PackTheme
## Pool index armed by the player (−1 = none).
var _armed := -1
var _pool: Array = []
var _chips: Array = []
var _stat_rows := {}
var _reroll_btn: Button
var _hint: Label


func setup(t: PackTheme) -> void:
	_theme = t
	add_theme_constant_override("separation", 18)


## Derives everything from the view: pool values from the assign labels,
## unassigned stats from the option set, the reroll from its option.
func build_from_view(view: Dictionary) -> void:
	_armed = -1
	_pool = _derive_pool(view)
	var unassigned: Array = _derive_unassigned_stats(view)
	var reroll_option: Variant = _find_option(view, "reroll_pool")

	for child: Node in get_children():
		remove_child(child)
		child.free()
	_chips = []
	_stat_rows = {}

	var chips_row := HBoxContainer.new()
	chips_row.add_theme_constant_override("separation", 10)
	chips_row.alignment = BoxContainer.ALIGNMENT_CENTER
	add_child(chips_row)
	for i: int in _pool.size():
		var chip := _build_chip(i)
		chips_row.add_child(chip)
		_chips.append(chip)

	var grid := GridContainer.new()
	grid.columns = 3
	grid.add_theme_constant_override("h_separation", 10)
	grid.add_theme_constant_override("v_separation", 10)
	grid.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	add_child(grid)
	for stat: String in ["STR", "DEX", "END", "INT", "EDU", "SOC"]:
		var row := StatRow.new()
		row.setup(_theme)
		var assigned := not unassigned.has(stat)
		if assigned:
			row.set_stat(stat, "?", "")  # value unknown from this view
			row.modulate.a = 0.55  # settled — not a drop target
		else:
			row.set_stat(stat, "—", "")
			row.set_drop_hint(true)
		var stat_name := stat
		row.gui_input.connect(_on_stat_input.bind(stat_name, row))
		grid.add_child(row)
		_stat_rows[stat] = row

	var dock := HBoxContainer.new()
	dock.add_theme_constant_override("separation", 12)
	dock.alignment = BoxContainer.ALIGNMENT_CENTER
	add_child(dock)
	if reroll_option != null:
		_reroll_btn = Kit.ghost_btn("⟳ REROLL POOL · ONCE", _theme)
		_reroll_btn.disabled = bool(reroll_option.get("dimmed", false))
		_reroll_btn.pressed.connect(func() -> void: choose_option.emit("reroll_pool"))
		dock.add_child(_reroll_btn)
	_hint = Fonts.label("TAP A VALUE, THEN ITS HOME", Fonts.micro_tracked(), 11, _theme.muted)
	dock.add_child(_hint)


func armed_pool_index() -> int:
	return _armed


# --- derivation (view-only truth) ----------------------------------------------


func _derive_pool(view: Dictionary) -> Array:
	var by_index := {}
	for option_variant: Variant in view.get("options", []):
		if not (option_variant is Dictionary):
			continue
		var option: Dictionary = option_variant
		var id := str(option.get("option_id", ""))
		if not id.begins_with("assign:"):
			continue
		var parts := id.split(":")
		if parts.size() < 3:
			continue
		var index := int(parts[1])
		if not by_index.has(index):
			by_index[index] = _value_from_label(str(option.get("label", "")))
	var pool: Array = []
	var i := 0
	while by_index.has(i):
		pool.append(by_index[i])
		i += 1
	return pool


static func _value_from_label(label: String) -> String:
	# "Assign 9 to STR" → "9"
	var mid := label.split(" to ", true, 1)
	if mid.size() != 2:
		return "?"
	return mid[0].trim_prefix("Assign ").strip_edges()


func _derive_unassigned_stats(view: Dictionary) -> Array:
	var stats := {}
	for option_variant: Variant in view.get("options", []):
		if not (option_variant is Dictionary):
			continue
		var id := str((option_variant as Dictionary).get("option_id", ""))
		if id.begins_with("assign:"):
			var parts := id.split(":")
			if parts.size() >= 3:
				stats[parts[2]] = true
	return stats.keys()


func _find_option(view: Dictionary, wanted: String) -> Variant:
	for option_variant: Variant in view.get("options", []):
		if (
			option_variant is Dictionary
			and str((option_variant as Dictionary).get("option_id", "")) == wanted
		):
			return option_variant
	return null


# --- interaction ----------------------------------------------------------------


func _build_chip(pool_index: int) -> Button:
	var chip := Button.new()
	chip.text = str(_pool[pool_index])
	chip.toggle_mode = true
	chip.add_theme_font_override("font", Fonts.title())
	chip.add_theme_font_size_override("font_size", 18)
	chip.add_theme_stylebox_override("focus", StyleBoxEmpty.new())
	chip.custom_minimum_size = Vector2(52, 40)
	chip.pressed.connect(_on_chip_pressed.bind(pool_index))
	_style_chip(chip, false)
	return chip


func _style_chip(chip: Button, armed: bool) -> void:
	var sb := StyleBoxFlat.new()
	sb.bg_color = _theme.panel if armed else Color.TRANSPARENT
	sb.set_border_width_all(2)
	sb.border_color = _theme.accent if armed else _theme.line
	if armed:
		sb.set_border_width_all(2)
		sb.draw_center = true
	chip.add_theme_stylebox_override("normal", sb)
	chip.add_theme_stylebox_override("hover", sb)
	chip.add_theme_stylebox_override("pressed", sb)
	chip.add_theme_color_override("font_color", _theme.ink)
	chip.add_theme_color_override("font_hover_color", _theme.ink)
	chip.add_theme_color_override("font_pressed_color", _theme.ink)
	chip.button_pressed = armed


func _on_chip_pressed(pool_index: int) -> void:
	_armed = -1 if _armed == pool_index else pool_index
	for i: int in _chips.size():
		_style_chip(_chips[i], i == _armed)
	if _hint != null:
		_hint.text = "NOW TAP ITS HOME" if _armed != -1 else "TAP A VALUE, THEN ITS HOME"


func _on_stat_input(event: InputEvent, stat: String, _row: StatRow) -> void:
	if not (event is InputEventMouseButton) or not event.pressed:
		return
	if event.button_index != MOUSE_BUTTON_LEFT:
		return
	if _armed == -1:
		return
	var option_id := "assign:%d:%s" % [_armed, stat]
	_armed = -1
	choose_option.emit(option_id)
