extends Node
## Autoload: PackThemes. Builds the four token sets as a mechanical
## translation of tokens.css (never reinterpreted — spec §5) and applies
## server theme hints (symbolic only: motif + ambience; §A6).

signal pack_changed(theme: PackTheme)

const NEUTRAL := "neutral"

var current: PackTheme
var _sets: Dictionary = {}


func _ready() -> void:
	_sets = _build_sets()
	current = _sets[NEUTRAL]


static func _build_sets() -> Dictionary:
	return {
		"scifi":
		_make(
			"scifi",
			"0A0F1E",
			"101830",
			"27345C",
			"E6EBF7",
			"7C88A8",
			"F5A623",
			"46C48A",
			"E5484D",
			"✦",
			["meteors", "birds"]
		),
		"fantasy":
		_make(
			"fantasy",
			"17120C",
			"221A10",
			"4A3A22",
			"F2E9D8",
			"9C8D76",
			"D9A02B",
			"7FA85C",
			"C24A52",
			"❧",
			["fireflies", "leaves"]
		),
		"neutral":
		_make(
			"neutral",
			"13161D",
			"1A1F2A",
			"2C3444",
			"E9EDF5",
			"7E8899",
			"8FA3C8",
			"5FC98E",
			"E5606C",
			"◆",
			[]
		),
		"dead":
		_make(
			"dead",
			"180F12",
			"221418",
			"4A2830",
			"E9DCD8",
			"96787E",
			"8E3A46",
			"7FA85C",
			"E5606C",
			"✝",
			[]
		),
	}


static func _make(
	id: String,
	bg: String,
	panel: String,
	line: String,
	ink: String,
	muted: String,
	accent: String,
	ok: String,
	danger: String,
	motif: String,
	ambience: Array
) -> PackTheme:
	var t := PackTheme.new()
	t.id = id
	t.bg = Color(bg)
	t.panel = Color(panel)
	t.line = Color(line)
	t.ink = Color(ink)
	t.muted = Color(muted)
	t.accent = Color(accent)
	t.ok = Color(ok)
	t.danger = Color(danger)
	t.motif = motif
	t.ambience = PackedStringArray(ambience)
	return t


func has_pack(id: String) -> bool:
	return _sets.has(id)


## Unknown ids fall back to neutral (spec §5).
func get_theme(id: String) -> PackTheme:
	return _sets.get(id, _sets[NEUTRAL])


func apply(id: String) -> void:
	current = get_theme(id)
	pack_changed.emit(current)


## Applies a server `theme` hint (§A6) over the built-in set: motif and
## ambience are adopted when present; the named accent is symbolic and never
## overrides the tokens.css hexes. Sets `current` and emits pack_changed.
func apply_hint(pack_id: String, hint: Dictionary) -> void:
	var base: PackTheme = get_theme(pack_id)
	var t := PackTheme.new()
	t.id = base.id
	t.bg = base.bg
	t.panel = base.panel
	t.line = base.line
	t.ink = base.ink
	t.muted = base.muted
	t.accent = base.accent
	t.ok = base.ok
	t.danger = base.danger
	t.motif = base.motif
	t.ambience = base.ambience
	if str(hint.get("motif", "")) != "":
		t.motif = str(hint["motif"])
	var amb: Variant = hint.get("ambience", null)
	if amb is Array and not amb.is_empty():
		# Cosmetic hint only: build element-wise so a non-String entry is
		# dropped instead of raising inside PackedStringArray's conversion.
		var packed := PackedStringArray()
		for element: Variant in amb:
			if element is String:
				packed.append(element)
		t.ambience = packed
	current = t
	pack_changed.emit(current)
