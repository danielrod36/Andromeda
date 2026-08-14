# gdlint: ignore=max-public-methods
class_name Kit
extends RefCounted
## The Hi-bit Console component kit (tokens.css; spec §6). Statics only.

static var _icon: ImageTexture


static func _shadow_box(bg: Color, border: Color, border_width := 0) -> StyleBoxFlat:
	var sb := StyleBoxFlat.new()
	sb.bg_color = bg
	sb.shadow_color = Color(0, 0, 0, 0.45)
	sb.shadow_size = 0
	sb.shadow_offset = Vector2(3, 3)
	if border_width > 0:
		sb.set_border_width_all(border_width)
		sb.border_color = border
	return sb


## .btn — accent fill, bg-colored Chakra Petch 600 text.
static func btn(text: String, t: PackTheme) -> Button:
	var b := Button.new()
	b.text = text
	b.add_theme_stylebox_override("normal", _shadow_box(t.accent, t.accent))
	b.add_theme_stylebox_override("hover", _shadow_box(t.accent.lightened(0.12), t.accent))
	b.add_theme_stylebox_override("pressed", _shadow_box(t.accent.darkened(0.12), t.accent))
	b.add_theme_stylebox_override("focus", StyleBoxEmpty.new())
	b.add_theme_font_override("font", Fonts.inter())
	b.add_theme_font_size_override("font_size", 13)
	b.add_theme_color_override("font_color", t.bg)
	b.add_theme_color_override("font_hover_color", t.bg)
	b.add_theme_color_override("font_pressed_color", t.bg)
	b.custom_minimum_size = Vector2(0, 34)
	return b


## .ghostbtn — panel fill, ink text, 2px line border.
static func ghost_btn(text: String, t: PackTheme) -> Button:
	var b := Button.new()
	b.text = text
	b.add_theme_stylebox_override("normal", _shadow_box(t.panel, t.line, 2))
	b.add_theme_stylebox_override("hover", _shadow_box(t.panel, t.accent, 2))
	b.add_theme_stylebox_override("pressed", _shadow_box(t.bg, t.line, 2))
	b.add_theme_stylebox_override("focus", StyleBoxEmpty.new())
	b.add_theme_font_override("font", Fonts.inter())
	b.add_theme_font_size_override("font_size", 12)
	b.add_theme_color_override("font_color", t.ink)
	b.add_theme_color_override("font_hover_color", t.ink)
	b.add_theme_color_override("font_pressed_color", t.ink)
	b.custom_minimum_size = Vector2(0, 30)
	return b


## .microlink — VT323 underlined; bad = danger color. (Godot's Button has
## no underline property — the underline is a 1px ColorRect at the bottom.)
static func microlink(text: String, t: PackTheme, bad := false) -> Button:
	var b := Button.new()
	b.text = text
	b.flat = true
	b.add_theme_stylebox_override("focus", StyleBoxEmpty.new())
	b.add_theme_font_override("font", Fonts.micro())
	b.add_theme_font_size_override("font_size", 13)
	var color := t.danger if bad else t.muted
	b.add_theme_color_override("font_color", color)
	b.add_theme_color_override("font_hover_color", color.lightened(0.25))
	b.add_theme_color_override("font_pressed_color", color)
	var rule := ColorRect.new()
	rule.color = color
	rule.custom_minimum_size = Vector2(0, 1)
	rule.set_anchors_preset(Control.PRESET_BOTTOM_WIDE)
	rule.offset_bottom = -2
	rule.mouse_filter = Control.MOUSE_FILTER_IGNORE
	b.add_child(rule)
	return b


## .card0 — panel bg, 2px line border, hard shadow. Content goes in the
## returned container.
static func card(t: PackTheme) -> PanelContainer:
	var p := PanelContainer.new()
	p.add_theme_stylebox_override("panel", _shadow_box(t.panel, t.line, 2))
	return p


## Settings boxed field (mock 05): bg fill, 2px line border, data font.
static func data_field(text: String, t: PackTheme) -> PanelContainer:
	var p := PanelContainer.new()
	var sb := StyleBoxFlat.new()
	sb.bg_color = t.bg
	sb.set_border_width_all(2)
	sb.border_color = t.line
	sb.content_margin_left = 10
	sb.content_margin_top = 7
	sb.content_margin_right = 10
	sb.content_margin_bottom = 7
	p.add_theme_stylebox_override("panel", sb)
	var label := Fonts.label(text, Fonts.data(), 11, t.muted)
	p.add_child(label)
	p.set_meta("label", label)  # screens update text via get_meta("label")
	return p


## .px stepped frame pre-themed (accent ring / panel fill by default).
static func px_frame(t: PackTheme, ring := "accent", fill := "panel") -> SteppedFrame:
	var f := SteppedFrame.new()
	f.apply_theme(t, ring, fill)
	return f


## .mi — numbered menu docket (mock 01). note may be "".
static func menu_item(
	num: String, item_title: String, note: String, t: PackTheme, dim := false
) -> MenuDocket:
	var d := MenuDocket.new()
	d.setup(num, item_title, note, t, dim)
	return d


## Toggle (mock 05): 44×22 box, sliding knob. Emits BaseButton.toggled.
static func toggle(on: bool, t: PackTheme) -> Toggle:
	var sw := Toggle.new()
	sw.setup(on, t)
	return sw


## Slider (mock 05): 6px track, 10×14 ink handle.
static func slider(value: float, t: PackTheme) -> HSlider:
	var s := HSlider.new()
	s.min_value = 0.0
	s.max_value = 1.0
	s.step = 0.05
	s.value = value
	s.custom_minimum_size = Vector2(0, 22)
	var track := StyleBoxFlat.new()
	track.bg_color = t.bg
	track.set_border_width_all(1)
	track.border_color = t.line
	track.content_margin_top = 8
	track.content_margin_bottom = 8
	s.add_theme_stylebox_override("slider", track)
	var fill := StyleBoxFlat.new()
	fill.bg_color = t.accent
	fill.content_margin_top = 8
	fill.content_margin_bottom = 8
	s.add_theme_stylebox_override("grabber_area", fill)
	var handle := StyleBoxFlat.new()
	handle.bg_color = t.ink
	s.add_theme_stylebox_override("grabber", handle)
	s.add_theme_stylebox_override("grabber_highlight", handle)
	s.add_theme_stylebox_override("grabber_pressed", handle)
	s.add_theme_icon_override("grabber", _blank_icon())
	s.add_theme_icon_override("grabber_highlight", _blank_icon())
	s.add_theme_icon_override("grabber_pressed", _blank_icon())
	return s


static func _blank_icon() -> ImageTexture:
	if _icon == null:
		var img := Image.create(10, 14, false, Image.FORMAT_RGBA8)
		img.fill(Color.WHITE)
		_icon = ImageTexture.create_from_image(img)
	return _icon


## Segmented control (mock 05 text speed): row of equal cells, selected =
## accent fill + bg text. `option_chosen(index)` signal.
static func segmented(options: PackedStringArray, selected: int, t: PackTheme) -> SegmentedControl:
	var sc := SegmentedControl.new()
	sc.setup(options, selected, t)
	return sc


class Toggle:
	extends BaseButton
	## Mock 05 toggle: 44×22, 2px line border, 16×14 knob (ok when on, muted
	## when off). toggle_mode is on; read `button_pressed`.

	var _theme: PackTheme

	func setup(on: bool, t: PackTheme) -> void:
		_theme = t
		toggle_mode = true
		button_pressed = on
		custom_minimum_size = Vector2(44, 22)
		toggled.connect(func(_on: bool) -> void: queue_redraw())

	func _draw() -> void:
		if _theme == null:
			return
		var r := Rect2(Vector2.ZERO, size)
		draw_rect(r, _theme.bg)
		draw_rect(r, _theme.line, false, 2.0)
		var knob := Rect2(Vector2(3, 3), Vector2(16, 14))
		if button_pressed:
			knob.position.x = size.x - 19
		draw_rect(knob, _theme.ok if button_pressed else _theme.muted)


class SegmentedControl:
	extends HBoxContainer

	signal option_chosen(index: int)

	var _options := PackedStringArray()
	var _selected := 0
	var _theme: PackTheme
	var _buttons: Array = []

	func setup(options: PackedStringArray, selected: int, t: PackTheme) -> void:
		_options = options
		_selected = selected
		_theme = t
		add_theme_constant_override("separation", 0)
		for i: int in _options.size():
			var b := Button.new()
			b.text = _options[i]
			b.toggle_mode = true
			b.size_flags_horizontal = Control.SIZE_EXPAND_FILL
			b.add_theme_font_override("font", Fonts.inter())
			b.add_theme_font_size_override("font_size", 11)
			b.add_theme_stylebox_override("focus", StyleBoxEmpty.new())
			b.pressed.connect(_choose.bind(i))
			add_child(b)
			_buttons.append(b)
		_restyle()

	func selected() -> int:
		return _selected

	func _choose(index: int) -> void:
		_selected = index
		_restyle()
		option_chosen.emit(index)

	func _restyle() -> void:
		for i: int in _buttons.size():
			var b: Button = _buttons[i]
			b.button_pressed = i == _selected
			var on := i == _selected
			var sb := StyleBoxFlat.new()
			sb.bg_color = _theme.accent if on else _theme.bg
			sb.set_border_width_all(2)
			sb.border_color = _theme.line
			b.add_theme_stylebox_override("normal", sb)
			b.add_theme_stylebox_override("hover", sb)
			b.add_theme_stylebox_override("pressed", sb)
			b.add_theme_color_override("font_color", _theme.bg if on else _theme.muted)
			b.add_theme_color_override("font_hover_color", _theme.bg if on else _theme.ink)
			b.add_theme_color_override("font_pressed_color", _theme.bg if on else _theme.ink)


class MenuDocket:
	extends Button
	## Mock 01 `.mi`: [num (data, accent)] [title (inter, ink)] [note (micro,
	## muted, right)]. dim = .mi.dim (55% opacity; interactivity is decided by
	## the screen connecting docket_pressed — mock 01's Quit is dimmed but
	## functional).

	signal docket_pressed

	var _theme: PackTheme

	func setup(num: String, item_title: String, note: String, t: PackTheme, dim := false) -> void:
		_theme = t
		var sb := StyleBoxFlat.new()
		sb.bg_color = t.panel
		sb.set_border_width_all(2)
		sb.border_color = t.line
		sb.shadow_color = Color(0, 0, 0, 0.45)
		sb.shadow_size = 0
		sb.shadow_offset = Vector2(3, 3)
		sb.content_margin_left = 14
		sb.content_margin_top = 10
		sb.content_margin_right = 14
		sb.content_margin_bottom = 10
		for state: String in ["normal", "hover", "pressed"]:
			add_theme_stylebox_override(state, sb)
		add_theme_stylebox_override("focus", StyleBoxEmpty.new())
		var row := HBoxContainer.new()
		row.add_theme_constant_override("separation", 10)
		row.mouse_filter = Control.MOUSE_FILTER_IGNORE
		row.set_anchors_preset(Control.PRESET_FULL_RECT)
		add_child(row)
		row.add_child(Fonts.label(num, Fonts.data(), 10, t.accent))
		var title_label := Fonts.label(item_title, Fonts.inter(), 15, t.ink)
		title_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.add_child(title_label)
		if note != "":
			row.add_child(Fonts.label(note, Fonts.micro_tracked(), 12, t.muted))
		if dim:
			modulate.a = 0.55
		pressed.connect(func() -> void: docket_pressed.emit())

	## Screens update the note after data loads (add / replace / remove).
	func set_note(note: String) -> void:
		if get_child_count() < 1:
			return
		var row := get_child(0)
		# the note label is the last child when present
		if note == "":
			if row.get_child_count() > 2:
				row.get_child(row.get_child_count() - 1).queue_free()
			return
		if row.get_child_count() > 2:
			(row.get_child(row.get_child_count() - 1) as Label).text = note
		else:
			row.add_child(Fonts.label(note, Fonts.micro_tracked(), 12, _theme.muted))


## "2H AGO"-style relative time for save mtimes (mocks 01/02).
static func relative_mtime(mtime: float) -> String:
	var delta := int(Time.get_unix_time_from_system() - mtime)
	if delta < 3600:
		return "%dM AGO" % maxi(delta / 60, 1)
	if delta < 172800:
		return "%dH AGO" % (delta / 3600)
	return "%dD AGO" % (delta / 86400)


## Distinct-chronicle count from a /v1/saves payload (autosaves share a
## base_name with their manual save).
static func chronicle_count(saves: Array) -> int:
	var names := {}
	for entry: Dictionary in saves:
		names[str(entry.get("base_name", ""))] = true
	return names.size()
