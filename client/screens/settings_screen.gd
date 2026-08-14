# gdlint: ignore=max-public-methods
class_name SettingsScreen
extends BaseScreen
## 05-settings.html: server-owned narrator card (keyring-backed key, live
## test), client-owned reading/audio cards (user://settings.cfg), server data
## card. Server cards persist via PUT /v1/settings/llm; client cards write
## ClientSettings immediately.

## Test hook: when set, used instead of Services.client.
var client_override: Node

var _theme: PackTheme
var _settings: Dictionary = {}
var _providers: Array = []
var _status: Dictionary = {}
var _replace_key_mode := false

var _provider_option: OptionButton
var _model_option: OptionButton
var _key_status: Label
var _key_edit: LineEdit
var _base_url_edit: LineEdit
var _retries_edit: LineEdit
var _conn_status: Label
var _storage_status: Label
var _provider_warning: Label
var _data_line: Label
var _strip: StatusStrip
var _text_speed: Kit.SegmentedControl
var _ambient_toggle: Kit.Toggle
var _motion_toggle: Kit.Toggle
var _master_slider: HSlider
var _music_slider: HSlider
var _effects_slider: HSlider


func _ready() -> void:
	_theme = PackThemes.current
	PackThemes.pack_changed.connect(_on_pack_changed)
	_rebuild()


func esc_target() -> String:
	return "title"


func screen_enter(_params: Dictionary) -> void:
	await _load_data()


func _client() -> Node:
	return client_override if client_override != null else Services.client


func _on_pack_changed(t: PackTheme) -> void:
	_theme = t
	if is_inside_tree():
		_rebuild()


func _load_data() -> void:
	var settings_res: EngineResult = await _client().get_settings()
	if settings_res.ok:
		_settings = settings_res.data
	else:
		Services.overlay.toast_error(settings_res)
	var providers_res: EngineResult = await _client().list_providers()
	if providers_res.ok:
		_providers = providers_res.data.get("providers", [])
	var status_res: EngineResult = await _client().llm_status()
	if status_res.ok:
		_status = status_res.data
	var saves_res: EngineResult = await _client().list_saves()
	var saves: Array = saves_res.data.get("saves", []) if saves_res.ok else []
	_rebuild()
	_populate(saves)


# --- view -------------------------------------------------------------------


func _rebuild() -> void:
	for child: Node in get_children():
		remove_child(child)
		child.free()
	_build()


func _build() -> void:
	var t := _theme
	var bg := ColorRect.new()
	bg.color = t.bg
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(bg)

	var root := VBoxContainer.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.add_theme_constant_override("separation", 0)
	add_child(root)
	root.add_child(Kit.screen_header("SETTINGS", t))

	var pad := MarginContainer.new()
	pad.size_flags_vertical = Control.SIZE_EXPAND_FILL
	pad.add_theme_constant_override("margin_left", 18)
	pad.add_theme_constant_override("margin_top", 16)
	pad.add_theme_constant_override("margin_right", 18)
	pad.add_theme_constant_override("margin_bottom", 18)
	root.add_child(pad)

	var scroll := ScrollContainer.new()
	scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	pad.add_child(scroll)

	var grid := HBoxContainer.new()
	grid.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	grid.add_theme_constant_override("separation", 16)
	scroll.add_child(grid)

	grid.add_child(_narrator_card(t))
	var right := VBoxContainer.new()
	right.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	right.add_theme_constant_override("separation", 16)
	grid.add_child(right)
	right.add_child(_reading_card(t))
	right.add_child(_audio_card(t))
	right.add_child(_data_card(t))

	_strip = StatusStrip.new()
	_strip.pack_theme = t
	root.add_child(_strip)


func _card_title(text: String, t: PackTheme) -> Label:
	return Fonts.label(text, Fonts.data(), 10, t.muted)


func _row(label_text: String, field: Control, t: PackTheme) -> HBoxContainer:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)
	var label := Fonts.label(label_text, Fonts.inter(), 11, t.ink)
	label.custom_minimum_size = Vector2(118, 0)
	row.add_child(label)
	field.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(field)
	return row


func _narrator_card(t: PackTheme) -> Control:
	var card := Kit.card(t)
	card.custom_minimum_size = Vector2(520, 0)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 9)
	card.add_child(box)
	box.add_child(_card_title("SERVER · THE NARRATOR", t))

	_provider_option = Kit.option(PackedStringArray(), t)
	_provider_option.item_selected.connect(_on_provider_selected)
	box.add_child(_row("Provider", _provider_option, t))

	_model_option = Kit.option(PackedStringArray(), t)
	box.add_child(_row("Model", _model_option, t))

	_key_status = Fonts.label("", Fonts.data(), 11, t.muted)
	var key_field := Kit.data_field("", t)
	(key_field.get_meta("label") as Label).queue_free()
	key_field.add_child(_key_status)
	box.add_child(_row("API key", key_field, t))

	_key_edit = LineEdit.new()
	_key_edit.secret = true
	_key_edit.visible = false
	_key_edit.add_theme_font_override("font", Fonts.data())
	box.add_child(_key_edit)

	_base_url_edit = LineEdit.new()
	_base_url_edit.placeholder_text = "provider default"
	box.add_child(_row("Base URL", _base_url_edit, t))

	_retries_edit = LineEdit.new()
	_retries_edit.text = "3"
	box.add_child(_row("Max retries", _retries_edit, t))

	_provider_warning = Fonts.label(
		"Switching provider clears the stored key — re-enter it for the new provider.",
		Fonts.prose(),
		11,
		t.danger
	)
	_provider_warning.visible = false
	_provider_warning.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	box.add_child(_provider_warning)

	var button_row := HBoxContainer.new()
	button_row.add_theme_constant_override("separation", 10)
	box.add_child(button_row)
	var test_btn := Kit.btn("TEST CONNECTION", t)
	test_btn.pressed.connect(press_test)
	button_row.add_child(test_btn)
	var save_btn := Kit.ghost_btn("SAVE", t)
	save_btn.pressed.connect(press_save)
	button_row.add_child(save_btn)
	var replace := Kit.microlink("REPLACE KEY", t)
	replace.pressed.connect(_on_replace_key)
	button_row.add_child(replace)

	_conn_status = Fonts.label("", Fonts.data(), 10, t.ok)
	box.add_child(_conn_status)
	_storage_status = Fonts.label("", Fonts.data(), 10, t.ok)
	box.add_child(_storage_status)
	var fallback_text := (
		"No OS keyring → owner-only file fallback, said so here. "
		+ "Narration falls back to templates — the game never breaks."
	)
	var fallback := Fonts.label(fallback_text, Fonts.data(), 10, t.muted)
	fallback.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	box.add_child(fallback)
	return card


func _reading_card(t: PackTheme) -> Control:
	var card := Kit.card(t)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 10)
	card.add_child(box)
	box.add_child(_card_title("CLIENT · READING", t))
	_text_speed = Kit.segmented(PackedStringArray(["SLOW", "MEDIUM", "FAST", "INSTANT"]), 1, t)
	_text_speed.option_chosen.connect(_on_text_speed)
	box.add_child(_row("Text speed", _text_speed, t))
	_ambient_toggle = Kit.toggle(bool(ClientSettings.get_value("reading/ambient_life")), t)
	_ambient_toggle.toggled.connect(
		func(on: bool) -> void: ClientSettings.set_value("reading/ambient_life", on)
	)
	var ambient_row := _row("Ambient life", _ambient_toggle, t)
	ambient_row.add_child(Fonts.label("meteors, birds, fireflies", Fonts.prose(), 11, t.muted))
	box.add_child(ambient_row)
	_motion_toggle = Kit.toggle(bool(ClientSettings.get_value("reading/reduced_motion")), t)
	_motion_toggle.toggled.connect(
		func(on: bool) -> void: ClientSettings.set_value("reading/reduced_motion", on)
	)
	var motion_row := _row("Reduced motion", _motion_toggle, t)
	motion_row.add_child(Fonts.label("stills all animation", Fonts.prose(), 11, t.muted))
	box.add_child(motion_row)
	return card


func _audio_card(t: PackTheme) -> Control:
	var card := Kit.card(t)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 10)
	card.add_child(box)
	box.add_child(_card_title("CLIENT · AUDIO", t))
	_master_slider = _wired_slider("audio/master", t)
	box.add_child(_row("Master", _master_slider, t))
	_music_slider = _wired_slider("audio/music", t)
	box.add_child(_row("Music", _music_slider, t))
	_effects_slider = _wired_slider("audio/effects", t)
	box.add_child(_row("Effects", _effects_slider, t))
	return card


func _wired_slider(key: String, t: PackTheme) -> HSlider:
	var s := Kit.slider(float(ClientSettings.get_value(key)), t)
	s.value_changed.connect(func(v: float) -> void: ClientSettings.set_value(key, v))
	return s


func _data_card(t: PackTheme) -> Control:
	var card := Kit.card(t)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 10)
	card.add_child(box)
	box.add_child(_card_title("SERVER · DATA", t))
	_data_line = Fonts.label("", Fonts.data(), 11, t.muted)
	var field := Kit.data_field("", t)
	(field.get_meta("label") as Label).queue_free()
	field.add_child(_data_line)
	box.add_child(_row("Saves", field, t))
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)
	box.add_child(row)
	var open := Kit.ghost_btn("OPEN CHRONICLES ▸", t)
	open.pressed.connect(func() -> void: navigate.emit("chronicles", {}))
	row.add_child(open)
	var export := Kit.ghost_btn("EXPORT ALL", t)
	export.pressed.connect(_on_export_all)
	row.add_child(export)
	return card


# --- data -------------------------------------------------------------------


func _populate(saves: Array) -> void:
	_provider_option.clear()
	for p: Dictionary in _providers:
		_provider_option.add_item(str(p["label"]))
		_provider_option.set_item_metadata(_provider_option.item_count - 1, str(p["id"]))
	var current_provider := str(_settings.get("provider", "anthropic"))
	for i: int in _provider_option.item_count:
		if str(_provider_option.get_item_metadata(i)) == current_provider:
			_provider_option.select(i)
	_populate_models(current_provider)
	_base_url_edit.text = str(_settings.get("base_url", ""))
	_retries_edit.text = str(int(_settings.get("max_retries", 3)))
	_update_key_status()
	_storage_status.text = _storage_line()
	_data_line.text = "saves/ · %d chronicles · autosaves on" % Kit.chronicle_count(saves)
	_strip.show_narrator_left(_status)
	_strip.set_right_plain("")


func _populate_models(provider_id: String) -> void:
	_model_option.clear()
	for p: Dictionary in _providers:
		if str(p["id"]) == provider_id:
			for preset: String in p.get("presets", []):
				_model_option.add_item(preset)
	var current_model := str(_settings.get("model", ""))
	for i: int in _model_option.item_count:
		if _model_option.get_item_text(i) == current_model:
			_model_option.select(i)


func _update_key_status() -> void:
	var tail := str(_settings.get("key_tail", ""))
	if tail == "":
		_key_status.text = "not stored — REPLACE to add"
	else:
		_key_status.text = "sk-…%s · %s" % [tail, _backend_label()]


func _backend_label() -> String:
	match str(_settings.get("key_backend", "")):
		"keyring":
			return "OS KEYRING"
		"file":
			return "OWNER-ONLY FILE"
	return "NOT STORED"


func _storage_line() -> String:
	match str(_settings.get("key_backend", "")):
		"keyring":
			return "✓ KEY STORAGE: OS KEYRING"
		"file":
			return "✓ KEY STORAGE: OWNER-ONLY FILE (no OS keyring available)"
	return "KEY STORAGE: NOT STORED"


func _selected_provider_id() -> String:
	if _provider_option.selected < 0:
		return str(_settings.get("provider", "anthropic"))
	return str(_provider_option.get_item_metadata(_provider_option.selected))


func _on_provider_selected(index: int) -> void:
	var provider_id := str(_provider_option.get_item_metadata(index))
	_provider_warning.visible = provider_id != str(_settings.get("provider", ""))
	_populate_models(provider_id)


func select_provider_index(i: int) -> void:
	_provider_option.select(i)
	_on_provider_selected(i)


func _on_replace_key() -> void:
	_replace_key_mode = true
	_key_edit.visible = true
	_key_edit.placeholder_text = "new key — empty on SAVE removes the stored key"
	_key_edit.grab_focus()


func _on_text_speed(index: int) -> void:
	var values := ["slow", "medium", "fast", "instant"]
	ClientSettings.set_value("reading/text_speed", values[index])


# --- actions ----------------------------------------------------------------


func press_test() -> void:
	_conn_status.text = "TESTING…"
	var res: EngineResult = await _client().test_settings()
	if res.ok and bool(res.data.get("ok", false)):
		_conn_status.text = (
			"✓ CONNECTION OK · %s · %dms"
			% [str(_settings.get("model", "")), int(_client().last_rtt_ms)]
		)
		_conn_status.add_theme_color_override("font_color", _theme.ok)
	else:
		var message := str(res.data.get("error", "")) if res.ok else res.error_message
		_conn_status.text = "✗ " + message
		_conn_status.add_theme_color_override("font_color", _theme.danger)


func press_save() -> void:
	var retries_text := _retries_edit.text.strip_edges()
	if not retries_text.is_valid_int() or int(retries_text) < 0 or int(retries_text) > 10:
		Services.overlay.toast("MAX RETRIES: whole number 0–10", "bad")
		return
	var payload := {
		"provider": _selected_provider_id(),
		"model": _model_option.get_item_text(maxi(_model_option.selected, 0)),
		"base_url": _base_url_edit.text.strip_edges(),
		"max_retries": int(retries_text),
		"api_key": null,
	}
	if _replace_key_mode:
		var entered := _key_edit.text.strip_edges()
		if entered == "":
			var remove: bool = await Services.overlay.confirm(
				"REMOVE THE STORED KEY?",
				"The narrator will fall back to templates until a new key is saved.",
				"REMOVE",
				"KEEP"
			)
			if not remove:
				return
			payload["api_key"] = ""
		else:
			payload["api_key"] = entered
	var res: EngineResult = await _client().put_settings(payload)
	if not res.ok:
		Services.overlay.toast_error(res)
		return
	_settings = res.data
	_replace_key_mode = false
	_key_edit.visible = false
	_key_edit.text = ""
	_update_key_status()
	_storage_status.text = _storage_line()
	_provider_warning.visible = false
	_strip.set_right_plain("SETTINGS SAVED")


func _on_export_all() -> void:
	DisplayServer.file_dialog_show(
		"EXPORT ALL CHRONICLES — choose a folder",
		"",
		"",
		false,
		DisplayServer.FILE_DIALOG_MODE_OPEN_DIR,
		PackedStringArray(),
		Callable(self, "_on_export_dir")
	)


func _on_export_dir(status: bool, paths: PackedStringArray, _selected_filter: int) -> void:
	if not status or paths.is_empty():
		return
	var dir: String = paths[0]
	var saves_res: EngineResult = await _client().list_saves()
	if not saves_res.ok:
		Services.overlay.toast_error(saves_res)
		return
	var names := {}
	for entry: Dictionary in saves_res.data.get("saves", []):
		names[str(entry["base_name"])] = true
	var exported := 0
	for save_name: String in names.keys():
		var res: EngineResult = await _client().export_save(save_name)
		if not res.ok:
			Services.overlay.toast_error(res)
			return
		var f := FileAccess.open(dir.path_join(save_name + ".json"), FileAccess.WRITE)
		if f == null:
			Services.overlay.toast("could not write into " + dir, "bad")
			return
		f.store_string(JSON.stringify(res.data))
		f.close()
		exported += 1
	Services.overlay.toast("EXPORTED %d CHRONICLES → %s" % [exported, dir], "ok")
