class_name Dither
extends RefCounted
## 4px dither overlay at ~3% (tokens.css §6.3). Statics only.

static var _texture: Texture2D


static func texture() -> Texture2D:
	if _texture == null:
		var img := Image.create(4, 4, false, Image.FORMAT_RGBA8)
		for y: int in 4:
			for x: int in 4:
				var on: bool = (x + y) % 2 == 0
				img.set_pixel(x, y, Color(1, 1, 1, 0.06) if on else Color(0, 0, 0, 0))
		_texture = ImageTexture.create_from_image(img)
	return _texture


## A full-rect tiled overlay; ignores mouse; add as the last child of a panel.
static func overlay() -> TextureRect:
	var tr := TextureRect.new()
	tr.texture = texture()
	tr.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	tr.stretch_mode = TextureRect.STRETCH_TILE
	tr.mouse_filter = Control.MOUSE_FILTER_IGNORE
	tr.set_anchors_preset(Control.PRESET_FULL_RECT)
	return tr
