class_name Fonts
extends RefCounted
## tokens.css type system. Statics only — never instantiate.
## Roles: title / int(eractive) / prose / data / micro.

const _SPACE_GROTESK := "res://assets/fonts/spacegrotesk/SpaceGrotesk-Variable.ttf"
const _CHAKRA_SEMIBOLD := "res://assets/fonts/chakrapetch/ChakraPetch-SemiBold.ttf"
const _CHAKRA_MEDIUM := "res://assets/fonts/chakrapetch/ChakraPetch-Medium.ttf"
const _ATKINSON := "res://assets/fonts/atkinsonhyperlegible/AtkinsonHyperlegible-Regular.ttf"
const _ATKINSON_BOLD := "res://assets/fonts/atkinsonhyperlegible/AtkinsonHyperlegible-Bold.ttf"
const _PLEX_MEDIUM := "res://assets/fonts/ibmplexmono/IBMPlexMono-Medium.ttf"
const _PLEX_SEMIBOLD := "res://assets/fonts/ibmplexmono/IBMPlexMono-SemiBold.ttf"
const _VT323 := "res://assets/fonts/vt323/VT323-Regular.ttf"

static var _cache: Dictionary = {}


static func _load(path: String) -> Font:
	if not _cache.has(path):
		_cache[path] = ResourceLoader.load(path) as Font
	return _cache[path]


## Space Grotesk 700 (screen titles, big numbers).
static func title() -> Font:
	if not _cache.has("title"):
		var v := FontVariation.new()
		v.base_font = _load(_SPACE_GROTESK)
		v.variation_opentype = {"wght": 700}
		_cache["title"] = v
	return _cache["title"]


## Chakra Petch 600 (interactive titles: menus, choices, buttons).
static func inter() -> Font:
	return _load(_CHAKRA_SEMIBOLD)


## Chakra Petch 500.
static func inter_medium() -> Font:
	return _load(_CHAKRA_MEDIUM)


## Atkinson Hyperlegible 400 (prose).
static func prose() -> Font:
	return _load(_ATKINSON)


## Atkinson Hyperlegible 700.
static func prose_bold() -> Font:
	return _load(_ATKINSON_BOLD)


## IBM Plex Mono 500 (data: dockets, odds, receipts).
static func data() -> Font:
	return _load(_PLEX_MEDIUM)


## IBM Plex Mono 600.
static func data_semibold() -> Font:
	return _load(_PLEX_SEMIBOLD)


## VT323 (micro-labels: kickers, pack tags, SEQ stamps — never main content).
static func micro() -> Font:
	return _load(_VT323)


## VT323 with +2px glyph tracking (the mocks' .2em micro tracking at 12px).
static func micro_tracked() -> Font:
	if not _cache.has("micro_tracked"):
		var v := FontVariation.new()
		v.base_font = _load(_VT323)
		v.spacing_glyph = 2
		_cache["micro_tracked"] = v
	return _cache["micro_tracked"]


## Builds a Label with the role font/size/color applied as overrides.
static func label(text: String, font: Font, size: int, color: Color) -> Label:
	var l := Label.new()
	l.text = text
	l.add_theme_font_override("font", font)
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", color)
	return l
