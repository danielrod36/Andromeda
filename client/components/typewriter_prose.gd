class_name TypewriterProse
extends VBoxContainer
## Narrator prose area (spec §3, tokens.css .spine): narration blocks type
## char-by-char at the reader's text speed (server pre-splits sentences),
## change/badge blocks land as instant lines, `done` snaps the tail home and
## announces all_text_shown — once per stream, reset by the next narration.
## Connect feed() to BeatDirector.block_received; skip() snaps without emitting.

signal all_text_shown

const CARET := "\u258C"

## reading/text_speed → ms per character (spec C2).
const SPEED_MS := {"slow": 45, "medium": 25, "fast": 12, "instant": 0}

var _theme: PackTheme
var _rich: RichTextLabel
## Blocks already fully shown: {kind: narration|change|badge, text: String}.
var _landed: Array = []
## Narration blocks waiting their turn behind the one currently typing.
var _queue: Array = []
## The narration block typing now ({} when idle) and its char cursor.
var _current := {}
var _progress := 0
var _typing := false
var _gen := 0  # typing-loop generation; bumping cancels a superseded loop
var _stream_done := false


func setup(t: PackTheme) -> void:
	_theme = t
	_rich = RichTextLabel.new()
	_rich.bbcode_enabled = true  # content is plain; only our color tags use it
	_rich.scroll_following = true
	_rich.fit_content = false
	_rich.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_rich.add_theme_font_override("font", Fonts.prose())
	_rich.add_theme_font_size_override("font_size", 14)
	_rich.add_theme_color_override("default_color", t.ink)
	add_child(_rich)


## Block dispatch — wire to BeatDirector.block_received.
func feed(block_type: String, content: String) -> void:
	if _theme == null:
		return
	match block_type:
		"narration":
			_stream_done = false  # narration after done opens a fresh stream
			if _speed_ms() == 0:
				_land({"kind": "narration", "text": content})
			elif not _typing:
				_begin({"kind": "narration", "text": content})
			else:
				_queue.append({"kind": "narration", "text": content})
				_rebuild()
		"change", "badge":
			# change/badge land instantly, so anything still typing or queued
			# snaps home first to keep the chronology intact.
			_snap()
			_land({"kind": block_type, "text": content})
		"done":
			_snap()
			if not _stream_done:
				_stream_done = true
				all_text_shown.emit()


## Complete the current block and everything buffered, without emitting —
## BeatDirector.skip() synthesizes the `done` block that does the emitting.
func skip() -> void:
	_snap()


func visible_text() -> String:
	# get_parsed_text() returns what the reader sees (.text holds the raw
	# bbcode source, and reads empty after clear()+append_text()).
	return _rich.get_parsed_text() if _rich != null else ""


func is_typing() -> bool:
	return _typing


## Milliseconds per character right now. Reduced motion and the "instant"
## speed both collapse typing to zero.
func _speed_ms() -> int:
	if bool(ClientSettings.get_value("reading/reduced_motion")):
		return 0
	return int(SPEED_MS.get(str(ClientSettings.get_value("reading/text_speed")), 25))


func _land(block: Dictionary) -> void:
	_landed.append(block)
	_rebuild()


func _begin(block: Dictionary) -> void:
	_current = block
	_progress = 0
	_typing = true
	_gen += 1
	_rebuild()
	_pump(_gen)


## Snap everything pending (current + queue) to landed, dropping the caret.
func _snap() -> void:
	_gen += 1
	_typing = false
	if not _current.is_empty():
		_landed.append(_current)
		_current = {}
	for queued: Dictionary in _queue:
		_landed.append(queued)
	_queue.clear()
	_progress = 0
	_rebuild()


## Advance the cursor one char at a time until superseded or drained.
func _pump(gen: int) -> void:
	while gen == _gen and _typing and is_inside_tree():
		var text := str(_current.get("text", ""))
		_progress += 1
		_rebuild()
		if _progress >= text.length():
			_landed.append(_current)
			_current = {}
			_progress = 0
			if _queue.is_empty():
				_typing = false
				_rebuild()
				return
			_current = _queue.pop_front()
		await get_tree().create_timer(float(_speed_ms()) / 1000.0).timeout


## Render landed blocks plus the truncated active block with the caret.
func _rebuild() -> void:
	if _rich == null:
		return
	var parts := PackedStringArray()
	var prev_kind := ""
	for block: Dictionary in _render_blocks():
		var kind := str(block["kind"])
		var txt := str(block["text"])
		if not parts.is_empty():
			var newline := prev_kind != "narration" or kind != "narration"
			parts[parts.size() - 1] += "\n" if newline else " "
		match kind:
			"change":
				parts.append("[color=#%s]%s[/color]" % [_theme.muted.to_html(false), txt])
			"badge":
				parts.append("[color=#%s]%s[/color]" % [_theme.accent.to_html(false), txt])
			_:
				parts.append(txt)
		prev_kind = kind
	_rich.clear()
	_rich.append_text("".join(parts))


## Landed blocks, then the active narration truncated at the cursor + caret.
func _render_blocks() -> Array:
	var blocks := _landed.duplicate()
	if not _current.is_empty():
		var shown := str(_current["text"]).substr(0, _progress) + CARET
		blocks.append({"kind": "narration", "text": shown})
	return blocks
