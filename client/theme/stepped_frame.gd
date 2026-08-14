class_name SteppedFrame
extends Control
## tokens.css .px frame: 2px accent ring with 2px-stepped pixel corners
## (outer steps 4/8px, inner steps 3/6px) over a panel fill.

@export var ring_color: Color = Color.WHITE:
	set(v):
		ring_color = v
		queue_redraw()
@export var fill_color: Color = Color.BLACK:
	set(v):
		fill_color = v
		queue_redraw()

var _content := MarginContainer.new()


func _ready() -> void:
	_content.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(_content)


## Themed content container; margins default to 2 (the ring) until
## set_content_margins is called.
func add_content(node: Control) -> void:
	_content.add_child(node)


## Detach + free current content children. Detaching immediately (not just
## queue_free) lets callers re-add in the same frame without mixing live and
## dying children.
func clear_content() -> void:
	for child: Node in _content.get_children():
		_content.remove_child(child)
		child.free()


func set_content_margins(l: int, t: int, r: int, b: int) -> void:
	_content.add_theme_constant_override("margin_left", l)
	_content.add_theme_constant_override("margin_top", t)
	_content.add_theme_constant_override("margin_right", r)
	_content.add_theme_constant_override("margin_bottom", b)


func apply_theme(t: PackTheme, ring := "accent", fill := "panel") -> void:
	ring_color = t.get(ring)
	fill_color = t.get(fill)


## The stepped-corner polygon: (0,s2)(s1,s2)(s1,s1)(s2,s1)(s2,0) mirrored on
## all four corners. 20 points. s1/s2 are 4/8 (outer) or 3/6 (inner).
static func _stepped(r: Rect2, s1: float, s2: float) -> PackedVector2Array:
	var x0 := r.position.x
	var y0 := r.position.y
	var x1 := r.end.x
	var y1 := r.end.y
	return PackedVector2Array(
		[
			Vector2(x0, y0 + s2),
			Vector2(x0 + s1, y0 + s2),
			Vector2(x0 + s1, y0 + s1),
			Vector2(x0 + s2, y0 + s1),
			Vector2(x0 + s2, y0),
			Vector2(x1 - s2, y0),
			Vector2(x1 - s2, y0 + s1),
			Vector2(x1 - s1, y0 + s1),
			Vector2(x1 - s1, y0 + s2),
			Vector2(x1, y0 + s2),
			Vector2(x1, y1 - s2),
			Vector2(x1 - s1, y1 - s2),
			Vector2(x1 - s1, y1 - s1),
			Vector2(x1 - s2, y1 - s1),
			Vector2(x1 - s2, y1),
			Vector2(x0 + s2, y1),
			Vector2(x0 + s2, y1 - s1),
			Vector2(x0 + s1, y1 - s1),
			Vector2(x0 + s1, y1 - s2),
			Vector2(x0, y1 - s2),
		]
	)


func _draw() -> void:
	# The corner steps need ≥16px per axis (outer steps 4/8, inner 3/6 on a
	# rect shrunk by 2); below that the polygon degenerates to collinear
	# points and triangulation fails. Layout can call _draw at size (0,0).
	if size.x < 17.0 or size.y < 17.0:
		return
	var r := Rect2(Vector2.ZERO, size)
	draw_colored_polygon(_stepped(r, 4.0, 8.0), ring_color)
	draw_colored_polygon(_stepped(r.grow_individual(-2, -2, -2, -2), 3.0, 6.0), fill_color)
