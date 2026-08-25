class_name StoryRail
extends VBoxContainer
## The story rail (mockup 06b .rail): THE STORY SO FAR header over the beat
## entries as they resolve — newest last, newest prose at full ink, older
## prose dimmed to 70%; stamps always stay accent. Steered re-tells mark the
## last stamp " — RE-TOLD" in danger.

const RETOLD_SUFFIX := " \u2014 RE-TOLD"

var _theme: PackTheme
var _entries: VBoxContainer
## One Dictionary per beat: {stamp, prose, retold} — rebuilt on change.
var _beats: Array = []


func setup(t: PackTheme) -> void:
	_theme = t
	custom_minimum_size = Vector2(300, 0)
	add_theme_constant_override("separation", 12)
	var header := Fonts.label("THE STORY SO FAR", Fonts.micro_tracked(), 12, t.accent)
	add_child(header)
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	add_child(scroll)
	_entries = VBoxContainer.new()
	_entries.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_entries.add_theme_constant_override("separation", 14)
	scroll.add_child(_entries)


## Append one beat entry (newest last). `stamp` is the screen-provided
## player-facing stamp (e.g. "TERM 2 · SURVEY DUTY") — never a phase key.
func add_beat(stamp: String, prose: String) -> void:
	_beats.append({"stamp": stamp, "prose": prose, "retold": false})
	_rebuild()


## Stamp the newest beat as re-told (steered narration replayed).
func mark_last_retold() -> void:
	if _beats.is_empty():
		return
	_beats[_beats.size() - 1]["retold"] = true
	_rebuild()


func beat_count() -> int:
	return _beats.size()


func _rebuild() -> void:
	for child: Node in _entries.get_children():
		_entries.remove_child(child)
		child.free()
	for i: int in _beats.size():
		var beat: Dictionary = _beats[i]
		var newest := i == _beats.size() - 1
		var entry := VBoxContainer.new()
		entry.add_theme_constant_override("separation", 4)
		entry.add_child(_stamp_label(beat))
		var prose := Fonts.label(str(beat["prose"]), Fonts.prose(), 12, _theme.ink)
		prose.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		prose.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		if not newest:
			prose.modulate.a = 0.7
		entry.add_child(prose)
		_entries.add_child(entry)


func _stamp_label(beat: Dictionary) -> Label:
	var stamp := str(beat["stamp"])
	var color := _theme.accent
	if bool(beat.get("retold", false)):
		stamp += RETOLD_SUFFIX
		color = _theme.danger
	var label := Fonts.label(stamp, Fonts.micro(), 11, color)
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	return label
