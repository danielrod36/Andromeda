class_name SheetDrawer
extends BaseScreen
## The pinned sheet (mockup 06's right pane) as a pushed overlay — the first
## ScreenStack.push/pop consumer. Read-only: name/career/terms line, the six
## characteristics as StatRows with server-computed DMs, skills as mono text.
## ESC pops. Data loads from GET /sheet; only verified fields render.

## Test hook: emitted instead of calling _pop when set (methods cannot be
## reassigned in GDScript; tests stub via this hook).
signal pop_requested

## Test hook: when set, used instead of Services.client.
var client_override: Node

var _theme: PackTheme
var _session := {}
var _loading_label: Label
var _content_box: VBoxContainer
## Guards the sheet fetch across pops.
var _epoch := 0


func _ready() -> void:
	_theme = PackThemes.current
	_build()


## Pushed overlays own ESC as pop — never the stack's replace-auto-route.
func esc_target() -> String:
	return ""


func _unhandled_input(event: InputEvent) -> void:
	if not visible:
		return
	if not (
		event is InputEventKey and event.pressed and not event.echo and event.keycode == KEY_ESCAPE
	):
		return
	get_viewport().set_input_as_handled()
	_pop()


func screen_enter(params: Dictionary) -> void:
	_epoch += 1
	var session: Variant = params.get("session")
	_session = session if session is Dictionary else {}
	var override: Variant = params.get("client_override")
	client_override = override if override is Node else client_override
	if is_instance_valid(_content_box):
		for child: Node in _content_box.get_children():
			_content_box.remove_child(child)
			child.free()
	if is_instance_valid(_loading_label):
		_loading_label.visible = true
	_fetch_sheet()


func screen_exit() -> void:
	_epoch += 1


func _client() -> Node:
	return client_override if client_override != null else Services.client


func _pop() -> void:
	pop_requested.emit()  # test hook
	var stack := _stack()
	if stack != null:
		stack.pop()
	elif is_inside_tree():
		# Fallback for direct-instantiation tests: leave the tree.
		get_parent().remove_child(self)


func _stack() -> ScreenStack:
	var node := get_parent()
	while node != null:
		if node is ScreenStack:
			return node
		node = node.get_parent()
	return null


func _fetch_sheet() -> void:
	var epoch := _epoch
	var res: EngineResult = await _client().sheet(str(_session.get("id", "")))
	if epoch != _epoch or not is_inside_tree() or not visible:
		return
	if not res.ok:
		Services.overlay.toast_error(res)
		_pop()
		return
	if is_instance_valid(_loading_label):
		_loading_label.visible = false
	_render_sheet(res.data)


func _render_sheet(data: Dictionary) -> void:
	var character: Dictionary = data.get("character", {})
	var dms: Dictionary = data.get("characteristic_dms", {})
	var skill_names: Dictionary = data.get("skill_names", {})

	var name_line := str(character.get("name", ""))
	if name_line == "":
		name_line = "NAME UNDECIDED"
	var detail_parts := PackedStringArray()
	var career := str(character.get("career", ""))
	if career != "":
		detail_parts.append(career.to_upper())
	var terms := int(character.get("terms", 0))
	if terms > 0:
		detail_parts.append("%d TERM%s" % [terms, "S" if terms != 1 else ""])
	var age := int(character.get("age", 0))
	if age > 0:
		detail_parts.append("AGE %d" % age)
	_content_box.add_child(Fonts.label(name_line, Fonts.title(), 22, _theme.ink))
	if not detail_parts.is_empty():
		_content_box.add_child(
			Fonts.label(" · ".join(detail_parts), Fonts.micro_tracked(), 11, _theme.muted)
		)

	var grid := GridContainer.new()
	grid.columns = 3
	grid.add_theme_constant_override("h_separation", 8)
	grid.add_theme_constant_override("v_separation", 8)
	grid.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_content_box.add_child(grid)
	for char_name: String in ["STR", "DEX", "END", "INT", "EDU", "SOC"]:
		var row := StatRow.new()
		row.setup(_theme)
		var value: Variant = character.get("characteristics", {}).get(char_name, "—")
		var dm := int(dms.get(char_name, 0))
		row.set_stat(char_name, value, "DM %+d" % dm)
		grid.add_child(row)

	var skills: Dictionary = character.get("skills", {})
	if not skills.is_empty():
		_content_box.add_child(Fonts.label("SKILLS", Fonts.micro_tracked(), 11, _theme.muted))
		var parts := PackedStringArray()
		for skill_id: String in skills:
			var display := str(skill_names.get(skill_id, skill_id))
			parts.append("%s-%d" % [display.to_upper(), int(skills[skill_id])])
		var skills_line := Fonts.label(" · ".join(parts), Fonts.data(), 11, _theme.ink)
		skills_line.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		skills_line.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		_content_box.add_child(skills_line)

	var credits := int(character.get("credits", 0))
	if credits > 0:
		_content_box.add_child(Fonts.label("CR %d" % credits, Fonts.data(), 11, _theme.muted))


func _build() -> void:
	for child: Node in get_children():
		remove_child(child)
		child.free()
	var t := _theme
	var dim := ColorRect.new()
	dim.color = Color(0, 0, 0, 0.6)
	dim.set_anchors_preset(Control.PRESET_FULL_RECT)
	dim.mouse_filter = Control.MOUSE_FILTER_STOP  # deliberate: clicks stop here
	add_child(dim)
	var center := CenterContainer.new()
	center.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(center)
	var frame := SteppedFrame.new()
	frame.custom_minimum_size = Vector2(420, 0)
	frame.apply_theme(t)
	center.add_child(frame)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 12)
	frame.add_content(box)
	frame.set_content_margins(18, 16, 18, 16)
	box.add_child(Fonts.label("SHEET — PINNED", Fonts.micro_tracked(), 11, t.accent))
	_loading_label = Fonts.label("FETCHING THE RECORD…", Fonts.data(), 11, t.muted)
	box.add_child(_loading_label)
	_content_box = VBoxContainer.new()
	_content_box.add_theme_constant_override("separation", 10)
	box.add_child(_content_box)
	var close := Kit.ghost_btn("CLOSE", t)
	close.pressed.connect(_pop)
	box.add_child(close)
