# gdlint: ignore=max-public-methods
class_name ChroniclesScreen
extends BaseScreen
## 02-chronicles.html: save dockets (per-pack tint, autosave spine) + recap
## preview + duplicate/export/delete/import. Selecting a docket resumes a
## preview session and fetches the recap (spec §7.3 lifecycle).

## Test hook: when set, used instead of Services.client.
var client_override: Node

var _theme: PackTheme
var _saves: Array = []
var _selected := -1
var _preview_id := ""
var _preview_session: Dictionary = {}
## Generation token: every screen_exit/_load_data/select_docket entry bumps it,
## so a superseded or exited selection discards its late await results.
var _select_epoch := 0
## Captured when the export dialog OPENS — _selected may be stale by close time.
var _export_base_name := ""

var _list_box: VBoxContainer
var _spines: Array = []
var _preview_name: Label
var _preview_strip: Label
var _preview_prose: VBoxContainer
var _preview_frame: SteppedFrame
var _strip: StatusStrip


func _ready() -> void:
	_theme = PackThemes.current
	PackThemes.pack_changed.connect(_on_pack_changed)
	_rebuild()


func esc_target() -> String:
	return "title"


func screen_enter(_params: Dictionary) -> void:
	# The stack keeps this instance alive across visits; without the reset,
	# RESUME could promote the previous visit's preview session and the list
	# would briefly render against the stale selection (spec §7.3).
	_selected = -1
	_preview_session = {}
	await _load_data()


func screen_exit() -> void:
	_select_epoch += 1  # in-flight selection coroutines must discard their results
	if _preview_id != "":
		_cleanup_preview()  # fire-and-forget (spec §7.3)


func _client() -> Node:
	return client_override if client_override != null else Services.client


func _on_pack_changed(t: PackTheme) -> void:
	_theme = t
	if is_inside_tree():
		_rebuild()
		_render_list()
		_render_preview()


func _load_data() -> void:
	_select_epoch += 1  # any in-flight selection works on a stale list
	var epoch := _select_epoch
	var res: EngineResult = await _client().list_saves()
	if epoch != _select_epoch:
		return  # superseded (another reload or screen_exit) — a newer pass renders
	if res.ok:
		_saves = res.data.get("saves", [])
		_saves.sort_custom(
			func(a: Dictionary, b: Dictionary) -> bool: return float(a["mtime"]) > float(b["mtime"])
		)
	else:
		_saves = []
		Services.overlay.toast_error(res)
	_render_list()
	if not _saves.is_empty():
		await select_docket(0)
	else:
		_render_preview()


# --- view -------------------------------------------------------------------


func _rebuild() -> void:
	for child: Node in get_children():
		remove_child(child)
		child.free()
	_spines = []
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
	root.add_child(Kit.screen_header("CHRONICLES", t, "ESC — BACK TO TITLE"))

	var pad := MarginContainer.new()
	pad.size_flags_vertical = Control.SIZE_EXPAND_FILL
	pad.add_theme_constant_override("margin_left", 18)
	pad.add_theme_constant_override("margin_top", 4)
	pad.add_theme_constant_override("margin_right", 18)
	pad.add_theme_constant_override("margin_bottom", 18)
	root.add_child(pad)

	var grid := HBoxContainer.new()
	grid.add_theme_constant_override("separation", 16)
	pad.add_child(grid)

	var scroll := ScrollContainer.new()
	scroll.custom_minimum_size = Vector2(400, 0)
	grid.add_child(scroll)
	_list_box = VBoxContainer.new()
	_list_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_list_box.add_theme_constant_override("separation", 10)
	scroll.add_child(_list_box)

	_preview_frame = Kit.px_frame(t)
	_preview_frame.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	grid.add_child(_preview_frame)

	_strip = StatusStrip.new()
	_strip.pack_theme = t
	root.add_child(_strip)


func _render_list() -> void:
	for child: Node in _list_box.get_children():
		_list_box.remove_child(child)
		child.free()
	_spines = []
	for i: int in _saves.size():
		_list_box.add_child(_build_docket(i))
	_list_box.add_child(_build_import_slot())
	_render_preview()


func _pack_of(entry: Dictionary) -> PackTheme:
	if not bool(entry.get("alive", true)):
		return PackThemes.get_theme("dead")
	return PackThemes.get_theme(str(entry.get("theme_pack", "neutral")))


func _build_docket(index: int) -> Control:
	var entry: Dictionary = _saves[index]
	var t := _pack_of(entry)
	var wrap := MarginContainer.new()  # 4px room for the selection outline
	wrap.add_theme_constant_override("margin_left", 4)
	wrap.add_theme_constant_override("margin_top", 4)
	wrap.add_theme_constant_override("margin_right", 4)
	wrap.add_theme_constant_override("margin_bottom", 4)
	wrap.set_meta("index", index)
	var outline := _SelectionOutline.new()
	wrap.add_child(outline)
	outline.set_anchors_preset(Control.PRESET_FULL_RECT)

	var frame := Kit.px_frame(t)
	frame.set_content_margins(10, 10, 12, 10)
	wrap.add_child(frame)

	var row := HBoxContainer.new()
	frame.add_content(row)
	var text_box := VBoxContainer.new()
	text_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(text_box)

	var display_name := str(entry.get("character_name", ""))
	if display_name == "":
		display_name = str(entry.get("base_name", ""))
	text_box.add_child(Fonts.label(display_name, Fonts.inter(), 15, t.ink))

	var career := str(entry.get("career", ""))
	var line1 := (
		"%s · TERM %d"
		% [career.to_upper() if career != "" else "IN CHARGEN", int(entry.get("terms", 0))]
	)
	if not bool(entry.get("alive", true)):
		line1 += " · MEMORIALIZED"
	var autosave := bool(entry.get("autosave", false))
	var line2 := (
		"%s · %s"
		% ["AUTO" if autosave else "MANUAL", Kit.relative_mtime(float(entry.get("mtime", 0.0)))]
	)
	text_box.add_child(Fonts.label(line1 + "\n" + line2, Fonts.data(), 10, t.muted))

	var spine := _Spine.new()
	if not bool(entry.get("alive", true)):
		spine.text_content = "✝ R.I.P."
		spine.text_color = t.danger
	elif autosave:
		spine.text_content = (
			"AUTO·" + Kit.relative_mtime(float(entry.get("mtime", 0.0))).trim_suffix(" AGO")
		)
		spine.text_color = t.accent
	else:
		spine.text_content = "MANUAL"
		spine.text_color = t.accent
	spine.line_color = t.line
	spine.custom_minimum_size = Vector2(24, 0)
	row.add_child(spine)
	_spines.append(spine)

	var click := Button.new()  # invisible full-rect click layer
	click.flat = true
	click.set_anchors_preset(Control.PRESET_FULL_RECT)
	click.add_theme_stylebox_override("focus", StyleBoxEmpty.new())
	click.pressed.connect(_on_docket_pressed.bind(index))
	wrap.add_child(click)
	return wrap


func _build_import_slot() -> Control:
	var t := _theme
	var wrap := MarginContainer.new()
	wrap.add_theme_constant_override("margin_left", 4)
	wrap.add_theme_constant_override("margin_top", 4)
	wrap.add_theme_constant_override("margin_right", 4)
	wrap.add_theme_constant_override("margin_bottom", 4)
	wrap.modulate.a = 0.55
	var frame := Kit.px_frame(t, "line", "panel")
	frame.set_content_margins(10, 10, 12, 10)
	wrap.add_child(frame)
	var box := VBoxContainer.new()
	frame.add_content(box)
	box.add_child(Fonts.label("— empty slot —", Fonts.inter(), 15, t.muted))
	box.add_child(Fonts.label("IMPORT A SAVE FILE…", Fonts.data(), 10, t.muted))
	var click := Button.new()
	click.flat = true
	click.set_anchors_preset(Control.PRESET_FULL_RECT)
	click.add_theme_stylebox_override("focus", StyleBoxEmpty.new())
	click.pressed.connect(press_import)
	wrap.add_child(click)
	return wrap


func _render_preview() -> void:
	_preview_frame.clear_content()
	var t := _theme
	if _selected >= 0 and _selected < _saves.size():
		t = _pack_of(_saves[_selected])
	_preview_frame.apply_theme(t)
	_preview_frame.set_content_margins(18, 16, 18, 16)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 10)
	_preview_frame.add_content(box)
	_preview_name = Fonts.label("", Fonts.title(), 22, t.ink)
	box.add_child(_preview_name)
	_preview_strip = Fonts.label("", Fonts.data(), 10, t.muted)
	box.add_child(_preview_strip)
	box.add_child(Fonts.label("THE STORY SO FAR", Fonts.data(), 10, t.accent))
	_preview_prose = VBoxContainer.new()
	_preview_prose.add_theme_constant_override("separation", 8)
	box.add_child(_preview_prose)
	var actions := HBoxContainer.new()
	actions.add_theme_constant_override("separation", 14)
	box.add_child(actions)
	var resume := Kit.btn("RESUME ▸", t)
	resume.pressed.connect(func() -> void: press_action("resume"))
	actions.add_child(resume)
	var dup := Kit.microlink("DUPLICATE", t)
	dup.pressed.connect(func() -> void: press_action("duplicate"))
	actions.add_child(dup)
	var exp := Kit.microlink("EXPORT", t)
	exp.pressed.connect(func() -> void: press_action("export"))
	actions.add_child(exp)
	var del := Kit.microlink("DELETE", t, true)
	del.pressed.connect(func() -> void: press_action("delete"))
	actions.add_child(del)
	if _selected >= 0 and _selected < _saves.size():
		_fill_preview_text()


func _fill_preview_text() -> void:
	var entry: Dictionary = _saves[_selected]
	var display_name := str(entry.get("character_name", ""))
	if display_name == "":
		display_name = str(entry.get("base_name", ""))
	_preview_name.text = display_name
	var career := str(entry.get("career", ""))
	_preview_strip.text = (
		"%s · %d TERMS · %s PACK"
		% [
			career.to_upper() if career != "" else "IN CHARGEN",
			int(entry.get("terms", 0)),
			str(entry.get("theme_pack", "")).to_upper(),
		]
	)


func _render_recap(lines: Array) -> void:
	for child: Node in _preview_prose.get_children():
		_preview_prose.remove_child(child)
		child.free()
	var t := _pack_of(_saves[_selected]) if _selected >= 0 else _theme
	if lines.is_empty():
		_preview_prose.add_child(Fonts.label("No recap recorded yet.", Fonts.prose(), 13, t.muted))
		return
	for line: String in lines:
		var muted := line.to_lower().begins_with("unresolved")
		var label := Fonts.label(line, Fonts.prose(), 14, t.muted if muted else t.ink)
		label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		label.custom_minimum_size = Vector2(520, 0)
		_preview_prose.add_child(label)


# --- selection + preview session (spec §7.3) --------------------------------


func docket_count() -> int:
	return _list_box.get_child_count()


func _on_docket_pressed(index: int) -> void:
	await select_docket(index)


func select_docket(index: int) -> void:
	_select_epoch += 1  # this selection supersedes any in-flight one
	var epoch := _select_epoch
	_selected = index
	for i: int in _list_box.get_child_count() - 1:  # last child is the import slot
		var outline := _list_box.get_child(i).get_child(0) as _SelectionOutline
		outline.on = i == index
		if i == index:
			outline.color = _pack_of(_saves[i]).accent
		outline.queue_redraw()
	_render_preview()
	if index < 0 or index >= _saves.size():
		return
	# Capture before awaiting: the list may re-sort (or shrink) while we wait.
	var entry: Dictionary = _saves[index]
	var base := str(entry["base_name"])
	await _cleanup_preview()
	if epoch != _select_epoch:
		return  # superseded (new selection, reload, or screen_exit)
	var res: EngineResult = await _client().resume_session(base)
	if epoch != _select_epoch:
		# Late result — discard it, and don't leak the preview it created.
		if res.ok:
			var late_id := str(res.data["session"].get("id", ""))
			if late_id != _preview_id:  # a newer selection may already own it
				await _client().delete_session(late_id)
		return
	if index >= _saves.size():
		return  # the list shrank while we awaited
	if not res.ok:
		Services.overlay.toast_error(res)
		return
	_preview_session = res.data["session"]
	_preview_id = str(_preview_session.get("id", ""))
	var recap_res: EngineResult = await _client().recap(_preview_id)
	if epoch != _select_epoch or index >= _saves.size():
		return  # superseded, or the list shrank while we awaited
	if recap_res.ok:
		_render_recap(recap_res.data.get("lines", []))
	else:
		Services.overlay.toast_error(recap_res)


func _cleanup_preview() -> void:
	if _preview_id == "":
		return
	var id := _preview_id
	_preview_id = ""
	_preview_session = {}
	await _client().delete_session(id)


# --- actions ----------------------------------------------------------------


func press_action(what: String) -> void:
	if _selected < 0 or _selected >= _saves.size():
		return
	var entry: Dictionary = _saves[_selected]
	match what:
		"resume":
			if _preview_session.is_empty():
				return
			SessionStore.set_current(_preview_session)
			_preview_id = ""  # promoted — screen_exit must not delete it
			var pack_id := str(entry.get("theme_pack", "neutral"))
			# Navigate first: applying the pack before leaving rebuilds this
			# screen while it is still the visible one (visible flicker).
			navigate.emit("stub", {"session": _preview_session})
			ClientSettings.set_value("ui/last_played_pack", pack_id)
			PackThemes.apply(pack_id)
		"duplicate":
			var entered: String = await Services.overlay.prompt(
				"DUPLICATE AS…", "new chronicle name"
			)
			if entered == "":
				return
			var res: EngineResult = await _client().duplicate_save(str(entry["base_name"]), entered)
			if not res.ok:
				Services.overlay.toast_error(res)
				return
			await _load_data()
		"export":
			_export_base_name = str(entry["base_name"])  # _selected may go stale
			DisplayServer.file_dialog_show(
				"EXPORT CHRONICLE — choose a folder",
				"",
				"",
				false,
				DisplayServer.FILE_DIALOG_MODE_OPEN_DIR,
				PackedStringArray(),
				Callable(self, "_on_export_dir")
			)
		"delete":
			var confirmed: bool = await Services.overlay.confirm(
				"DELETE %s?" % str(entry.get("character_name", entry["base_name"])).to_upper(),
				"The chronicle and its autosave are removed from disk. This is not recoverable.",
				"DELETE",
				"KEEP"
			)
			if not confirmed:
				return
			var res: EngineResult = await _client().delete_save(str(entry["base_name"]))
			if not res.ok:
				Services.overlay.toast_error(res)
				return
			Services.overlay.toast(
				"%d FILES REMOVED" % Array(res.data.get("deleted", [])).size(), "ok"
			)
			await _cleanup_preview()
			_selected = -1
			await _load_data()


func _on_export_dir(status: bool, paths: PackedStringArray, _selected_filter: int) -> void:
	var base := _export_base_name
	_export_base_name = ""  # one-shot, captured when the dialog was opened
	if not status or paths.is_empty() or base == "":
		return
	var res: EngineResult = await _client().export_save(base)
	if not res.ok:
		Services.overlay.toast_error(res)
		return
	var path: String = paths[0].path_join(base + ".json")
	if FileAccess.file_exists(path):
		var overwrite: bool = await Services.overlay.confirm(
			"OVERWRITE %s?" % path.get_file(),
			"A file with this name already exists in that folder.",
			"OVERWRITE",
			"SKIP"
		)
		if not overwrite:
			return
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f == null:
		Services.overlay.toast("could not write " + path, "bad")
		return
	f.store_string(JSON.stringify(res.data))
	f.close()
	Services.overlay.toast("EXPORTED → " + path, "ok")


func press_import() -> void:
	DisplayServer.file_dialog_show(
		"IMPORT A SAVE FILE",
		"",
		"",
		false,
		DisplayServer.FILE_DIALOG_MODE_OPEN_FILE,
		PackedStringArray(["*.json ; Andromeda save"]),
		Callable(self, "_on_import_file")
	)


func _on_import_file(status: bool, paths: PackedStringArray, _selected_filter: int) -> void:
	if not status or paths.is_empty():
		return
	var path: String = paths[0]
	var text := FileAccess.get_file_as_string(path)
	var parsed: Variant = JSON.parse_string(text)
	if not (parsed is Dictionary):
		Services.overlay.toast("that file isn't a chronicle", "bad")
		return
	var stem := path.get_file().get_basename()
	var entered: String = await Services.overlay.prompt("IMPORT AS…", stem)
	if entered == "":
		return
	var res: EngineResult = await _client().import_save(entered, parsed)
	if not res.ok:
		Services.overlay.toast_error(res)
		return
	Services.overlay.toast("IMPORTED AS " + entered.to_upper(), "ok")
	await _load_data()


# --- inner components ---------------------------------------------------------


class _SelectionOutline:
	extends Control
	## 2px accent outline drawn when the docket is selected (mock 02).

	var on := false
	var color := Color.WHITE

	func _ready() -> void:
		mouse_filter = Control.MOUSE_FILTER_IGNORE

	func _draw() -> void:
		if on:
			draw_rect(Rect2(Vector2.ZERO, size), color, false, 2.0)


class _Spine:
	extends Control
	## Vertical spine text (mock 02 writing-mode: vertical-rl) + dashed rule.

	var text_content := ""
	var text_color := Color.WHITE
	var line_color := Color.WHITE

	func _ready() -> void:
		mouse_filter = Control.MOUSE_FILTER_IGNORE

	func _draw() -> void:
		# dashed 2px rule on the left edge (2px on / 2px off)
		var y := 0.0
		while y < size.y:
			draw_rect(Rect2(Vector2(0, y), Vector2(2, minf(2.0, size.y - y))), line_color)
			y += 4.0
		# vertical text, top-to-bottom
		draw_set_transform(Vector2(size.x / 2 + 5, 6), PI / 2)
		draw_string(
			Fonts.micro(), Vector2.ZERO, text_content, HORIZONTAL_ALIGNMENT_LEFT, -1, 12, text_color
		)
		draw_set_transform(Vector2.ZERO, 0.0)
