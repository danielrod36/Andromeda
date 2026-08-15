# gdlint: ignore=max-public-methods
class_name TitleScreen
extends BaseScreen
## 01-title.html: console boot. Pack-neutral graphite at first boot; tints to
## ClientSettings ui/last_played_pack on return. Left rail 380px: wordmark,
## kicker, accent rule + motif, numbered menu dockets, boot readout. Right:
## SceneBackdrop viewport (sc-night). Bottom: StatusStrip.

const _MENU := [
	["continue", "01", "Continue"],
	["new_journey", "02", "New Journey"],
	["chronicles", "03", "Chronicles"],
	["settings", "04", "Settings"],
	["quit", "05", "Quit"],
]

## Test hook: when set, used instead of Services.client.
var client_override: Node

var _theme: PackTheme
var _boot_lines: Array = []
var _saves: Array = []
var _status: Dictionary = {}
var _menu := {}  # action -> {docket, note, enabled}
var _continuing := false
var _boot_label: Label
var _strip: StatusStrip
var _backdrop: SceneBackdrop


func _ready() -> void:
	_theme = PackThemes.current
	PackThemes.pack_changed.connect(_on_pack_changed)
	_rebuild()


func esc_target() -> String:
	return ""  # nowhere to go back to


func screen_enter(params: Dictionary) -> void:
	_boot_lines = params.get("boot_lines", [])
	# Return-visit tint (mock 01): apply the last-played pack.
	var last := str(ClientSettings.get_value("ui/last_played_pack"))
	if last != "" and PackThemes.current.id != last:
		PackThemes.apply(last)
	else:
		_rebuild()
	await _load_data()


func _client() -> Node:
	return client_override if client_override != null else Services.client


func _on_pack_changed(t: PackTheme) -> void:
	_theme = t
	if is_inside_tree():
		_rebuild()


func _load_data() -> void:
	var saves_res: EngineResult = await _client().list_saves()
	if saves_res.ok:
		_saves = saves_res.data.get("saves", [])
	else:
		_saves = []
		Services.overlay.toast_error(saves_res)
	var status_res: EngineResult = await _client().llm_status()
	if status_res.ok:
		_status = status_res.data
	_apply_data()


# --- view -------------------------------------------------------------------


func _rebuild() -> void:
	for child: Node in get_children():
		remove_child(child)
		child.free()
	_menu = {}
	_build()
	_apply_data()


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

	var body := HBoxContainer.new()
	body.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_theme_constant_override("separation", 0)
	root.add_child(body)

	_build_rail(body, t)

	_backdrop = SceneBackdrop.new()
	_backdrop.pack_theme = t
	_backdrop.scene_id = "night"
	_backdrop.kicker_text = "◤ VIEWPORT · DEEP FIELD"
	_backdrop.footer_text = "RUUTH PRIME ORBIT · LOCAL DRIFT"
	_backdrop.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	body.add_child(_backdrop)

	_strip = StatusStrip.new()
	_strip.pack_theme = t
	root.add_child(_strip)


func _build_rail(body: HBoxContainer, t: PackTheme) -> void:
	var rail := PanelContainer.new()
	rail.custom_minimum_size = Vector2(380, 0)
	var rail_sb := StyleBoxFlat.new()
	rail_sb.bg_color = t.bg
	rail_sb.border_width_right = 2
	rail_sb.border_color = t.line
	rail.add_theme_stylebox_override("panel", rail_sb)
	body.add_child(rail)

	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 28)
	margin.add_theme_constant_override("margin_top", 38)
	margin.add_theme_constant_override("margin_right", 28)
	margin.add_theme_constant_override("margin_bottom", 16)
	rail.add_child(margin)

	var col := VBoxContainer.new()
	col.add_theme_constant_override("separation", 8)
	margin.add_child(col)

	var wordmark_font := FontVariation.new()
	wordmark_font.base_font = Fonts.title()
	wordmark_font.spacing_glyph = 6  # .16em at 40px
	col.add_child(Fonts.label("ANDROMEDA", wordmark_font, 40, t.ink))
	col.add_child(Fonts.label("WRITTEN IN THE STARS", Fonts.micro_tracked(), 12, t.accent))

	var rule := _AccentRule.new()
	rule.pack_theme = t
	col.add_child(rule)

	var spacer_top := Control.new()
	spacer_top.custom_minimum_size = Vector2(0, 12)
	col.add_child(spacer_top)

	for entry: Array in _MENU:
		var action: String = entry[0]
		var docket := Kit.menu_item(entry[1], entry[2], "", t)
		docket.docket_pressed.connect(_on_menu_pressed.bind(action))
		col.add_child(docket)
		_menu[action] = {"docket": docket, "note": ""}

	var spacer := Control.new()
	spacer.size_flags_vertical = Control.SIZE_EXPAND_FILL
	col.add_child(spacer)

	_boot_label = Fonts.label("", Fonts.micro_tracked(), 12, t.muted)
	col.add_child(_boot_label)


class _AccentRule:
	extends Control
	## Mock 01: 190×2 accent rule with the pack motif at its right end.

	var pack_theme: PackTheme

	func _init() -> void:
		custom_minimum_size = Vector2(190, 10)

	func _draw() -> void:
		if pack_theme == null:
			return
		draw_rect(Rect2(Vector2(0, 4), Vector2(190, 2)), pack_theme.accent)
		draw_string(
			Fonts.micro(),
			Vector2(196, 12),
			pack_theme.motif,
			HORIZONTAL_ALIGNMENT_LEFT,
			-1,
			12,
			pack_theme.accent
		)


# --- data -------------------------------------------------------------------


func _apply_data() -> void:
	if _boot_label == null:
		return
	_boot_label.text = "\n".join(PackedStringArray(_boot_lines))
	# Continue: most recently modified entry (spec §7.1).
	var latest := {}
	for entry: Dictionary in _saves:
		if latest.is_empty() or float(entry["mtime"]) > float(latest["mtime"]):
			latest = entry
	var continue_note := ""
	if not latest.is_empty():
		var who := str(latest.get("character_name", ""))
		if who == "":
			who = str(latest.get("base_name", ""))
		continue_note = "%s · %s" % [who.to_upper(), Kit.relative_mtime(float(latest["mtime"]))]
	_set_menu_note("continue", continue_note, not latest.is_empty())
	_set_menu_note("chronicles", "%d SAVES" % Kit.chronicle_count(_saves), true)
	_set_menu_note("new_journey", "", true)
	_set_menu_note("settings", "", true)
	_set_menu_note("quit", "", true)
	(_menu["quit"]["docket"] as Control).modulate.a = 0.55  # dim styling per mock
	_strip.pack_theme = _theme
	_strip.restyle()
	_strip.refresh(_status)


func _set_menu_note(action: String, note: String, enabled: bool) -> void:
	var entry: Dictionary = _menu[action]
	entry["note"] = note
	entry["enabled"] = enabled
	var docket: Kit.MenuDocket = entry["docket"]
	docket.set_note(note)
	docket.disabled = not enabled


# --- accessors used by tests ------------------------------------------------


func menu_note(action: String) -> String:
	return str(_menu.get(action, {}).get("note", ""))


func menu_enabled(action: String) -> bool:
	return bool(_menu.get(action, {}).get("enabled", false))


func boot_text() -> String:
	return _boot_label.text


## Programmatic menu press (tests + keyboard later).
func press_menu(action: String) -> void:
	if menu_enabled(action):
		_on_menu_pressed(action)


func _on_menu_pressed(action: String) -> void:
	match action:
		"new_journey", "chronicles", "settings":
			navigate.emit(action, {})
		"quit":
			Services.shutdown()
			get_tree().quit()
		"continue":
			_continue()


func _continue() -> void:
	if _continuing:  # a second press during the resume await must not double-run
		return
	_continuing = true
	var latest := {}
	for entry: Dictionary in _saves:
		if latest.is_empty() or float(entry["mtime"]) > float(latest["mtime"]):
			latest = entry
	if latest.is_empty():
		_continuing = false
		return
	var res: EngineResult = await _client().resume_session(str(latest["base_name"]))
	if not res.ok:
		Services.overlay.toast_error(res)
		_continuing = false
		return
	var session: Dictionary = res.data["session"]
	if not _client().contract_matches(session):
		# Report the contract of the session's kind, not always chargen's.
		var engine_version: int = (
			_client().contract_adventure
			if str(session.get("kind", "")) == "adventure"
			else _client().contract_chargen
		)
		Services.overlay.toast(
			(
				"contract drift: chronicle v%d, engine v%d — update the client"
				% [int(session.get("contract_version", -1)), engine_version]
			),
			"bad"
		)
		_continuing = false
		return
	SessionStore.set_current(session)
	_reset_continuing.call_deferred()  # one-shot: a same-frame re-press stays blocked
	navigate.emit("stub", {"session": session})
	# Apply the pack after navigating: applying first rebuilds this screen
	# while it is still the visible one (visible flicker).
	ClientSettings.set_value("ui/last_played_pack", str(latest.get("theme_pack", "")))
	PackThemes.apply(str(latest.get("theme_pack", "neutral")))


func _reset_continuing() -> void:
	_continuing = false
