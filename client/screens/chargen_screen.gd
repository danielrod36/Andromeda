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
## Bumped by every applied envelope — a reconnect resolving after a newer
## application is stale and discarded.
var _session_gen := 0
var _backdrop: SceneBackdrop
var _strip: JourneyStrip
var _stage_holder: Control
var _prose: TypewriterProse
var _dockbar: HBoxContainer
var _sheet_btn: Button
var _subnote: Label
var _freetext_slot: HBoxContainer
var _freetext_edit: LineEdit
var _freetext_send: Button
var _interp_card: PanelContainer
var _freetext_busy := false
var _prompt_label: Label
var _receipts_box: VBoxContainer
var _cards_box: GridContainer
var _cards: Array = []
var _career_filter := ""
var _career_selected := ""
var _career_view := {}
var _career_hero: PanelContainer


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
## A fetch that resolves after a NEWER envelope applied locally (a finished
## beat, a pack re-apply) is discarded: its snapshot is older than what the
## player already sees.
func _reconnect() -> void:
	var epoch := _epoch
	var gen := _session_gen
	var res: EngineResult = await _client().get_session(str(_session.get("id", "")))
	if epoch != _epoch or gen != _session_gen or not is_inside_tree() or not visible:
		return
	if not res.ok:
		Services.overlay.toast_error(res)
		return
	_apply_envelope(res.data.get("session", {}))


# --- envelope application ------------------------------------------------------


func _apply_envelope(session: Dictionary) -> void:
	if session.is_empty():
		return
	_session_gen += 1
	_session = session
	if is_instance_valid(_strip):
		_strip.set_phase(str(session.get("phase", "")))
	if is_instance_valid(_backdrop):
		_backdrop.kicker_text = _kicker_text(str(session.get("phase", "")))
	if str(session.get("phase", "")) == "complete":
		# Only a VISIBLE screen navigates. Hidden callers (pack_changed
		# re-applying a lingering complete stash) must never fire navigate
		# off-stage — the stash waits for pop-resume.
		if visible:
			navigate.emit("reveal", {"session": session})
		return
	_render_view(session.get("view", {}))


## `view` arrives as an explicit null for complete sessions — soft-typed so
## the guard below can handle it instead of raising at the call boundary.
func _render_view(view: Variant) -> void:
	if not (view is Dictionary) or (view as Dictionary).is_empty():
		return
	_clear_stage()
	var v: Dictionary = view
	var phase := str(v.get("phase", ""))
	if phase == "assign_characteristics":
		_render_assign_stage(v)
	elif phase == "choose_career":
		_career_filter = ""
		_career_selected = ""
		_render_career_deck(v)
	else:
		_render_generic_stage(v)
	_refresh_freetext_slot(v)


## The freetext slot (mockup 07a's dockbar): offered only when the phase
## allows it; a translation renders as an interpretation card.
func _refresh_freetext_slot(v: Dictionary) -> void:
	if is_instance_valid(_freetext_slot):
		_freetext_slot.visible = bool(v.get("allows_freetext", false))
		var hint := _opt_str_dict(v, "freetext_hint")
		if is_instance_valid(_freetext_edit):
			_freetext_edit.placeholder_text = hint if hint != "" else "In your own words…"
			_freetext_edit.editable = not _freetext_busy
	if is_instance_valid(_interp_card):
		_interp_card.queue_free()
		_interp_card = null


static func _opt_str_dict(source: Dictionary, key: String) -> String:
	var value: Variant = source.get(key, "")
	return str(value) if value is String else ""


## The career deck (mockup 07a): filter chips over the card grid, a hero
## rail on selection (big odds + full description + ATTEMPT), selection
## dims the rest to 45%.
func _render_career_deck(v: Dictionary) -> void:
	_career_view = v
	var prompt := str(v.get("prompt", ""))
	if prompt != "":
		_prompt_label = Fonts.label(prompt, Fonts.prose(), 16, _theme.ink)
		_prompt_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		_prompt_label.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
		_stage_holder.add_child(_prompt_label)
	var filters := HBoxContainer.new()
	filters.add_theme_constant_override("separation", 8)
	filters.alignment = BoxContainer.ALIGNMENT_CENTER
	_stage_holder.add_child(filters)
	var chars := _career_filter_chars(v)
	var chip_row := PackedStringArray(["ALL"])
	chip_row.append_array(chars)
	for chip_label: String in chip_row:
		var chip := Button.new()
		chip.text = chip_label
		chip.toggle_mode = true
		chip.button_pressed = (
			chip_label == _career_filter or (chip_label == "ALL" and _career_filter == "")
		)
		chip.add_theme_font_override("font", Fonts.micro_tracked())
		chip.add_theme_font_size_override("font_size", 11)
		chip.add_theme_stylebox_override("focus", StyleBoxEmpty.new())
		var wanted := "" if chip_label == "ALL" else chip_label
		chip.pressed.connect(_on_career_filter.bind(wanted))
		filters.add_child(chip)
	var body := HBoxContainer.new()
	body.add_theme_constant_override("separation", 14)
	body.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	_stage_holder.add_child(body)
	_cards_box = GridContainer.new()
	_cards_box.columns = 3
	_cards_box.add_theme_constant_override("h_separation", 10)
	_cards_box.add_theme_constant_override("v_separation", 10)
	body.add_child(_cards_box)
	_career_hero = PanelContainer.new()
	_career_hero.custom_minimum_size = Vector2(300, 0)
	_career_hero.visible = false
	body.add_child(_career_hero)
	var index := 0
	for option_variant: Variant in v.get("options", []):
		if not (option_variant is Dictionary):
			continue
		var option: Dictionary = option_variant
		if _career_filter != "" and not _career_matches(option, _career_filter):
			continue
		_cards_box.add_child(_build_card(option, index, _on_career_card_pressed))
		index += 1
	if _career_selected != "":
		_open_career_hero(_career_selected)
	_refresh_cards_enabled()
	_refresh_subnote(v)


## Characteristics offered by the deck — parsed from the qualify previews
## ("2D6+1 vs INT 6+ to qualify"); never hardcoded per pack.
func _career_filter_chars(v: Dictionary) -> Array:
	var found := {}
	for option_variant: Variant in v.get("options", []):
		if not (option_variant is Dictionary):
			continue
		for preview_variant: Variant in (option_variant as Dictionary).get("preview", []):
			var preview := str(preview_variant)
			for char_name: String in ["STR", "DEX", "END", "INT", "EDU", "SOC"]:
				if preview.contains(" vs %s " % char_name):
					found[char_name] = true
	return found.keys()


func _career_matches(option: Dictionary, char_name: String) -> bool:
	for preview_variant: Variant in option.get("preview", []):
		if str(preview_variant).contains(" vs %s " % char_name):
			return true
	return false


func _on_career_filter(wanted: String) -> void:
	_career_filter = wanted
	_career_selected = ""
	_render_career_deck(_career_view)


## Card presses on the deck SELECT (hero rail) — the funnel fires from the
## hero's ATTEMPT button, per mockup 07a.
func _on_career_card_pressed(option_id: String) -> void:
	if _director.state != BeatDirector.State.IDLE:
		return
	_career_selected = option_id
	_open_career_hero(option_id)
	for entry: Dictionary in _cards:
		var card: Control = entry["card"]
		card.modulate.a = 0.45 if str(entry["option_id"]) != option_id else 1.0


func _open_career_hero(option_id: String) -> void:
	if not is_instance_valid(_career_hero):
		return
	var option: Variant = _find_option_in(_career_view, option_id)
	if option == null:
		_career_hero.visible = false
		return
	for child: Node in _career_hero.get_children():
		_career_hero.remove_child(child)
		child.free()
	var t := _theme
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 8)
	_career_hero.add_child(box)
	box.add_child(Fonts.label(str(option.get("label", "")), Fonts.inter(), 16, t.ink))
	var odds := _opt_str(option, "odds_line")
	if odds != "":
		var percent := _trailing_percent(odds)
		if percent >= 0:
			var big := Fonts.label("%d%%" % percent, Fonts.title(), 30, _odds_color(odds))
			box.add_child(big)
		box.add_child(Fonts.label(odds, Fonts.data(), 10, t.muted))
	var description := _opt_str(option, "description")
	if description != "":
		var prose := Fonts.label(description, Fonts.prose(), 12, t.ink)
		prose.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		prose.custom_minimum_size = Vector2(272, 0)
		box.add_child(prose)
	for preview_variant: Variant in option.get("preview", []):
		var bullet := Fonts.label("· %s" % str(preview_variant), Fonts.data(), 10, t.muted)
		bullet.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		bullet.custom_minimum_size = Vector2(272, 0)
		box.add_child(bullet)
	var attempt := Kit.btn("ATTEMPT QUALIFICATION ▸", t)
	attempt.pressed.connect(_on_option_chosen.bind(option_id))
	box.add_child(attempt)
	_career_hero.visible = true


func _find_option_in(v: Dictionary, wanted: String) -> Variant:
	for option_variant: Variant in v.get("options", []):
		if (
			option_variant is Dictionary
			and str((option_variant as Dictionary).get("option_id", "")) == wanted
		):
			return option_variant
	return null


func _on_freetext_send() -> void:
	if _freetext_busy or _director.state != BeatDirector.State.IDLE:
		return
	var text := _freetext_edit.text.strip_edges() if is_instance_valid(_freetext_edit) else ""
	if text == "":
		return
	_freetext_busy = true
	if is_instance_valid(_freetext_edit):
		_freetext_edit.editable = false
	var res: EngineResult = await _client().freetext(str(_session.get("id", "")), text)
	_freetext_busy = false
	if is_instance_valid(_freetext_edit):
		_freetext_edit.editable = true
		_freetext_edit.text = ""
	if not res.ok:
		# 422 translator_unavailable (or any error) — engine message verbatim.
		Services.overlay.toast_error(res)
		return
	_show_interpretation(res.data.get("record", {}))


## The interpretation card: your words → the option the referee read them
## as. APPLY commits it through the funnel; DISMISS drops the proposal.
func _show_interpretation(record: Dictionary) -> void:
	if is_instance_valid(_interp_card):
		_interp_card.queue_free()
	var selected: Variant = record.get("selected_option_id", null)
	var option: Variant = _find_view_option(str(selected) if selected != null else "")
	var card := Kit.card(_theme)
	card.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 4)
	card.add_child(box)
	box.add_child(
		Fonts.label("YOUR WORDS, READ BY THE REFEREE", Fonts.micro_tracked(), 10, _theme.accent)
	)
	var body := str(record.get("rationale", ""))
	var target_label := str(option.get("label", selected)) if option != null else str(selected)
	var line := Fonts.label(
		"“%s” → %s" % [str(record.get("text", "")), target_label.to_upper()],
		Fonts.prose(),
		12,
		_theme.ink
	)
	line.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	line.custom_minimum_size = Vector2(420, 0)
	box.add_child(line)
	if body != "":
		var why := Fonts.label(body, Fonts.prose(), 11, _theme.muted)
		why.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		why.custom_minimum_size = Vector2(420, 0)
		box.add_child(why)
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 10)
	box.add_child(row)
	if option != null:
		var apply_btn := Kit.btn("PROCEED ▸", _theme)
		apply_btn.pressed.connect(
			func() -> void: _on_option_chosen(str(option.get("option_id", "")))
		)
		row.add_child(apply_btn)
	var dismiss := Kit.ghost_btn("DISMISS", _theme)
	dismiss.pressed.connect(
		func() -> void:
			if is_instance_valid(card):
				card.queue_free()
	)
	row.add_child(dismiss)
	if is_instance_valid(_stage_holder):
		_stage_holder.add_child(card)
	_interp_card = card


## Find a current option by id (the interpretation card's APPLY target).
func _find_view_option(option_id: String) -> Variant:
	if _session.is_empty():
		return null
	var view: Variant = _session.get("view", null)
	if not (view is Dictionary):
		return null
	for option_variant: Variant in (view as Dictionary).get("options", []):
		if option_variant is Dictionary:
			var option: Dictionary = option_variant
			if str(option.get("option_id", "")) == option_id:
				return option
	return null


## The bespoke pool-assignment stage (mockup 06a): chips × stat matrix.
func _render_assign_stage(v: Dictionary) -> void:
	var stage := AssignStage.new()
	stage.setup(_theme)
	stage.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	stage.choose_option.connect(_on_option_chosen)
	_stage_holder.add_child(stage)
	stage.build_from_view(v, _on_option_chosen)


## The generic card stage — every other phase (mockup 06's choice cards).
func _render_generic_stage(v: Dictionary) -> void:
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
	_refresh_subnote(v)


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


func _build_card(
	option: Dictionary, index: int, on_press: Callable = Callable(_on_option_chosen)
) -> Control:
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
	btn.pressed.connect(on_press.bind(option_id))
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
	_freetext_slot = HBoxContainer.new()
	_freetext_slot.add_theme_constant_override("separation", 8)
	_freetext_slot.visible = false
	_dockbar.add_child(_freetext_slot)
	var pen := Fonts.label("✎", Fonts.micro_tracked(), 12, t.accent)
	_freetext_slot.add_child(pen)
	_freetext_edit = LineEdit.new()
	_freetext_edit.custom_minimum_size = Vector2(260, 0)
	_freetext_edit.add_theme_font_override("font", Fonts.prose())
	_freetext_edit.add_theme_font_size_override("font_size", 12)
	_freetext_edit.add_theme_color_override("font_color", t.ink)
	_freetext_edit.add_theme_color_override("caret_color", t.accent)
	_freetext_edit.placeholder_text = "In your own words…"
	_freetext_slot.add_child(_freetext_edit)
	_freetext_send = Kit.btn("SEND ▸", t)
	_freetext_send.pressed.connect(_on_freetext_send)
	_freetext_slot.add_child(_freetext_send)
