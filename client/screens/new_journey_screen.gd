# gdlint: ignore=max-public-methods
class_name NewJourneyScreen
extends BaseScreen
## 03-new-journey.html: the launch manifest. Pack/profile/death-mode cards
## (selected = accent border + ▸ LOCKED IN), rerollable seed, immutability
## notice, narrator status. BEGIN → POST /v1/sessions {kind:"chargen"} → the
## Ceremony (M3).

const _PROFILE_COPY := {
	"narrative":
	[
		(
			"Three tiers: strong hit / weak hit with complication / miss with consequence. "
			+ "Story-forward; the oracle tables talk back. "
			+ "Lifepath always uses classic CE mechanics either way."
		),
		"10+ STRONG · 7–9 WEAK · ≤6 MISS",
	],
	"classic":
	[
		"Binary 2D6+DM vs 8 with Effect margins. SRD-faithful, clean, unforgiving in the way dice are.",
		"2D6+DM ≥ 8",
	],
}
const _DEATH_COPY := {
	"ironman":
	["Death is permanent — even in chargen. A life, told once.", "PERMADEATH · MEMORIAL"],
	"checkpoint":
	[
		(
			"Death rewinds to the start of the scene. "
			+ "The abandoned branch stays in the audit log."
		),
		"SCENE REWIND",
	],
	"narrative":
	[
		"Defeat leaves lasting scars — injuries, debt, capture — and play continues.",
		"SCARS, NOT ENDINGS",
	],
}
const _PROFILE_TITLES := {"narrative": "Narrative", "classic": "Classic"}
const _DEATH_TITLES := {"ironman": "Ironman", "checkpoint": "Checkpoint", "narrative": "Narrative"}

## Test hook: when set, used instead of Services.client.
var client_override: Node

var selected_pack := "scifi"
var selected_profile := "narrative"
var selected_death := "narrative"

var _theme: PackTheme
var _packs: Array = []
var _ruleset: Dictionary = {}
var _status: Dictionary = {}
var _max_retries := 3
var _name_text := ""
var _seed_value := 0
var _submitting := false

var _name_edit: LineEdit
var _seed_label: Label
var _cards_box: VBoxContainer
var _pack_cards := {}
var _profile_cards := {}
var _death_cards := {}
var _narrator_line: Label
var _cap_line: Label
var _strip: StatusStrip


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
		_render_cards()


func _load_data() -> void:
	var packs_res: EngineResult = await _client().list_packs()
	if packs_res.ok:
		_packs = packs_res.data.get("packs", [])
	else:
		Services.overlay.toast_error(packs_res)
	var rules_res: EngineResult = await _client().list_rulesets()
	if not rules_res.ok:
		Services.overlay.toast_error(rules_res)
	elif not Array(rules_res.data.get("rulesets", [])).is_empty():
		_ruleset = rules_res.data["rulesets"][0]
	var status_res: EngineResult = await _client().llm_status()
	if status_res.ok:
		_status = status_res.data
	else:
		Services.overlay.toast_error(status_res)
	var settings_res: EngineResult = await _client().get_settings()
	if settings_res.ok:
		_max_retries = int(settings_res.data.get("max_retries", 3))
	else:
		Services.overlay.toast_error(settings_res)
	_render_cards()


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
	root.add_child(Kit.screen_header("NEW JOURNEY — LAUNCH MANIFEST", t, "ESC — BACK"))

	var pad := MarginContainer.new()
	pad.size_flags_vertical = Control.SIZE_EXPAND_FILL
	pad.add_theme_constant_override("margin_left", 18)
	pad.add_theme_constant_override("margin_top", 16)
	pad.add_theme_constant_override("margin_right", 18)
	pad.add_theme_constant_override("margin_bottom", 18)
	root.add_child(pad)
	var scroll := ScrollContainer.new()
	pad.add_child(scroll)
	_cards_box = VBoxContainer.new()
	_cards_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_cards_box.add_theme_constant_override("separation", 16)
	scroll.add_child(_cards_box)

	_strip = StatusStrip.new()
	_strip.pack_theme = t
	root.add_child(_strip)


func _section_label(text: String) -> Label:
	return Fonts.label("%s %s" % [_theme.motif, text], Fonts.data(), 10, _theme.muted)


func _render_cards() -> void:
	for child: Node in _cards_box.get_children():
		_cards_box.remove_child(child)
		child.free()
	_pack_cards = {}
	_profile_cards = {}
	_death_cards = {}
	var t := _theme

	# 01 · CHRONICLE
	_cards_box.add_child(_section_label("01 · CHRONICLE"))
	var id_row := HBoxContainer.new()
	id_row.add_theme_constant_override("separation", 12)
	_cards_box.add_child(id_row)
	var name_card := Kit.card(t)
	name_card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	id_row.add_child(name_card)
	var name_box := VBoxContainer.new()
	name_card.add_child(name_box)
	name_box.add_child(Fonts.label("SAVE NAME", Fonts.micro_tracked(), 11, t.muted))
	_name_edit = LineEdit.new()
	_name_edit.placeholder_text = "name the chronicle"
	_name_edit.text = _name_text
	_name_edit.text_changed.connect(func(new_text: String) -> void: _name_text = new_text)
	_name_edit.add_theme_font_override("font", Fonts.inter())
	_name_edit.add_theme_font_size_override("font_size", 17)
	_name_edit.add_theme_color_override("font_color", t.ink)
	_name_edit.add_theme_color_override("caret_color", t.accent)
	_name_edit.add_theme_stylebox_override("normal", StyleBoxEmpty.new())
	_name_edit.add_theme_stylebox_override("focus", StyleBoxEmpty.new())
	_name_edit.flat = true
	name_box.add_child(_name_edit)
	var seed_card := Kit.card(t)
	seed_card.custom_minimum_size = Vector2(250, 0)
	id_row.add_child(seed_card)
	var seed_row := HBoxContainer.new()
	seed_card.add_child(seed_row)
	var seed_box := VBoxContainer.new()
	seed_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	seed_row.add_child(seed_box)
	seed_box.add_child(Fonts.label("SEED", Fonts.micro_tracked(), 11, t.muted))
	if _seed_value == 0:
		_seed_value = randi_range(100000, 999999)
	_seed_label = Fonts.label(str(_seed_value), Fonts.data(), 15, t.ink)
	seed_box.add_child(_seed_label)
	var reroll := Kit.btn("⟳ REROLL", t)
	reroll.pressed.connect(press_reroll)
	seed_row.add_child(reroll)

	# 02 · THEME PACK
	_cards_box.add_child(_section_label("02 · THEME PACK — THE WORLD"))
	var pack_grid := HBoxContainer.new()
	pack_grid.add_theme_constant_override("separation", 12)
	_cards_box.add_child(pack_grid)
	for pack: Dictionary in _packs:
		var card := _choice_card(
			str(pack["id"]),
			"%s %s" % [str(pack.get("theme", {}).get("motif", "◆")), str(pack["name"])],
			str(pack.get("description", "")),
			_stats_line(pack),
			PackThemes.get_theme(str(pack["id"])),
			selected_pack == str(pack["id"])
		)
		card.get_meta("button").pressed.connect(select_card.bind("pack", str(pack["id"])))
		_pack_cards[str(pack["id"])] = card
		pack_grid.add_child(card)

	# 03 · RESOLUTION PROFILE
	_cards_box.add_child(_section_label("03 · RESOLUTION PROFILE — HOW CHECKS READ"))
	var profile_grid := HBoxContainer.new()
	profile_grid.add_theme_constant_override("separation", 12)
	_cards_box.add_child(profile_grid)
	for id: String in ["narrative", "classic"]:
		if not Array(_ruleset.get("resolution_profiles", [])).has(id):
			continue
		var card := _choice_card(
			id,
			"%s %s" % [t.motif, _PROFILE_TITLES[id]],
			_PROFILE_COPY[id][0],
			_PROFILE_COPY[id][1],
			t,
			selected_profile == id
		)
		card.get_meta("button").pressed.connect(select_card.bind("profile", id))
		_profile_cards[id] = card
		profile_grid.add_child(card)

	# 04 · DEATH MODE
	_cards_box.add_child(_section_label("04 · DEATH MODE — WHAT DEFEAT MEANS"))
	var death_grid := HBoxContainer.new()
	death_grid.add_theme_constant_override("separation", 12)
	_cards_box.add_child(death_grid)
	for id: String in ["ironman", "checkpoint", "narrative"]:
		if not Array(_ruleset.get("death_modes", [])).has(id):
			continue
		var card := _choice_card(
			id,
			"%s %s" % [t.motif, _DEATH_TITLES[id]],
			_DEATH_COPY[id][0],
			_DEATH_COPY[id][1],
			t,
			selected_death == id
		)
		card.get_meta("button").pressed.connect(select_card.bind("death", id))
		_death_cards[id] = card
		death_grid.add_child(card)

	# Immutability notice (verbatim mock copy)
	var notice_wrap := PanelContainer.new()
	var notice_sb := StyleBoxFlat.new()
	notice_sb.bg_color = Color(0, 0, 0, 0)
	notice_sb.border_width_left = 3
	notice_sb.border_color = t.accent
	notice_sb.content_margin_left = 12
	notice_sb.content_margin_top = 6
	notice_sb.content_margin_bottom = 6
	notice_wrap.add_theme_stylebox_override("panel", notice_sb)
	_cards_box.add_child(notice_wrap)
	var notice := RichTextLabel.new()
	notice.bbcode_enabled = true
	notice.fit_content = true
	notice.scroll_active = false
	notice.add_theme_font_override("normal_font", Fonts.prose())
	notice.add_theme_font_override("bold_font", Fonts.prose_bold())
	notice.add_theme_font_size_override("normal_font_size", 12)
	notice.add_theme_font_size_override("bold_font_size", 12)
	notice.add_theme_color_override("default_color", t.muted)
	notice.text = (
		"[b]Permanent once launched:[/b] pack, profile, and death mode are baked into "
		+ "the save so replays stay honest. Name and seed are just the chronicle's "
		+ "label and starting dice."
	)
	notice_wrap.add_child(notice)

	# BEGIN row
	var begin_row := HBoxContainer.new()
	begin_row.add_theme_constant_override("separation", 16)
	_cards_box.add_child(begin_row)
	var begin := Kit.btn("BEGIN — ROLL CHARACTERISTICS ▸", t)
	begin.add_theme_font_size_override("font_size", 14)
	begin.custom_minimum_size = Vector2(0, 42)
	begin.pressed.connect(press_begin)
	begin_row.add_child(begin)
	var narrator_box := VBoxContainer.new()
	begin_row.add_child(narrator_box)
	_narrator_line = Fonts.label("", Fonts.data(), 10, t.muted)
	narrator_box.add_child(_narrator_line)
	_cap_line = Fonts.label("", Fonts.data(), 10, t.muted)
	narrator_box.add_child(_cap_line)
	_update_narrator_lines()

	_strip.refresh(_status)
	_strip.set_right_plain("MANIFEST 04/04")


func _stats_line(pack: Dictionary) -> String:
	var line := (
		"%d CAREERS · %d SKILLS"
		% [int(pack.get("career_count", 0)), int(pack.get("skill_count", 0))]
	)
	if bool(pack.get("has_cascades", false)):
		line += " · CASCADES ✓"
	return line


## A manifest card (mock 03): title, prose desc, stats line; selected shows
## the accent border + ▸ LOCKED IN stamp. The clickable overlay is in
## meta "button".
func _choice_card(
	id: String, title_text: String, desc: String, stats: String, t: PackTheme, selected: bool
) -> PanelContainer:
	var card := Kit.card(t)
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.set_meta("card_id", id)
	if selected:
		var sb: StyleBoxFlat = card.get_theme_stylebox("panel")
		var selected_sb := sb.duplicate()
		selected_sb.border_color = t.accent
		card.add_theme_stylebox_override("panel", selected_sb)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 5)
	card.add_child(box)
	var title_row := HBoxContainer.new()
	box.add_child(title_row)
	var title := Fonts.label(title_text, Fonts.inter(), 15, t.ink)
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	title_row.add_child(title)
	var stamp := Fonts.label("▸ LOCKED IN" if selected else "", Fonts.micro_tracked(), 10, t.accent)
	title_row.add_child(stamp)
	var body := Fonts.label(desc, Fonts.prose(), 12, t.muted)
	body.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	box.add_child(body)
	box.add_child(Fonts.label(stats, Fonts.data(), 9, t.muted))
	var click := Button.new()
	click.flat = true
	click.set_anchors_preset(Control.PRESET_FULL_RECT)
	click.add_theme_stylebox_override("focus", StyleBoxEmpty.new())
	card.add_child(click)
	card.set_meta("button", click)
	return card


func _update_narrator_lines() -> void:
	if bool(_status.get("configured", false)):
		_narrator_line.text = (
			"NARRATOR: %s ● · TEMPLATES IF IT EVER FAILS" % str(_status.get("model", "")).to_upper()
		)
	else:
		_narrator_line.text = "NARRATOR: UNCONFIGURED — TEMPLATES ACTIVE"
	_cap_line.text = "SPEND CAP: %d CALLS PER BEAT" % (1 + _max_retries)


func press_reroll() -> void:
	_seed_value = randi_range(100000, 999999)
	_seed_label.text = str(_seed_value)


func select_card(kind: String, id: String) -> void:
	match kind:
		"pack":
			selected_pack = id
		"profile":
			selected_profile = id
		"death":
			selected_death = id
	# The rebuild destroys the name LineEdit — carry focus and caret across so
	# a card click mid-edit doesn't drop input/IME state (text survives via
	# _name_text).
	var had_focus := _name_edit.has_focus()
	var caret := _name_edit.caret_column
	_render_cards()
	if had_focus:
		_name_edit.grab_focus()
		_name_edit.caret_column = caret


func press_begin() -> void:
	if _submitting:  # a second press during the await chain must not double-run
		return
	_submitting = true
	var save_name := _name_edit.text.strip_edges()
	if save_name == "":
		Services.overlay.toast("NAME THE CHRONICLE FIRST", "bad")
		_submitting = false
		return
	var saves_res: EngineResult = await _client().list_saves()
	if not saves_res.ok:
		# Never fall through to create on a failed pre-check — that would
		# blind-create and clobber an existing chronicle's autosave.
		Services.overlay.toast_error(saves_res)
		_submitting = false
		return
	for entry: Dictionary in saves_res.data.get("saves", []):
		if str(entry.get("base_name", "")).to_lower() == save_name.to_lower():
			Services.overlay.toast(
				"A CHRONICLE NAMED %s EXISTS — pick another name" % save_name.to_upper(), "bad"
			)
			_submitting = false
			return
	var res: EngineResult = await (
		_client()
		. create_session(
			{
				"kind": "chargen",
				"name": save_name,
				"seed": int(_seed_label.text),
				"pack_id": selected_pack,
				"profile": selected_profile,
				"death_mode": selected_death,
			}
		)
	)
	if not res.ok:
		Services.overlay.toast_error(res)
		_submitting = false
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
		_submitting = false
		return
	SessionStore.set_current(session)
	_reset_submitting.call_deferred()  # one-shot: a same-frame re-press stays blocked
	navigate.emit("ceremony", {"session": session})
	# Apply the pack after navigating: applying first rebuilds this screen
	# while it is still the visible one (visible flicker).
	ClientSettings.set_value("ui/last_played_pack", selected_pack)
	PackThemes.apply(selected_pack)


func _reset_submitting() -> void:
	_submitting = false
