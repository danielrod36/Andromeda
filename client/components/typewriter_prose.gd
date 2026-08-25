class_name TypewriterProse
extends VBoxContainer
## Narrator prose area (spec §3, tokens.css .spine): narration blocks type
## char-by-char at the reader's text speed (server pre-splits sentences),
## change/badge blocks land as instant lines, `done` snaps the tail home and
## announces all_text_shown — once per stream, reset by the next narration.
## Connect feed() to BeatDirector.block_received; skip() snaps without emitting.
##
## Layout: a landed transcript (RichTextLabel, append-only) plus an active
## line (Label) that carries the typing cursor + caret — per-char cost is
## O(active sentence), not O(transcript). Transcript content is bbcode-
## ESCAPED ([→[lb], ]→[rb]) so LLM prose can never inject tags; only this
## component's own change/badge color tags ride the wire. History is capped
## (_MAX_BLOCKS); exceeding it rewrites the transcript from the window.

signal all_text_shown

const CARET := "\u258C"
const _MAX_BLOCKS := 400
## Trims run in batches: the window is sliced back to _MAX_BLOCKS only
## once it exceeds _MAX_BLOCKS + _TRIM_BATCH, so the full-transcript
## rewrite amortizes to O(window / batch) per landing.
const _TRIM_BATCH := 100

## reading/text_speed → ms per character (spec C2).
const SPEED_MS := {"slow": 45, "medium": 25, "fast": 12, "instant": 0}

var _theme: PackTheme
var _rich: RichTextLabel
var _active: Label
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


## font_size and shadow are presentation knobs for the screens that host
## this component (the ceremony reads its intro larger, over a scene).
func setup(t: PackTheme, font_size := 14, shadow := false) -> void:
	_theme = t
	_rich = RichTextLabel.new()
	_rich.bbcode_enabled = true  # only for our color tags; content is escaped
	_rich.scroll_following = true
	_rich.fit_content = false
	_rich.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_rich.add_theme_font_override("font", Fonts.prose())
	_rich.add_theme_font_size_override("font_size", font_size)
	_rich.add_theme_color_override("default_color", t.ink)
	add_child(_rich)
	_active = Label.new()
	_active.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_active.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_active.add_theme_font_override("font", Fonts.prose())
	_active.add_theme_font_size_override("font_size", font_size)
	_active.add_theme_color_override("font_color", t.ink)
	_active.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_active)
	if shadow:
		for node: Control in [_rich, _active]:
			node.add_theme_color_override("font_shadow_color", Color(0, 0, 0, 0.6))
			node.add_theme_constant_override("shadow_offset_x", 0)
			node.add_theme_constant_override("shadow_offset_y", 2)


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
	var parts := PackedStringArray()
	var prev_kind := ""
	for block: Dictionary in _render_blocks():
		var kind := str(block["kind"])
		if not parts.is_empty():
			var newline := prev_kind != "narration" or kind != "narration"
			parts[parts.size() - 1] += "\n" if newline else " "
		parts.append(str(block["text"]))
		prev_kind = kind
	return "".join(parts)


func is_typing() -> bool:
	return _typing


## Leaving the tree mid-typing (screens push/pop; auto_free) lands everything
## and cancels the pump — the pending per-char timer would otherwise resume
## on a dead instance, and a re-added instance would sit frozen in _typing.
func _notification(what: int) -> void:
	if what == NOTIFICATION_EXIT_TREE and _typing:
		_snap()


## Milliseconds per character right now. Reduced motion and the "instant"
## speed both collapse typing to zero.
func _speed_ms() -> int:
	if bool(ClientSettings.get_value("reading/reduced_motion")):
		return 0
	return int(SPEED_MS.get(str(ClientSettings.get_value("reading/text_speed")), 25))


## bbcode escape for wire content — brackets in LLM prose must render
## literally, never parse as tags.
static func _esc(text: String) -> String:
	return text.replace("[", "[lb]").replace("]", "[rb]")


func _land(block: Dictionary) -> void:
	_landed.append(block)
	if _landed.size() > _MAX_BLOCKS + _TRIM_BATCH:
		_landed = _landed.slice(_landed.size() - _MAX_BLOCKS)
		_rewrite_transcript()
	else:
		_append_transcript(block)


func _begin(block: Dictionary) -> void:
	_current = block
	_progress = 0
	_typing = true
	_gen += 1
	_update_active()
	_pump(_gen)


## Snap everything pending (current + queue) to landed, dropping the caret.
func _snap() -> void:
	_gen += 1
	_typing = false
	if not _current.is_empty():
		_land(_current)
		_current = {}
	for queued: Dictionary in _queue:
		_land(queued)
	_queue.clear()
	_progress = 0
	_update_active()


## Advance the cursor one char at a time until superseded or drained.
func _pump(gen: int) -> void:
	while gen == _gen and _typing and is_inside_tree():
		var text := str(_current.get("text", ""))
		_progress += 1
		_update_active()
		if _progress >= text.length():
			_land(_current)
			_current = {}
			_progress = 0
			if _queue.is_empty():
				_typing = false
				_update_active()
				return
			_current = _queue.pop_front()
		await get_tree().create_timer(float(_speed_ms()) / 1000.0).timeout


## The typing line: the active block truncated at the cursor, caret appended.
func _update_active() -> void:
	if _active == null:
		return
	if _current.is_empty():
		_active.text = ""
		return
	var text := str(_current["text"])
	var shown := text.substr(0, _progress)
	if _progress < text.length():
		shown += CARET
	_active.text = shown


func _append_transcript(block: Dictionary) -> void:
	if _transcript_has_text():
		var prev_index := _landed.size() - 2  # block is already landed at -1
		var prev_kind := str(_landed[prev_index]["kind"]) if prev_index >= 0 else ""
		var sep := " " if (str(block["kind"]) == "narration" and prev_kind == "narration") else "\n"
		_rich.append_text(sep)
	_append_block_bbcode(block)


## One block as bbcode: escaped content, colored for change/badge.
func _append_block_bbcode(block: Dictionary) -> void:
	var kind := str(block["kind"])
	var txt := _esc(str(block["text"]))
	match kind:
		"change":
			_rich.append_text("[color=#%s]%s[/color]" % [_theme.muted.to_html(false), txt])
		"badge":
			_rich.append_text("[color=#%s]%s[/color]" % [_theme.accent.to_html(false), txt])
		_:
			_rich.append_text(txt)


## Full transcript rewrite from the (already capped) window — only when the
## cap drops the oldest blocks.
func _rewrite_transcript() -> void:
	_rich.clear()
	var window := _landed.duplicate()
	_landed = []
	for block: Dictionary in window:
		_landed.append(block)
		_append_transcript(block)


func _transcript_has_text() -> bool:
	return not _rich.get_parsed_text().is_empty()


## Landed blocks, then the active narration truncated at the cursor.
func _render_blocks() -> Array:
	var blocks := _landed.duplicate()
	if not _current.is_empty():
		var text := str(_current["text"])
		var shown := text.substr(0, _progress)
		if _progress < text.length():
			shown += CARET
		blocks.append({"kind": "narration", "text": shown})
	return blocks
