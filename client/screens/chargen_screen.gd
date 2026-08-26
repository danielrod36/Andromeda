# gdlint: ignore=max-public-methods
class_name ChargenScreen
extends BaseScreen
## The chargen shell (mockup 06): journey strip over a night scene, a stage
## that renders ANY ChoicePointView (every phase playable from this frame
## alone — bespoke stages C5-C7 dress on top), a prose strip fed by the
## BeatDirector, and a dockbar with the sheet drawer (first push/pop
## consumer). 'complete' routes to the reveal (C8; stub until then).

const _RAIL_WIDTH := 300

## Test hook: when set, used instead of Services.client.
var client_override: Node
## Test hook: when set, handed to the BeatDirector instead of its own pump.
var pump_override: Node

var _theme: PackTheme
var _session := {}
var _director: BeatDirector
## Guards the reconnect fetch across re-entry/exit.
var _epoch := 0

var _backdrop: SceneBackdrop
var _strip: JourneyStrip
var _stage_holder: Control
var _prose: TypewriterProse
var _dockbar: HBoxContainer
var _sheet_btn: Button
var _subnote: Label
## Current generic-stage nodes, rebuilt per envelope.
var _prompt_label: Label
var _receipts_box: VBoxContainer
var _cards_box: GridContainer
var _cards: Array = []


func _ready() -> void:
	_theme = PackThemes.current
	PackThemes.pack_changed.connect(_on_pack_changed)
	_director = BeatDirector.new()
	# Configure BEFORE add_child: BeatDirector._ready spawns its own pump
	# when none is injected (the fake arrives via pump_override first).
	_director.configure(_client(), pump_override)
	add_child(_director)
	_director.block_received.connect(_on_block_received)
	_director.receipts_ready.connect(_on_receipts)
	_director.beat_finished.connect(_on_beat_finished)
	_director.beat_failed.connect(_on_beat_failed)
	_build()


func esc_target() -> String:
	return "title"


func screen_enter(params: Dictionary) -> void:
	_epoch += 1
	# pop() re-enters with EMPTY params — a live session means "resume",
	# never "leave". Only a genuinely absent session routes home.
	var session: Variant = params.get("session")
	if not (session is Dictionary) or (session as Dictionary).is_empty():
		if _session.is_empty():
			navigate.emit("title", {})
			return
		_apply_envelope(_session)
		return
	if str((session as Dictionary).get("kind", "")) == "adventure":
		# Defensive: an adventure envelope never renders here (M4's shell).
		navigate.emit("stub", {"session": session})
		return
	_session = session
	_apply_envelope(_session)
	_reconnect()


func screen_exit() -> void:
	_epoch += 1
	# Abandon an in-flight beat — but NEVER synchronously: skip() emits
	# beat_finished → _apply_envelope → navigate.emit while the stack is
	# still inside its own transition (re-entrant replace corrupts it).
	# Deferred one frame, the stack's transition has committed; a hidden
	# screen's _on_beat_finished stashes instead of applying.
	if _director != null and _director.state != BeatDirector.State.IDLE:
		var director := _director
		var epoch := _epoch
		_deferred_abandon.call_deferred(director, epoch)


func _deferred_abandon(director: BeatDirector, epoch: int) -> void:
	if epoch != _epoch or not is_instance_valid(director):
		return  # re-entered (or freed) before the frame landed — keep the beat
	if director.state == BeatDirector.State.NARRATING:
		director.skip()
	# CHOOSING/RECEIPTS: the choose await resolves later and run()'s stale
	# generation check drops it; nothing else to do.


func _on_pack_changed(t: PackTheme) -> void:
	# Unconditional: chargen is registered at boot and stays in the tree
	# hidden — a pack switch in Settings must retheme the frame or a later
	# entry renders the NEW stage inside the OLD frame (screen_enter never
	# rebuilds the frame; _apply_envelope re-renders content only).
	_theme = t
	if is_inside_tree():
		_build()
		if not _session.is_empty():
			_apply_envelope(_session)


func _client() -> Node:
	return client_override if client_override != null else Services.client


## Params may be stale (session created screens ago) — re-fetch the truth.
func _reconnect() -> void:
	var epoch := _epoch
	var res: EngineResult = await _client().get_session(str(_session.get("id", "")))
	if epoch != _epoch or not is_inside_tree() or not visible:
		return
	if not res.ok:
		Services.overlay.toast_error(res)
		return
	_apply_envelope(res.data.get("session", {}))


# --- envelope application ------------------------------------------------------


func _apply_envelope(session: Dictionary) -> void:
	if session.is_empty():
		return
	_session = session
	if is_instance_valid(_strip):
		_strip.set_phase(str(session.get("phase", "")))
	if is_instance_valid(_backdrop):
		_backdrop.kicker_text = _kicker_text(str(session.get("phase", "")))
	if str(session.get("phase", "")) == "complete":
		navigate.emit("reveal", {"session": session})
		return
	_render_view(session.get("view", {}))


## `view` arrives as an explicit null for complete sessions — soft-typed so
## the guard below can handle it instead of raising on the call boundary.
func _render_view(view: Variant) -> void:
	if not (view is Dictionary) or (view as Dictionary).is_empty():
		return
	_clear_stage()
	var v: Dictionary = view
	var prompt := str(v.get("prompt", ""))
	if prompt != "":
		_prompt_label = Fonts.label(prompt, Fonts.prose(), 16, _theme.ink)
		_prompt_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		_prompt_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		_prompt_label.custom_minimum_size = Vector2(560, 0)
		_prompt_label.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
		_stage_holder.add_child(_prompt_label)
	_receipts_box = VBoxContainer.new()
	_receipts_box.add_theme_constant_override("separation", 6)
	_receipts_box.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	_stage_holder.add_child(_receipts_box)
	_cards_box = GridContainer.new()
	_cards_box.columns = 3
	_cards_box.add_theme_constant_override("h_separation", 10)
	_cards_box.add_theme_constant_override("v_separation", 10)
	_cards_box.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	_stage_holder.add_child(_cards_box)
	var options: Array = v.get("options", [])
	for i: int in options.size():
		var option: Dictionary = options[i]
		_cards_box.add_child(_build_card(option, i))
	_refresh_cards_enabled()
	_refresh_subnote(view)


func _clear_stage() -> void:
	_cards = []
	if is_instance_valid(_stage_holder):
		for child: Node in _stage_holder.get_children():
			_stage_holder.remove_child(child)
			child.free()
	_prompt_label = null
	_receipts_box = null
	_cards_box = null


## Player-facing kicker from the phase's journey segment — never a phase key.
func _kicker_text(phase: String) -> String:
	match JourneyStrip.SEGMENT_BY_PHASE.get(phase, ""):
		"POOL", "ASSIGN", "BACKGROUND":
			return "◤ CHAPTER I — ORIGIN"
		"CAREER":
			return "◤ CHAPTER II — A TRADE"
		"TERMS":
			return "◤ CHAPTER III — THE TERMS"
		"MUSTER":
			return "◤ MUSTERING OUT"
	return "◤ THE CHARGEN SHELL"


func _refresh_subnote(view: Dictionary) -> void:
	if not is_instance_valid(_subnote):
		return
	# Only counts derivable from the view itself — never invented numbers.
	var options: Array = (view as Dictionary).get("options", [])
	var pickable := 0
	for option: Dictionary in options:
		if not bool(option.get("dimmed", false)):
			pickable += 1
	_subnote.text = (
		"%d CHOICE%s OPEN" % [pickable, "" if pickable == 1 else "S"] if pickable > 0 else ""
	)


# --- the generic stage ---------------------------------------------------------


func _build_card(option: Dictionary, index: int) -> Control:
	var option_id := str(option.get("option_id", ""))
	var dimmed := bool(option.get("dimmed", false))
	var card := Kit.card(_theme)
	card.custom_minimum_size = Vector2(176, 0)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 4)
	card.add_child(box)
	box.add_child(Fonts.label(str(option.get("label", option_id)), Fonts.inter(), 14, _theme.ink))
	var odds := _opt_str(option, "odds_line")
	if odds != "":
		box.add_child(Fonts.label(odds, Fonts.data(), 11, _odds_color(odds)))
	for line: Variant in option.get("preview", []):
		var bullet := Fonts.label("· %s" % str(line), Fonts.data(), 10, _theme.muted)
		bullet.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		box.add_child(bullet)
	if dimmed:
		var requirement := _opt_str(option, "requirement")
		if requirement != "":
			var req := Fonts.label(requirement, Fonts.data(), 10, _theme.danger)
			req.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
			box.add_child(req)
		card.modulate.a = 0.45
	var btn := Button.new()
	btn.flat = true
	btn.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	btn.size_flags_vertical = Control.SIZE_EXPAND_FILL
	btn.pressed.connect(_on_option_chosen.bind(option_id))
	# The card IS the visual; the engine's default focus ring would clash
	# with the mockup styling (M5 adds a themed ring with the a11y pass).
	btn.add_theme_stylebox_override("focus", StyleBoxEmpty.new())

	card.add_child(btn)
	_cards.append({"card": card, "button": btn, "option_id": option_id, "dimmed": dimmed})
	if not dimmed and not _reduced_motion():
		# Staggered rise (~40ms per card), mockup 06's entrance. Dimmed cards
		# keep their static 0.45 — they never tween (the guard above).
		card.modulate.a = 0.0
		var tween := card.create_tween()
		tween.tween_interval(0.04 * index)
		tween.tween_property(card, "modulate:a", 1.0, 0.12)
	return card


## Odds color by the trailing percent band (mockup 07's ok/accent/danger).
func _odds_color(odds_line: String) -> Color:
	var percent := _trailing_percent(odds_line)
	if percent < 0:
		return _theme.muted
	if percent >= 70:
		return _theme.ok
	if percent >= 40:
		return _theme.accent
	return _theme.danger


## The trailing percent ("... · 72% FAVORABLE" → 72); -1 when none.
## Parses the digit run that ENDS at the '%' — other numbers don't count.
static func _trailing_percent(text: String) -> int:
	var pct := text.find("%")
	if pct == -1:
		return -1
	var end := pct - 1  # digit just before the %
	var start := end
	while start >= 0 and text[start].is_valid_int():
		start -= 1
	var digits := text.substr(start + 1, end - start)
	return int(digits) if digits.is_valid_int() else -1


## Optional wire strings arrive as explicit nulls — "" them for rendering.
static func _opt_str(option: Dictionary, key: String) -> String:
	var value: Variant = option.get(key, "")
	return str(value) if value is String else ""


func _on_option_chosen(option_id: String) -> void:
	if _director.state != BeatDirector.State.IDLE:
		return
	_director.run(str(_session.get("id", "")), option_id)


func _refresh_cards_enabled() -> void:
	var busy := _director != null and _director.state != BeatDirector.State.IDLE
	for entry: Dictionary in _cards:
		var button: Button = entry["button"]
		button.disabled = busy or bool(entry["dimmed"])


func _on_receipts(events: Array) -> void:
	if not is_instance_valid(_receipts_box):
		return
	for child: Node in _receipts_box.get_children():
		_receipts_box.remove_child(child)
		child.free()
	for event_variant: Variant in events:
		if not (event_variant is Dictionary):
			continue
		var event: Dictionary = event_variant
		var roll_variant: Variant = event.get("roll", {})
		if not (roll_variant is Dictionary) or (roll_variant as Dictionary).is_empty():
			continue
		var readout := RollReadout.new()
		readout.setup(_theme)
		readout.show_compact(roll_variant, str(event.get("description", "")))
		_receipts_box.add_child(readout)
	_refresh_cards_enabled()


func _on_beat_finished(session: Dictionary) -> void:
	# Hidden (drawer open): stash the envelope — never navigate or render
	# off-stage — and let pop-resume apply it. Dropping the envelope would
	# leave _session on the already-consumed phase (every choice then 422s).
	if not visible:
		if not session.is_empty():
			_session = session
		return
	_apply_envelope(session)


# --- director plumbing ---------------------------------------------------------


func _on_block_received(block_type: String, content: String) -> void:
	if is_instance_valid(_prose):
		_prose.feed(block_type, content)


func _on_beat_failed(_error_code: String, message: String) -> void:
	Services.overlay.toast(message, "bad")
	_refresh_cards_enabled()


# --- sheet drawer --------------------------------------------------------------


func press_sheet() -> void:
	var stack := _stack()
	if stack == null:
		return
	stack.push("sheet_drawer", {"session": _session, "client_override": client_override})


func _stack() -> ScreenStack:
	var node := get_parent()
	while node != null:
		if node is ScreenStack:
			return node
		node = node.get_parent()
	return null


# --- view ---------------------------------------------------------------------


func _reduced_motion() -> bool:
	return bool(ClientSettings.get_value("reading/reduced_motion"))


func _build() -> void:
	for child: Node in get_children():
		if child == _director:
			continue  # the director survives rebuilds — its stream state is ours
		remove_child(child)
		child.free()
	# The freed stage nodes must never be referenced again — reset the
	# bookkeeping exactly like _clear_stage does (a pack rebuild frees the
	# old cards; a later _render_view with an empty view early-returns
	# before _clear_stage and would otherwise hold freed buttons).
	_cards = []
	_prompt_label = null
	_receipts_box = null
	_cards_box = null
	var t := _theme
	_backdrop = SceneBackdrop.new()
	_backdrop.pack_theme = t
	_backdrop.scene_id = "night"
	_backdrop.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(_backdrop)

	var root := VBoxContainer.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.add_theme_constant_override("separation", 0)
	add_child(root)

	# Journey strip, top-center (mockup 06).
	var strip_margin := MarginContainer.new()
	strip_margin.add_theme_constant_override("margin_top", 10)
	root.add_child(strip_margin)
	var strip_center := CenterContainer.new()
	strip_margin.add_child(strip_center)
	_strip = JourneyStrip.new()
	_strip.setup(t)
	strip_center.add_child(_strip)

	# Stage: rail (reserved, hidden in C4) | stage | dock.
	var body := HBoxContainer.new()
	body.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_theme_constant_override("separation", 0)
	root.add_child(body)
	var rail_spacer := Control.new()
	rail_spacer.custom_minimum_size = Vector2(_RAIL_WIDTH, 0)
	rail_spacer.mouse_filter = Control.MOUSE_FILTER_IGNORE
	body.add_child(rail_spacer)
	var stage_scroll := ScrollContainer.new()
	stage_scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	stage_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	body.add_child(stage_scroll)
	var stage_center := CenterContainer.new()
	stage_center.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	stage_scroll.add_child(stage_center)
	_stage_holder = VBoxContainer.new()
	_stage_holder.add_theme_constant_override("separation", 14)
	_stage_holder.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	stage_center.add_child(_stage_holder)
	var dock_spacer := Control.new()
	dock_spacer.custom_minimum_size = Vector2(_RAIL_WIDTH, 0)
	dock_spacer.mouse_filter = Control.MOUSE_FILTER_IGNORE
	body.add_child(dock_spacer)

	# Prose strip (the beat narration) under the stage.
	_prose = TypewriterProse.new()
	_prose.setup(t)
	_prose.custom_minimum_size = Vector2(0, 120)
	root.add_child(_prose)

	# Dockbar (mockup 06).
	var dock_margin := MarginContainer.new()
	dock_margin.add_theme_constant_override("margin_left", 18)
	dock_margin.add_theme_constant_override("margin_right", 18)
	dock_margin.add_theme_constant_override("margin_bottom", 16)
	root.add_child(dock_margin)
	_dockbar = HBoxContainer.new()
	_dockbar.add_theme_constant_override("separation", 12)
	dock_margin.add_child(_dockbar)
	_sheet_btn = Kit.ghost_btn("⧉ SHEET", t)
	_sheet_btn.pressed.connect(press_sheet)
	_dockbar.add_child(_sheet_btn)
	var spacer := Control.new()
	spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	spacer.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_dockbar.add_child(spacer)
	_subnote = Fonts.label("", Fonts.micro_tracked(), 12, t.muted)
	_dockbar.add_child(_subnote)
