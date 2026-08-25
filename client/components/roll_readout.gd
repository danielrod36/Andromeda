class_name RollReadout
extends HBoxContainer
## tokens.css .readout / .tbl-roll — the one way rolls are shown (spec §6.4).
## Three forms render the same RollResult dictionary:
##   full    — pip dice + signed DM chip + big total + vs + verdict chip
##   compact — 18px pips + chips (no verdict, no target)
##   table   — pip dice + DM chip + total + "→ result" (07b, meterless)
## Zero game truth: presentation only — pips from rolls[], chip text from the
## parsed receipt line. Natural 2/12 earn the mock's accent/ok frames.

const _DIE_FULL := 30
const _DIE_COMPACT := 18

var _theme: PackTheme
var _frame_mode := "line"  # line | accent (natural 2) | ok (natural 12)
var _tween: Tween


## Parses the server's receipt lines into
## {label, dm, total, target, outcome, tier}; {} when unparseable.
## Two wire shapes (src/game/lifepath.py):
##   `Label: 2D6({raw})+DM({dm})={total} vs {target} -> outcome [tier]`
##   `Label: 2D6({raw})={total} vs {target} -> outcome`  (dm == 0 — the
##   server omits the DM segment; the re-enlistment receipt never has one)
## `target` stays a String when non-numeric (the re-enlistment `—`).
static func parse_receipt(receipt: String) -> Dictionary:
	var head := receipt.split(":", true, 1)
	if head.size() != 2 or head[0].strip_edges() == "":
		return {}
	var body := head[1]
	var dm := 0
	var after_dm := body
	var dm_open := body.find("+DM(")
	if dm_open != -1:
		var dm_close := body.find(")", dm_open + 4)
		if dm_close == -1:
			return {}
		var dm_text := body.substr(dm_open + 4, dm_close - dm_open - 4).strip_edges()
		if not dm_text.is_valid_int():
			return {}
		dm = int(dm_text)
		after_dm = body.substr(dm_close + 1)
	var eq := after_dm.find("=")
	if eq == -1:
		return {}
	var vs := after_dm.find(" vs ", eq + 1)
	if vs == -1:
		return {}
	var arrow := after_dm.find(" -> ", vs + 4)
	if arrow == -1:
		return {}
	var total_text := after_dm.substr(eq + 1, vs - eq - 1).strip_edges()
	if not total_text.is_valid_int():
		return {}
	var target_text := after_dm.substr(vs + 4, arrow - vs - 4).strip_edges()
	var outcome_parts := after_dm.substr(arrow + 4).strip_edges().split(" ", false)
	if outcome_parts.is_empty() or target_text == "":
		return {}
	return {
		"label": head[0].strip_edges(),
		"dm": dm,
		"total": int(total_text),
		"target": int(target_text) if target_text.is_valid_int() else target_text,
		"outcome": outcome_parts[0],
		"tier": " ".join(outcome_parts.slice(1)),
	}


## Signed display for DM values — the mock's U+2212 minus for negatives.
static func _signed(n: int) -> String:
	return "+%d" % n if n >= 0 else "\u2212%d" % absi(n)


func setup(t: PackTheme) -> void:
	_theme = t
	# Presentation-only: never swallow clicks aimed at the stage behind it.
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_theme_constant_override("separation", 9)
	alignment = BoxContainer.ALIGNMENT_CENTER


## Full readout (mockup 06b): dice, named DM chip, total, target, verdict.
func show_full(roll: Dictionary, receipt: String) -> void:
	var parsed := parse_receipt(receipt)
	var top := _top_row()
	top.add_child(_dice_row(roll, _DIE_FULL))
	var chip := _dm_chip_from(parsed, roll)
	if chip != null:
		top.add_child(chip)
	top.add_child(_eq_label())
	top.add_child(_total_label(int(roll.get("total", 0))))
	if not parsed.is_empty():
		top.add_child(Fonts.label("vs %s" % str(parsed["target"]), Fonts.data(), 10, _theme.muted))
		var outcome := str(parsed["outcome"]).to_lower()
		var color := _theme.ok if outcome == "success" else _theme.danger
		top.add_child(Fonts.label(str(parsed["outcome"]).to_upper(), Fonts.inter(), 11, color))
	_mount(top, 50)
	var natural := _natural_sum(roll)
	_frame_mode = "accent" if natural == 2 else ("ok" if natural == 12 else "line")
	_land()


## Compact readout: 18px pips + chips only (dense rows, dockets).
func show_compact(roll: Dictionary, receipt: String) -> void:
	var parsed := parse_receipt(receipt)
	var top := _top_row()
	top.add_child(_dice_row(roll, _DIE_COMPACT))
	var chip := _dm_chip_from(parsed, roll)
	if chip != null:
		top.add_child(chip)
	_mount(top, 34)
	_frame_mode = "line"
	_land()


## Table-roll readout (mockup 07b): dice + chip + total → result, no verdict.
func show_table(roll: Dictionary, result_text: String) -> void:
	var top := _top_row()
	top.add_child(_dice_row(roll, _DIE_FULL))
	var chip := _dm_chip_from({}, roll)
	if chip != null:
		top.add_child(chip)
	top.add_child(_eq_label())
	top.add_child(_total_label(int(roll.get("total", 0))))
	top.add_child(Fonts.label("\u2192 %s" % result_text, Fonts.data(), 11, _theme.ink))
	_mount(top, 50)
	_frame_mode = "line"
	_land()


func _draw() -> void:
	if _theme == null:
		return
	pivot_offset = size / 2.0  # stamp-landing scales about the center
	var r := Rect2(Vector2.ZERO, size)
	var bg := _theme.panel
	bg.a = 0.8
	draw_rect(r, bg)
	var border := _theme.line
	match _frame_mode:
		"accent":
			border = _theme.accent
		"ok":
			border = _theme.ok
	draw_rect(r, border, false, 2.0)


## Frees the current form's children immediately (not queue_free) so a new
## form can mount in the same frame without mixing live and dying nodes.
func _clear() -> void:
	for child: Node in get_children():
		remove_child(child)
		child.free()


func _mount(top: HBoxContainer, min_height: int) -> void:
	_clear()
	custom_minimum_size = Vector2(0, min_height)
	var pad_left := Control.new()
	pad_left.mouse_filter = Control.MOUSE_FILTER_IGNORE
	pad_left.custom_minimum_size = Vector2(12, 0)
	var pad_right := Control.new()
	pad_right.mouse_filter = Control.MOUSE_FILTER_IGNORE
	pad_right.custom_minimum_size = Vector2(12, 0)
	add_child(pad_left)
	add_child(top)
	add_child(pad_right)
	queue_redraw()


func _top_row() -> HBoxContainer:
	var row := HBoxContainer.new()
	row.mouse_filter = Control.MOUSE_FILTER_IGNORE
	row.add_theme_constant_override("separation", 9)
	row.alignment = BoxContainer.ALIGNMENT_CENTER
	return row


func _dice_row(roll: Dictionary, die_px: int) -> HBoxContainer:
	var row := HBoxContainer.new()
	row.mouse_filter = Control.MOUSE_FILTER_IGNORE
	row.add_theme_constant_override("separation", 7)
	for face: Variant in Array(roll.get("rolls", [])):
		var die := PipDie.new()
		die.pip_value = int(face)
		die.face_color = _theme.ink
		die.pip_color = _theme.bg
		die.custom_minimum_size = Vector2(die_px, die_px)
		row.add_child(die)
	return row


## Chip text = signed DM (+ the receipt label when parseable); sign colors the
## border and text per the mock's .dm.pos / .dm.neg. A DM of zero applies
## nothing — no chip (the mock shows chips only for actual modifiers).
func _dm_chip_from(parsed: Dictionary, roll: Dictionary) -> PanelContainer:
	var dm := int(parsed.get("dm", int(roll.get("modifiers", 0))))
	if dm == 0:
		return null
	var text := _signed(dm)
	if not parsed.is_empty() and str(parsed["label"]).strip_edges() != "":
		text += " " + str(parsed["label"]).to_upper().strip_edges()
	var chip := PanelContainer.new()
	chip.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var sb := StyleBoxFlat.new()
	sb.bg_color = _theme.panel
	sb.set_border_width_all(2)
	sb.border_color = _theme.line
	sb.content_margin_left = 7
	sb.content_margin_right = 7
	sb.content_margin_top = 4
	sb.content_margin_bottom = 4
	var color := _theme.muted
	if signi(dm) > 0:
		sb.border_color = _theme.ok
		color = _theme.ok
	elif signi(dm) < 0:
		sb.border_color = _theme.danger
		color = _theme.danger
	chip.add_theme_stylebox_override("panel", sb)
	chip.add_child(Fonts.label(text, Fonts.data(), 10, color))
	return chip


func _eq_label() -> Label:
	return Fonts.label("=", Fonts.title(), 14, _theme.muted)


func _total_label(total: int) -> Label:
	return Fonts.label(str(total).replace("-", "\u2212"), Fonts.title(), 26, _theme.ink)


## "Natural" is a 2D6 idiom — only exactly two six-sided dice can earn the
## fumble/crit frames; 3D6 summing 12 or a lone die showing 2 never do.
static func _natural_sum(roll: Dictionary) -> int:
	if int(roll.get("ndice", 2)) != 2 or int(roll.get("sides", 6)) != 6:
		return 0
	var total := 0
	for face: Variant in Array(roll.get("rolls", [])):
		total += int(face)
	return total


## Stamp-landing: one-shot 0.12s scale/alpha arrival. A previous landing is
## killed first — back-to-back rolls never overlap tweens on the same
## properties. Reduced motion (or no tree to run a tween in) snaps.
func _land() -> void:
	if _theme == null:
		return
	pivot_offset = size / 2.0
	if _tween != null and _tween.is_valid():
		_tween.kill()
	if bool(ClientSettings.get_value("reading/reduced_motion")) or not is_inside_tree():
		scale = Vector2.ONE
		modulate.a = 1.0
		return
	scale = Vector2(0.9, 0.9)
	modulate.a = 0.2
	_tween = create_tween().set_parallel(true)
	_tween.tween_property(self, "scale", Vector2.ONE, 0.12).set_trans(Tween.TRANS_QUAD).set_ease(
		Tween.EASE_OUT
	)
	_tween.tween_property(self, "modulate:a", 1.0, 0.12)


class PipDie:
	extends Control
	## One die face: ink square, bg-colored pips in the mock's .TL/.TR/…/C
	## positions (16%/46% grid), hard drop shadow scaled to the face size.

	const _FACES := {
		1: ["C"],
		2: ["TL", "BR"],
		3: ["TL", "C", "BR"],
		4: ["TL", "TR", "BL", "BR"],
		5: ["TL", "TR", "C", "BL", "BR"],
		6: ["TL", "TR", "ML", "MR", "BL", "BR"],
	}

	var pip_value := 1
	var face_color := Color.WHITE
	var pip_color := Color.BLACK

	func _init() -> void:
		mouse_filter = Control.MOUSE_FILTER_IGNORE

	func _draw() -> void:
		var shadow := maxi(int(size.x / 15.0), 1)
		draw_rect(Rect2(Vector2(shadow, shadow), size), Color(0, 0, 0, 0.5))
		draw_rect(Rect2(Vector2.ZERO, size), face_color)
		var pip_r := maxf(size.x, size.y) * 0.1
		for key: String in _FACES.get(pip_value, ["C"]):
			draw_circle(_pip_pos(key, pip_r), pip_r, pip_color)

	## CSS places the pip box's top-left at 16%/46%; the pip center is that
	## offset plus one pip radius. "C" is the single center pip; the rest
	## are a column letter (L/R) plus a row letter (T/M/B).
	func _pip_pos(key: String, pip_r: float) -> Vector2:
		if key == "C":
			return size / 2.0
		var edge := pip_r + minf(size.x, size.y) * 0.16
		var cols := {"L": edge, "R": size.x - edge}
		var rows := {"T": edge, "M": size.y / 2.0, "B": size.y - edge}
		return Vector2(cols[key[1]], rows[key[0]])
