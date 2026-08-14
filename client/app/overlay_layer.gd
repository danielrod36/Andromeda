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
	add_child(_toast_box)


func toast(message: String, kind := "ok") -> void:
	var t := Toast.new()
	_toast_box.add_child(t)
	t.setup(message, kind, PackThemes.current)
	while _toast_box.get_child_count() > 4:
		_toast_box.get_child(0).queue_free()


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


class _ConfirmModal:
	extends Control

	signal chosen(answer: bool)

	func setup(
		title: String, body: String, ok_label: String, cancel_label: String, theme: PackTheme
	) -> void:
		set_anchors_preset(Control.PRESET_FULL_RECT)
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

	func _answer(value: bool) -> void:
		chosen.emit(value)
