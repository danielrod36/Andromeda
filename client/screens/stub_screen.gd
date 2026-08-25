class_name StubScreen
extends BaseScreen
## The honest boundary gate (spec M2-D8): session created/resumed, the real
## screen arrives in a later milestone. Renders the session's current view as
## cockpit data — real wiring, inspectable, replaced wholesale by M3/M4.

var _session: Dictionary = {}
var _title := ""
var _title_label: Label
var _view_dump: Label


func esc_target() -> String:
	return "title"


func screen_enter(params: Dictionary) -> void:
	_session = params.get("session", {})
	var kind := str(_session.get("kind", ""))
	var view: Dictionary = _view()
	if kind == "chargen":
		_title = "THE CHARGEN SHELL arrives later in M3"
	elif bool(view.get("game_over", false)):
		_title = "THE MEMORIAL arrives in M4"
	else:
		_title = "THE ADVENTURE SHELL arrives in M4"
	_rebuild()


func title_text() -> String:
	return _title


## The server sends view: null once chargen completes (spec §A3) — guard the
## present-but-null case; Dictionary.get only defaults on a missing key.
func _view() -> Dictionary:
	var raw: Variant = _session.get("view")
	return raw if raw is Dictionary else {}


func _rebuild() -> void:
	for child: Node in get_children():
		remove_child(child)
		child.free()
	var t := PackThemes.current
	var bg := ColorRect.new()
	bg.color = t.bg
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(bg)
	var center := CenterContainer.new()
	center.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(center)
	var frame := Kit.px_frame(t)
	frame.custom_minimum_size = Vector2(640, 0)
	center.add_child(frame)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 10)
	frame.add_content(box)
	frame.set_content_margins(18, 16, 18, 16)
	_title_label = Fonts.label(_title, Fonts.inter(), 16, t.accent)
	box.add_child(_title_label)
	(
		box
		. add_child(
			(
				Fonts
				. label(
					(
						"SESSION %s · %s · phase %s · contract v%d"
						% [
							str(_session.get("id", "")),
							str(_session.get("kind", "")).to_upper(),
							str(_session.get("phase", "")),
							int(_session.get("contract_version", -1)),
						]
					),
					Fonts.data(),
					10,
					t.muted
				)
			)
		)
	)
	var prompt := str(_view().get("prompt", ""))
	if prompt != "":
		box.add_child(Fonts.label(prompt, Fonts.prose(), 13, t.ink))
	var scroll := ScrollContainer.new()
	scroll.custom_minimum_size = Vector2(600, 260)
	box.add_child(scroll)
	_view_dump = Label.new()
	_view_dump.text = JSON.stringify(_session.get("view", {}), "  ")
	_view_dump.add_theme_font_override("font", Fonts.data())
	_view_dump.add_theme_font_size_override("font_size", 10)
	_view_dump.add_theme_color_override("font_color", t.muted)
	scroll.add_child(_view_dump)
	box.add_child(Fonts.label("ESC — BACK TO TITLE", Fonts.micro_tracked(), 12, t.muted))
