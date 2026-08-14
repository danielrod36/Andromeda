class_name PackTheme
extends Resource
## One pack's token set: the eight colors + motif glyph + ambience list
## (design/mockups/final/tokens.css, .t-* blocks).

var id: String = ""
var bg: Color = Color.BLACK
var panel: Color = Color.BLACK
var line: Color = Color.BLACK
var ink: Color = Color.WHITE
var muted: Color = Color.GRAY
var accent: Color = Color.WHITE
var ok: Color = Color.GREEN
var danger: Color = Color.RED
var motif: String = "◆"
var ambience: PackedStringArray = PackedStringArray()
