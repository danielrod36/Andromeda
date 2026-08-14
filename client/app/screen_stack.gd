class_name ScreenStack
extends Control
## Push/replace/pop navigation (spec §6). Instant swaps in M2 — transitions
## are M5 polish. M2 screens navigate with `replace` only (the stack stays
## one deep); push/pop exist for M3+ overlays.

signal screen_changed(screen_name: String)

var _screens := {}
var _stack: Array = []


func register(screen_name: String, screen: Control) -> void:
	_screens[screen_name] = screen
	screen.visible = false
	add_child(screen)
	screen.set_anchors_preset(Control.PRESET_FULL_RECT)


func current_name() -> String:
	return str(_stack[-1]) if not _stack.is_empty() else ""


func current() -> Control:
	return _screens.get(current_name())


func replace(screen_name: String, params := {}) -> void:
	_hide_top()
	if _stack.is_empty():
		_stack.append(screen_name)
	else:
		_stack[-1] = screen_name
	_show_top(params)


func push(screen_name: String, params := {}) -> void:
	_hide_top()
	_stack.append(screen_name)
	_show_top(params)


func pop(params := {}) -> void:
	if _stack.size() <= 1:
		return
	_hide_top()
	_stack.pop_back()
	_show_top(params)


func _hide_top() -> void:
	if _stack.is_empty():
		return
	var old: Control = _screens[_stack[-1]]
	if old is BaseScreen:
		old.screen_exit()
	old.visible = false


func _show_top(params: Dictionary) -> void:
	var top: Control = _screens[_stack[-1]]
	top.visible = true
	if top is BaseScreen:
		top.screen_enter(params)
	screen_changed.emit(_stack[-1])


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo and event.keycode == KEY_ESCAPE:
		var top := current()
		if top is BaseScreen and top.esc_target() != "":
			replace(top.esc_target())
			get_viewport().set_input_as_handled()
