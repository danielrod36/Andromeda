# gdlint: ignore=max-public-methods
class_name CeremonyScreen
extends BaseScreen
## 04-ceremony.html: the Ceremony — three beats on one night scene.
## 1) FATE SEEDED: a level docket with the session seed, auto-advancing
##    (~1.2s; 0.3s reduced-motion), no button.
## 2) WORLD INTRO: BeatDirector.narrate_only streams the intro into the
##    typewriter; SKIP — SHOW FULL TEXT left, CONTINUE ▸ right, unlocked by
##    narration_finished/all_text_shown. beat_failed toasts the engine
##    message, keeps CONTINUE usable (degraded path) and offers RETRY.
## 3) THE NAME: the card commits set_character_name (80-char cap) and
##    replaces into "chargen" with the returned envelope.
## ESC abandons the fate behind a confirm — the session is deleted.

const _KICKER := "◤ THE SPINWARD REACH — A WORLD INTRODUCTION"
const _FATE_HOLD_SEC := 1.2
const _FATE_HOLD_REDUCED_SEC := 0.3
const _INTRO_WIDTH := 520  # ~58ch at prose size 16
const _INTRO_HEIGHT := 280
const _NAME_CARD_WIDTH := 280

const BEAT_FATE := 1
const BEAT_INTRO := 2
const BEAT_NAME := 3

## Test hook: when set, used instead of Services.client.
var client_override: Node
## Test hook: when set, handed to the BeatDirector instead of its own pump.
var pump_override: Node

var _theme: PackTheme
var _session := {}
var _beat := BEAT_FATE
var _director: BeatDirector
## Guards the fate-hold timer across re-entry, exit and pack rebuilds.
var _epoch := 0
var _intro_unlocked := false
var _intro_failed := false
var _committing := false
var _name_text := ""
var _confirming := false

var _backdrop: SceneBackdrop
var _beat_fate: Control
var _seed_label: Label
var _beat_intro: Control
var _prose_holder: VBoxContainer
var _prose: TypewriterProse
var _intro_bar: Control
var _skip_link: Button
var _retry_btn: Button
var _continue_btn: Button
var _beat_name: Control
var _name_edit: LineEdit
var _take_up_btn: Button


func _ready() -> void:
	_theme = PackThemes.current
	PackThemes.pack_changed.connect(_on_pack_changed)
	_director = BeatDirector.new()
	# Configure BEFORE add_child: BeatDirector._ready spawns its own StreamPump
	# when none is injected, so the pump must be handed over first (the
	# tests' FakeStreamPump arrives via pump_override before this runs).
	_director.configure(_client(), pump_override)
	add_child(_director)
	_director.block_received.connect(_on_block_received)
	_director.narration_finished.connect(_unlock_continue)
	_director.beat_failed.connect(_on_beat_failed)
	_rebuild()


func esc_target() -> String:
	return "title"


func screen_enter(params: Dictionary) -> void:
	_epoch += 1
	var session: Variant = params.get("session")
	_session = session if session is Dictionary else {}
	if _session.is_empty():
		navigate.emit("title", {})
		return
	_name_text = ""
	_intro_unlocked = false
	_intro_failed = false
	_committing = false
	_confirming = false
	_seed_label.text = _seed_docket_text()
	_name_edit.text = ""
	_show_fate_beat()


func screen_exit() -> void:
	_epoch += 1
	# Never leave a narration stream running behind a hidden screen.
	if _director != null and _director.state == BeatDirector.State.NARRATING:
		_director.skip()


## ESC — abandon this fate. The screen owns ESC (instead of letting the
## ScreenStack auto-route on esc_target) because the confirm must gate the
## navigation and the stack's replace() cannot be vetoed from screen_exit —
## the same pattern Chronicles uses for its gated destructive actions. While
## a modal is open it consumes ESC first (the overlay mounts after the stack
## — main.gd), so this handler only ever runs with no modal up.
func _unhandled_input(event: InputEvent) -> void:
	if not visible:
		return
	if not (
		event is InputEventKey and event.pressed and not event.echo and event.keycode == KEY_ESCAPE
	):
		return
	get_viewport().set_input_as_handled()
	_confirm_abandon()


func _client() -> Node:
	return client_override if client_override != null else Services.client


func _on_pack_changed(t: PackTheme) -> void:
	_theme = t
	if is_inside_tree():
		_rebuild()


# --- beats ------------------------------------------------------------------


func _show_fate_beat() -> void:
	_beat = BEAT_FATE
	_apply_beat()
	var epoch := _epoch
	var hold := _FATE_HOLD_REDUCED_SEC if _reduced_motion() else _FATE_HOLD_SEC
	await get_tree().create_timer(hold).timeout
	if epoch == _epoch and _beat == BEAT_FATE and is_inside_tree() and visible:
		_show_intro_beat()


func _show_intro_beat() -> void:
	_beat = BEAT_INTRO
	_intro_unlocked = false
	_intro_failed = false
	_apply_beat()
	_refresh_intro_controls()
	_director.narrate_only(str(_session.get("id", "")), "world_intro")


func _show_name_beat() -> void:
	_beat = BEAT_NAME
	_apply_beat()
	_name_edit.grab_focus()


func _apply_beat() -> void:
	_beat_fate.visible = _beat == BEAT_FATE
	_beat_intro.visible = _beat == BEAT_INTRO
	_beat_name.visible = _beat == BEAT_NAME
	_intro_bar.visible = _beat == BEAT_INTRO


func _reduced_motion() -> bool:
	return bool(ClientSettings.get_value("reading/reduced_motion"))


func _seed_docket_text() -> String:
	if _session.is_empty():
		return ""
	# The docket shows the seed as a plain number (pin 5 — no tilt, no jargon).
	return "FATE SEEDED · %d" % int(_session.get("seed", 0))


# --- world intro wiring -------------------------------------------------------


func _on_block_received(block_type: String, content: String) -> void:
	# Indirected (not wired straight to feed) so pack rebuilds can swap the
	# typewriter without touching the director's connections.
	if _prose != null:
		_prose.feed(block_type, content)


## Unlocks CONTINUE — narration_finished and the typewriter's own
## all_text_shown both land here; the second call is a no-op.
func _unlock_continue() -> void:
	if _beat != BEAT_INTRO:
		return
	_intro_unlocked = true
	_refresh_intro_controls()


func _on_beat_failed(_error_code: String, message: String) -> void:
	if _beat != BEAT_INTRO:
		return
	# Degraded path: the engine message verbatim, CONTINUE stays usable and
	# RETRY re-runs the beat (spec §9).
	Services.overlay.toast(message, "bad")
	_intro_failed = true
	_refresh_intro_controls()


func _refresh_intro_controls() -> void:
	_skip_link.visible = not (_intro_unlocked or _intro_failed)
	_retry_btn.visible = _intro_failed
	_continue_btn.disabled = not (_intro_unlocked or _intro_failed)


func press_skip() -> void:
	if _beat != BEAT_INTRO or not _skip_link.visible:
		return
	# The director closes the pump and synthesizes `done` — the typewriter
	# completes on it and all_text_shown unlocks CONTINUE.
	_director.skip()


func press_retry() -> void:
	if not _retry_btn.visible:
		return
	_intro_failed = false
	_intro_unlocked = false
	_refresh_intro_controls()
	_rebuild_prose()  # drop the failed beat's partial text before the re-tell
	_director.narrate_only(str(_session.get("id", "")), "world_intro")


func press_continue() -> void:
	if _continue_btn.disabled:
		return
	_show_name_beat()


# --- the name -----------------------------------------------------------------


func _on_name_changed(text: String) -> void:
	_name_text = text
	_take_up_btn.disabled = text.strip_edges() == ""


## Enter commits like the button (mock UX: TAKE UP THE TALE).
func _on_name_submitted(_text: String) -> void:
	press_take_up()


func press_take_up() -> void:
	if _committing or _take_up_btn.disabled:
		return
	var char_name := _name_edit.text.strip_edges()
	_committing = true
	_take_up_btn.disabled = true
	var res: EngineResult = await (_client().set_character_name(
		str(_session.get("id", "")), char_name
	))
	if not res.ok:
		Services.overlay.toast_error(res)
		_committing = false
		_on_name_changed(_name_text)
		return
	var session: Dictionary = res.data["session"]
	SessionStore.set_current(session)
	_reset_committing.call_deferred()  # one-shot: a same-frame re-press stays blocked
	navigate.emit("chargen", {"session": session})


func _reset_committing() -> void:
	_committing = false


# --- ESC: abandon this fate ---------------------------------------------------


func _confirm_abandon() -> void:
	if _confirming:
		return  # a second ESC while the confirm is up must not stack another
	_confirming = true
	var confirmed: bool = await Services.overlay.confirm(
		"ABANDON THIS FATE?", "The chronicle is deleted; the seed is lost.", "ABANDON", "STAY"
	)
	if not confirmed:
		_confirming = false
		return
	var session_id := str(_session.get("id", ""))
	if session_id != "":
		var res: EngineResult = await _client().delete_session(session_id)
		if not res.ok:
			# The abandon failed — keep the fate and say why.
			Services.overlay.toast_error(res)
			_confirming = false
			return
	_confirming = false
	navigate.emit("title", {})


# --- view -------------------------------------------------------------------


func _rebuild() -> void:
	for child: Node in get_children():
		if child == _director:
			continue  # the director survives rebuilds — its stream state is ours
		remove_child(child)
		child.free()
	_build()
	_apply_beat()
	_refresh_intro_controls()


func _build() -> void:
	var t := _theme
	_backdrop = SceneBackdrop.new()
	_backdrop.pack_theme = t
	_backdrop.scene_id = "night"
	_backdrop.kicker_text = _KICKER
	_backdrop.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(_backdrop)

	var root := VBoxContainer.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.add_theme_constant_override("separation", 0)
	add_child(root)

	var stage := Control.new()
	stage.size_flags_vertical = Control.SIZE_EXPAND_FILL
	root.add_child(stage)

	_beat_fate = _build_fate_beat(stage, t)
	_beat_intro = _build_intro_beat(stage, t)
	_beat_name = _build_name_beat(stage, t)
	_intro_bar = _build_intro_bar(root, t)

	_seed_label.text = _seed_docket_text()
	_name_edit.text = _name_text


func _build_fate_beat(stage: Control, t: PackTheme) -> Control:
	var beat := VBoxContainer.new()
	beat.set_anchors_preset(Control.PRESET_FULL_RECT)
	beat.alignment = BoxContainer.ALIGNMENT_CENTER
	beat.add_theme_constant_override("separation", 16)
	stage.add_child(beat)

	var docket := Kit.card(t)
	docket.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	var sb := docket.get_theme_stylebox("panel").duplicate() as StyleBoxFlat
	sb.content_margin_left = 18
	sb.content_margin_top = 10
	sb.content_margin_right = 18
	sb.content_margin_bottom = 10
	docket.add_theme_stylebox_override("panel", sb)
	beat.add_child(docket)
	_seed_label = Fonts.label("", Fonts.data(), 13, t.ink)
	docket.add_child(_seed_label)

	var line := Fonts.label(
		(
			"The dice are already cast. "
			+ "Every fortune in this chronicle was written at this number."
		),
		Fonts.prose(),
		14,
		t.muted
	)
	line.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	line.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	line.custom_minimum_size = Vector2(264, 0)  # ~34ch at 14px
	line.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	beat.add_child(line)
	return beat


func _build_intro_beat(stage: Control, t: PackTheme) -> Control:
	var beat := VBoxContainer.new()
	beat.set_anchors_preset(Control.PRESET_FULL_RECT)
	beat.add_theme_constant_override("separation", 0)
	stage.add_child(beat)
	var top := Control.new()
	top.size_flags_vertical = Control.SIZE_EXPAND_FILL
	beat.add_child(top)
	var holder := CenterContainer.new()
	beat.add_child(holder)
	_prose_holder = VBoxContainer.new()
	_prose_holder.custom_minimum_size = Vector2(_INTRO_WIDTH, _INTRO_HEIGHT)
	holder.add_child(_prose_holder)
	_prose = _build_prose(_prose_holder, t)
	var bottom := Control.new()
	bottom.size_flags_vertical = Control.SIZE_EXPAND_FILL
	beat.add_child(bottom)
	return beat


func _build_prose(parent: Control, t: PackTheme) -> TypewriterProse:
	var prose := TypewriterProse.new()
	prose.size_flags_vertical = Control.SIZE_EXPAND_FILL
	prose.setup(t)
	# Mock 04 reads the intro larger than the shell spine (19px-equivalent).
	prose._rich.add_theme_font_size_override("font_size", 16)
	prose._active.add_theme_font_size_override("font_size", 16)
	# Legibility over the scene (mock 04's text-shadow).
	for node: Control in [prose._rich, prose._active]:
		node.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0.6))
		node.add_theme_constant_override("shadow_offset_x", 0)
		node.add_theme_constant_override("shadow_offset_y", 2)
	parent.add_child(prose)
	prose.all_text_shown.connect(_unlock_continue)
	return prose


func _rebuild_prose() -> void:
	if _prose != null:
		_prose_holder.remove_child(_prose)
		_prose.free()
	_prose = _build_prose(_prose_holder, _theme)


func _build_name_beat(stage: Control, t: PackTheme) -> Control:
	var beat := VBoxContainer.new()
	beat.set_anchors_preset(Control.PRESET_FULL_RECT)
	beat.alignment = BoxContainer.ALIGNMENT_CENTER
	beat.add_theme_constant_override("separation", 16)
	stage.add_child(beat)

	var title := Fonts.label("Every fortune starts with a name.", Fonts.title(), 21, t.ink)
	title.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	title.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0.6))
	title.add_theme_constant_override("shadow_offset_x", 0)
	title.add_theme_constant_override("shadow_offset_y", 2)
	beat.add_child(title)

	var card := Kit.card(t)
	card.custom_minimum_size = Vector2(_NAME_CARD_WIDTH, 0)
	card.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	var sb := card.get_theme_stylebox("panel").duplicate() as StyleBoxFlat
	sb.content_margin_left = 14
	sb.content_margin_top = 11
	sb.content_margin_right = 14
	sb.content_margin_bottom = 11
	card.add_theme_stylebox_override("panel", sb)
	beat.add_child(card)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 5)
	card.add_child(box)
	box.add_child(Fonts.label("THE NAME THE WORLD REMEMBERS", Fonts.micro_tracked(), 10, t.muted))
	_name_edit = LineEdit.new()
	_name_edit.max_length = 80
	_name_edit.add_theme_font_override("font", Fonts.data())
	_name_edit.add_theme_font_size_override("font_size", 17)
	_name_edit.add_theme_color_override("font_color", t.ink)
	_name_edit.add_theme_color_override("caret_color", t.accent)
	_name_edit.add_theme_stylebox_override("normal", StyleBoxEmpty.new())
	_name_edit.add_theme_stylebox_override("focus", StyleBoxEmpty.new())
	_name_edit.flat = true
	_name_edit.text_changed.connect(_on_name_changed)
	_name_edit.text_submitted.connect(_on_name_submitted)

	_take_up_btn = Kit.btn("TAKE UP THE TALE ▸", t)
	_take_up_btn.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	_take_up_btn.disabled = true
	_take_up_btn.pressed.connect(press_take_up)
	beat.add_child(_take_up_btn)
	return beat


func _build_intro_bar(root: Control, t: PackTheme) -> Control:
	var bar_margin := MarginContainer.new()
	bar_margin.add_theme_constant_override("margin_left", 26)
	bar_margin.add_theme_constant_override("margin_right", 26)
	bar_margin.add_theme_constant_override("margin_bottom", 20)
	root.add_child(bar_margin)
	var bar := HBoxContainer.new()
	bar.add_theme_constant_override("separation", 12)
	bar_margin.add_child(bar)
	_skip_link = Kit.microlink("SKIP — SHOW FULL TEXT", t)
	_skip_link.pressed.connect(press_skip)
	bar.add_child(_skip_link)
	var spacer := Control.new()
	spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	bar.add_child(spacer)
	_retry_btn = Kit.ghost_btn("RETRY", t)
	_retry_btn.visible = false
	_retry_btn.pressed.connect(press_retry)
	bar.add_child(_retry_btn)
	_continue_btn = Kit.btn("CONTINUE ▸", t)
	_continue_btn.disabled = true
	_continue_btn.pressed.connect(press_continue)
	bar.add_child(_continue_btn)
	return bar_margin
