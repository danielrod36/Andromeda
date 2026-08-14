class_name Toast
extends Control
## tokens.css .toast — engine strings verbatim (spec §6.6). Self-dismisses
## after 6s. Kind ∈ ok | warn | bad (left bar: ok / accent / danger).

var _message := ""
var _kind := "ok"
var _theme: PackTheme


func setup(message: String, kind: String, theme: PackTheme) -> void:
	_message = message
	_kind = kind
	_theme = theme
	mouse_filter = Control.MOUSE_FILTER_IGNORE  # toasts never eat clicks
	custom_minimum_size = Vector2(320, 34)
	var label := Fonts.label(message, Fonts.data(), 11, theme.ink)
	label.position = Vector2(12, 9)
	label.size = Vector2(300, 16)
	label.clip_text = true
	add_child(label)
	var timer := Timer.new()
	timer.wait_time = 6.0
	timer.one_shot = true
	timer.timeout.connect(queue_free)
	add_child(timer)
	timer.start()


func _draw() -> void:
	if _theme == null:
		return
	var r := Rect2(Vector2.ZERO, size)
	# hard 3px offset shadow
	draw_rect(Rect2(Vector2(3, 3), size), Color(0, 0, 0, 0.45))
	draw_rect(r, _theme.panel)
	draw_rect(r, _theme.line, false, 2.0)
	var bar := _theme.ok
	match _kind:
		"warn":
			bar = _theme.accent
		"bad":
			bar = _theme.danger
	draw_rect(Rect2(Vector2.ZERO, Vector2(3, size.y)), bar)
