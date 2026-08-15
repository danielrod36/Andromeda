class_name OverlayLayer
extends CanvasLayer
## Toasts (bottom-right stack, max 4) + modal confirms (spec §6).
## Engine messages arrive verbatim (§A1) via toast_error.

var _toast_box: VBoxContainer


func _ready() -> void:
	layer = 10
	_toast_box = VBoxContainer.new()
	_toast_box.set_anchors_preset(Control.PRESET_BOTTOM_RIGHT)
	_toast_box.grow_horizontal = Control.GROW_DIRECTION_BEGIN
	_toast_box.grow_vertical = Control.GROW_DIRECTION_BEGIN
	_toast_box.position -= Vector2(16, 16)
	_toast_box.add_theme_constant_override("separation", 8)
	_toast_box.mouse_filter = Control.MOUSE_FILTER_IGNORE  # never eat clicks
	add_child(_toast_box)


func toast(message: String, kind := "ok") -> void:
	var t := Toast.new()
	_toast_box.add_child(t)
	t.setup(message, kind, PackThemes.current)
	# remove_child (not just queue_free) so the count drops in-loop —
	# queue_free alone is deferred and this loop never terminated
	while _toast_box.get_child_count() > 4:
		var oldest: Node = _toast_box.get_child(0)
		_toast_box.remove_child(oldest)
		oldest.queue_free()


func toast_error(result: EngineResult) -> void:
	toast(result.error_message, "bad")


## Modal confirm; await it. True = confirmed.
func confirm(title: String, body: String, ok_label := "CONFIRM", cancel_label := "CANCEL") -> bool:
	var modal := _ConfirmModal.new()
	add_child(modal)
	modal.setup(title, body, ok_label, cancel_label, PackThemes.current)
	var answer: bool = await modal.chosen
	modal.queue_free()
	return answer


## Modal text prompt; await it. Returns "" when cancelled.
func prompt(title: String, placeholder := "") -> String:
	var modal := _PromptModal.new()
	add_child(modal)
	modal.setup(title, placeholder, PackThemes.current)
	var answer: String = await modal.chosen
	modal.queue_free()
	return answer


class _PromptModal:
	extends Control

	signal chosen(text: String)

	func setup(title: String, placeholder: String, t: PackTheme) -> void:
		set_anchors_preset(Control.PRESET_FULL_RECT)
		mouse_filter = Control.MOUSE_FILTER_STOP  # deliberate: clicks stop here
		var dim := ColorRect.new()
		dim.color = Color(0, 0, 0, 0.6)
		dim.set_anchors_preset(Control.PRESET_FULL_RECT)
		add_child(dim)
		var center := CenterContainer.new()
		center.set_anchors_preset(Control.PRESET_FULL_RECT)
		add_child(center)
		var frame := SteppedFrame.new()
		frame.custom_minimum_size = Vector2(420, 0)
		frame.apply_theme(t)
		center.add_child(frame)
		var box := VBoxContainer.new()
		box.add_theme_constant_override("separation", 10)
		frame.add_content(box)
		frame.set_content_margins(16, 14, 16, 14)
		box.add_child(Fonts.label(title, Fonts.inter(), 14, t.ink))
		var edit := LineEdit.new()
		edit.placeholder_text = placeholder
		edit.add_theme_font_override("font", Fonts.data())
		edit.text_submitted.connect(
			func(text: String) -> void:
				if text.strip_edges() != "":
					chosen.emit(text.strip_edges())
		)
		box.add_child(edit)
		edit.grab_focus()
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 12)
		box.add_child(row)
		var ok_btn := Kit.btn("OK", t)
		ok_btn.pressed.connect(
			func() -> void:
				if edit.text.strip_edges() != "":
					chosen.emit(edit.text.strip_edges())
		)
		row.add_child(ok_btn)
		var cancel_btn := Kit.ghost_btn("CANCEL", t)
		cancel_btn.pressed.connect(func() -> void: chosen.emit(""))
		row.add_child(cancel_btn)

	func _unhandled_input(event: InputEvent) -> void:
		# the modal owns ESC — unconsumed it falls through to ScreenStack and
		# navigates BEHIND the open prompt
		if (
			event is InputEventKey
			and event.pressed
			and not event.echo
			and event.keycode == KEY_ESCAPE
		):
			get_viewport().set_input_as_handled()
			chosen.emit("")


class _ConfirmModal:
	extends Control

	signal chosen(answer: bool)

	func setup(
		title: String, body: String, ok_label: String, cancel_label: String, theme: PackTheme
	) -> void:
		set_anchors_preset(Control.PRESET_FULL_RECT)
		mouse_filter = Control.MOUSE_FILTER_STOP  # deliberate: clicks stop here
		var dim := ColorRect.new()
		dim.color = Color(0, 0, 0, 0.6)
		dim.set_anchors_preset(Control.PRESET_FULL_RECT)
		add_child(dim)
		var center := CenterContainer.new()
		center.set_anchors_preset(Control.PRESET_FULL_RECT)
		add_child(center)
		var frame := SteppedFrame.new()
		frame.custom_minimum_size = Vector2(420, 0)
		frame.apply_theme(theme)
		center.add_child(frame)
		var box := VBoxContainer.new()
		box.add_theme_constant_override("separation", 10)
		frame.add_content(box)
		frame.set_content_margins(16, 14, 16, 14)
		box.add_child(Fonts.label(title, Fonts.inter(), 14, theme.ink))
		var body_label := Fonts.label(body, Fonts.prose(), 12, theme.muted)
		body_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		body_label.custom_minimum_size = Vector2(388, 0)
		box.add_child(body_label)
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 12)
		box.add_child(row)
		var ok_btn := Kit.btn(ok_label, theme)
		ok_btn.pressed.connect(_answer.bind(true))
		row.add_child(ok_btn)
		var cancel_btn := Kit.ghost_btn(cancel_label, theme)
		cancel_btn.pressed.connect(_answer.bind(false))
		row.add_child(cancel_btn)
		ok_btn.grab_focus()  # takes keyboard focus; Enter confirms via the button

	func _unhandled_input(event: InputEvent) -> void:
		# the modal owns ESC — unconsumed it falls through to ScreenStack and
		# navigates BEHIND the open confirm
		if (
			event is InputEventKey
			and event.pressed
			and not event.echo
			and event.keycode == KEY_ESCAPE
		):
			get_viewport().set_input_as_handled()
			_answer(false)

	func _answer(value: bool) -> void:
		chosen.emit(value)
