class_name StoryRail
extends VBoxContainer
## The story rail (mockup 06b .rail): THE STORY SO FAR header over the beat
## entries as they resolve — newest last, newest prose at full ink, older
## prose dimmed to 70%; stamps always stay accent. Steered re-tells mark the
## last stamp " — RE-TOLD" in danger.
##
## Entries append incrementally (no teardown per beat: a collapse-and-grow
## cycle would defeat the follow-bottom logic and relayout the whole rail).
## Follow-bottom is user-aware: content growth snaps to the newest entry
## only while the reader sits at the bottom; a scroll-up suspends following
## until they return. The decision derives from observed bar state (max rose
## = growth; value-only = user scroll or snap echo) — no reliance on signal
## ordering.

const RETOLD_SUFFIX := " \u2014 RE-TOLD"

var _theme: PackTheme
var _entries: VBoxContainer
var _scroll: ScrollContainer
## One {entry, stamp, prose} per landed beat — nodes stay alive; only the
## previously-newest prose gets dimmed when a new beat arrives.
var _nodes: Array = []
## Follow-bottom state: gap below the viewport as of the last scroll change,
## and the bar max as of the last change (to distinguish growth).
var _bottom_gap := 0.0
var _last_max := 0.0


func setup(t: PackTheme) -> void:
	_theme = t
	custom_minimum_size = Vector2(300, 0)
	add_theme_constant_override("separation", 12)
	var header := Fonts.label("THE STORY SO FAR", Fonts.micro_tracked(), 12, t.accent)
	add_child(header)
	_scroll = ScrollContainer.new()
	_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	add_child(_scroll)
	# `changed` covers config/layout (max growth); `value_changed` covers
	# every value move — user scrolls AND our own snap echoes — and is the
	# only place the gap is measured. Range.changed alone never sees wheels.
	_scroll.get_v_scroll_bar().changed.connect(_on_scroll_changed)
	_scroll.get_v_scroll_bar().value_changed.connect(_on_scroll_value)
	_entries = VBoxContainer.new()
	_entries.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_entries.add_theme_constant_override("separation", 14)
	_scroll.add_child(_entries)


## Append one beat entry (newest last). `stamp` is the screen-provided
## player-facing stamp (e.g. "TERM 2 · SURVEY DUTY") — never a phase key.
func add_beat(stamp: String, prose: String) -> void:
	if not _nodes.is_empty():
		(_nodes[_nodes.size() - 1]["prose"] as Label).modulate.a = 0.7
	var entry := VBoxContainer.new()
	entry.add_theme_constant_override("separation", 4)
	var stamp_label := _stamp_label(stamp)
	entry.add_child(stamp_label)
	var prose_label := Fonts.label(prose, Fonts.prose(), 12, _theme.ink)
	prose_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	prose_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	entry.add_child(prose_label)
	_entries.add_child(entry)
	_nodes.append({"entry": entry, "stamp": stamp_label, "prose": prose_label})


## Stamp the newest beat as re-told (steered narration replayed).
## Idempotent: a second steer of the same beat re-tells the prose without
## stacking another suffix.
func mark_last_retold() -> void:
	if _nodes.is_empty():
		return
	var record: Dictionary = _nodes[_nodes.size() - 1]
	if bool(record.get("retold", false)):
		return
	record["retold"] = true
	var stamp_label: Label = record["stamp"]
	stamp_label.text += RETOLD_SUFFIX
	stamp_label.add_theme_color_override("font_color", _theme.danger)


func beat_count() -> int:
	return _nodes.size()


func _on_scroll_value(_value: float) -> void:
	if _scroll == null:
		return
	var bar := _scroll.get_v_scroll_bar()
	_bottom_gap = (bar.max_value - bar.page) - _scroll.scroll_vertical


func _on_scroll_changed() -> void:
	if _scroll == null:
		return
	var bar := _scroll.get_v_scroll_bar()
	var grew := bar.max_value > _last_max + 0.5
	_last_max = bar.max_value
	if grew and _bottom_gap <= 4.0:
		# Content grew while the reader sat at the bottom: ride it. The snap
		# itself fires value_changed, which re-measures the gap to ~0.
		_scroll.scroll_vertical = int(bar.max_value)


func _stamp_label(stamp: String) -> Label:
	var label := Fonts.label(stamp, Fonts.micro(), 11, _theme.accent)
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	return label
