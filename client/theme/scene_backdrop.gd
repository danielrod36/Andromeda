class_name SceneBackdrop
extends Control
## Cinematic scene backdrop (tokens.css §cinematic scene system).
## Static in M2: gradient + fixed star specks + planet + horizon + veil.
## Ambient motion (twinkle, drift, beacon, meteor, birds) is M5.

## tokens.css .sc-* linear-gradient stops (top → bottom).
const GRADIENTS := {
	"night": [[0.0, "0B0E17"], [0.52, "141B31"], [0.78, "1E2A4D"], [1.0, "2A3A66"]],
	"dawn": [[0.0, "0B0E17"], [0.45, "181E38"], [0.75, "41365C"], [1.0, "8A5A3A"]],
	"dusk": [[0.0, "0B0E17"], [0.55, "241E3C"], [0.85, "5C3A4E"], [1.0, "7C4A44"]],
	"flare": [[0.0, "0B0E17"], [0.55, "2E1524"], [0.85, "571E28"], [1.0, "7A2830"]],
	"gold": [[0.0, "0B0E17"], [0.5, "1E2438"], [0.8, "4A3A22"], [1.0, "8A6428"]],
	"noon": [[0.0, "0B0E17"], [0.4, "1A2440"], [0.7, "3A4A7C"], [1.0, "C97B4A"]],
	"port": [[0.0, "0B0E17"], [0.45, "1A2030"], [0.75, "3A3230"], [1.0, "5C4630"]],
	"dead": [[0.0, "120A0D"], [0.55, "1E1216"], [1.0, "331A20"]],
}

## tokens.css .sc-night star specks: [x%, y%, radius px, alpha, color?]. The
## size is the CSS gradient's radius; color defaults to _STAR_INK (the
## 63%/10% speck is rgba(143,163,200,.7) = #8FA3C8).
const NIGHT_STARS := [
	[12.0, 18.0, 1.5, 0.8],
	[28.0, 8.0, 1.0, 0.5],
	[45.0, 22.0, 1.0, 0.4],
	[63.0, 10.0, 2.0, 0.7, "8FA3C8"],
	[78.0, 26.0, 1.0, 0.45],
	[90.0, 12.0, 1.5, 0.6],
	[8.0, 40.0, 1.0, 0.3],
]

## tokens.css .horizon clip-path polygon, as [x%, y%] within the bottom band.
const HORIZON_POINTS := [
	[0, 62],
	[6, 62],
	[6, 54],
	[12, 54],
	[12, 66],
	[20, 66],
	[20, 40],
	[26, 40],
	[26, 30],
	[30, 30],
	[30, 40],
	[36, 40],
	[36, 58],
	[44, 58],
	[44, 46],
	[52, 46],
	[52, 24],
	[55, 24],
	[55, 12],
	[58, 12],
	[58, 24],
	[62, 24],
	[62, 52],
	[70, 52],
	[70, 62],
	[78, 62],
	[78, 44],
	[86, 44],
	[86, 58],
	[100, 58],
	[100, 100],
	[0, 100],
]

const _STAR_INK := "E9EDF5"
const _HORIZON_FILL := "080A10"
const _HORIZON_BAND := 0.26  # bottom 26%

@export var scene_id := "night":
	set(v):
		scene_id = v
		queue_redraw()
@export var kicker_text := "":
	set(v):
		kicker_text = v
		queue_redraw()
@export var footer_text := "":
	set(v):
		footer_text = v
		queue_redraw()
@export var show_planet := true:
	set(v):
		show_planet = v
		queue_redraw()
@export var show_horizon := true:
	set(v):
		show_horizon = v
		queue_redraw()

var pack_theme: PackTheme:
	set(v):
		pack_theme = v
		queue_redraw()


func _ready() -> void:
	mouse_filter = Control.MOUSE_FILTER_IGNORE


func _draw() -> void:
	var r := Rect2(Vector2.ZERO, size)
	_draw_gradient(r)
	if scene_id != "flat":
		_draw_stars(r)
		if show_planet:
			_draw_planet(r)
		if show_horizon:
			_draw_horizon(r)
		_draw_veil(r)
	_draw_labels(r)


func _draw_gradient(r: Rect2) -> void:
	var stops: Array = GRADIENTS.get(scene_id, [])
	if stops.is_empty():
		# .sc-flat — the pack bg.
		draw_rect(r, pack_theme.bg if pack_theme != null else Color("13161D"))
		return
	var prev_offset: float = stops[0][0]
	var prev_color := Color(stops[0][1])
	draw_rect(Rect2(r.position, Vector2(r.size.x, 1)), prev_color)
	for i: int in range(1, stops.size()):
		var offset: float = stops[i][0]
		var color := Color(stops[i][1])
		# Vertical strip interpolation in N slices keeps the gradient smooth.
		var y_from := r.size.y * prev_offset
		var y_to := r.size.y * offset
		const SLICES := 24
		for s: int in SLICES:
			var t0 := float(s) / SLICES
			var t1 := float(s + 1) / SLICES
			var strip := Rect2(
				0, y_from + (y_to - y_from) * t0, r.size.x, (y_to - y_from) * (t1 - t0) + 1
			)
			draw_rect(strip, prev_color.lerp(color, (t0 + t1) * 0.5))
		prev_offset = offset
		prev_color = color


func _draw_stars(r: Rect2) -> void:
	for speck: Array in NIGHT_STARS:
		var pos := Vector2(r.size.x * speck[0] / 100.0, r.size.y * speck[1] / 100.0)
		# CSS `radial-gradient(Npx Npx ...)` — N is the radius; the speck's
		# drawn size is the diameter.
		var side: float = float(speck[2]) * 2.0
		var c := Color(_STAR_INK)
		if speck.size() > 4:
			c = Color(str(speck[4]))
		c.a = speck[3]
		draw_rect(Rect2(pos - Vector2(side, side) * 0.5, Vector2(side, side)), c)


func _draw_planet(r: Rect2) -> void:
	# 130px radial-gradient circle, top 8% right 10% (tokens.css .planet), with
	# a 44px glow halo behind it: box-shadow rgba(201,123,74,.35) reaching
	# 65+44=109px from the center. Flat .35 out to the body edge, fading to 0
	# at the halo edge — the body overdraws the middle, leaving the edge ring.
	var center := Vector2(r.size.x * 0.90 - 65.0, r.size.y * 0.08 + 65.0)
	var glow := Color("C97B4A")
	_draw_radial(center, 109.0, [[0.0, glow, 0.35], [65.0 / 109.0, glow, 0.35], [1.0, glow, 0.0]])
	# `circle at 34% 30%`: the highlight sits up-left of the body center —
	# (0.34 − 0.5)·130 = −20.8, (0.30 − 0.5)·130 = −26.
	var light_offset := Vector2(-130.0 * 0.16, -130.0 * 0.20)
	_draw_radial(
		center + light_offset,
		65.0,
		[
			[0.0, Color("C97B4A"), 1.0],
			[0.42, Color("A8542E"), 1.0],
			[0.78, Color("6E3319"), 1.0],
			[1.0, Color("4A2212"), 1.0]
		]
	)


func _draw_radial(center: Vector2, radius: float, stops: Array) -> void:
	# Concentric-ring approximation of a radial gradient (48 rings).
	const RINGS := 48
	for i: int in range(RINGS, 0, -1):
		var t := float(i) / RINGS
		var color: Color = _radial_color(stops, t)
		draw_circle(center, radius * t, color)


static func _radial_color(stops: Array, t: float) -> Color:
	# stops: [offset, hex, alpha?] — alpha defaults to 1.
	if t <= float(stops[0][0]):
		var c0: Color = Color(stops[0][1])
		c0.a = stops[0][2] if stops[0].size() > 2 else 1.0
		return c0
	var prev: Array = stops[0]
	for i: int in range(1, stops.size()):
		var cur: Array = stops[i]
		if t <= float(cur[0]):
			var span: float = float(cur[0]) - float(prev[0])
			var k: float = (t - prev[0]) / span if span > 0.0 else 1.0
			var a0: float = prev[2] if prev.size() > 2 else 1.0
			var a1: float = cur[2] if cur.size() > 2 else 1.0
			var c: Color = Color(prev[1]).lerp(Color(cur[1]), k)
			c.a = lerpf(a0, a1, k)
			return c
		prev = cur
	var cl: Color = Color(stops[-1][1])
	cl.a = stops[-1][2] if stops[-1].size() > 2 else 1.0
	return cl


func _draw_horizon(r: Rect2) -> void:
	var band_top := r.size.y * (1.0 - _HORIZON_BAND)
	var pts := PackedVector2Array()
	for p: Array in HORIZON_POINTS:
		pts.append(
			Vector2(r.size.x * p[0] / 100.0, band_top + r.size.y * _HORIZON_BAND * p[1] / 100.0)
		)
	draw_colored_polygon(pts, Color(_HORIZON_FILL))


func _draw_veil(r: Rect2) -> void:
	# .veil-cinema: rgba(8,10,16,.34) → .55 at 60% → .78 at 100%.
	var c := Color("080A10")
	var bands := [[0.0, 0.6, 0.34, 0.55], [0.6, 1.0, 0.55, 0.78]]
	for band: Array in bands:
		var y_from: float = r.size.y * band[0]
		var y_to: float = r.size.y * band[1]
		const SLICES := 16
		for s: int in SLICES:
			var t0 := float(s) / SLICES
			var t1 := float(s + 1) / SLICES
			var a: float = lerpf(band[2], band[3], (t0 + t1) * 0.5)
			var strip := Rect2(
				0, y_from + (y_to - y_from) * t0, r.size.x, (y_to - y_from) * (t1 - t0) + 1
			)
			var col := c
			col.a = a
			draw_rect(strip, col)


func _draw_labels(r: Rect2) -> void:
	var accent := pack_theme.accent if pack_theme != null else Color("8FA3C8")
	var muted := pack_theme.muted if pack_theme != null else Color("7E8899")
	if kicker_text != "":
		draw_string(
			Fonts.micro_tracked(),
			Vector2(18, 14 + 12),
			kicker_text,
			HORIZONTAL_ALIGNMENT_LEFT,
			-1,
			12,
			accent
		)
	if footer_text != "":
		draw_string(
			Fonts.micro_tracked(),
			Vector2(22, r.size.y - 12),
			footer_text,
			HORIZONTAL_ALIGNMENT_LEFT,
			-1,
			12,
			muted
		)
