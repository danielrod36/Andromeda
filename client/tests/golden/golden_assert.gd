class_name GoldenAssert
extends RefCounted
## Golden-layout screenshots (spec M2-D9): capture a full-rect screen at the
## pinned 1280×720 and compare against the committed baseline. Baselines
## guard regression; the HTML mocks guard intent — no HTML↔Godot pixel
## matching (different text rasterizers).

const BASELINE_DIR := "res://tests/golden"
const SIZE := Vector2i(1280, 720)
const MAX_CHANNEL_DELTA := 16  # per-pixel channel tolerance
const MAX_BAD_PIXEL_RATIO := 0.005  # ≤0.5% of pixels may exceed the delta
const MEAN_ABS_LIMIT := 1.0  # mean absolute per-channel delta


static func supported() -> bool:
	return DisplayServer.get_name() != "headless"


static func update_mode() -> bool:
	return OS.get_environment("GOLDEN_UPDATE") == "1"


## The caller must: add the screen to the tree at full rect, let it finish
## its data load, and await two process frames before calling. In update
## mode the baseline is (re)written and the result is always a match.
static func capture(screen: Control, baseline_name: String) -> Dictionary:
	screen.set_anchors_preset(Control.PRESET_FULL_RECT)
	screen.size = Vector2(SIZE)
	var img := screen.get_viewport().get_texture().get_image()
	var res_path := BASELINE_DIR.path_join(baseline_name + ".png")
	if update_mode():
		var abs_path := ProjectSettings.globalize_path(res_path)
		var err := img.save_png(abs_path)
		return {"match": err == OK, "stats": "baseline written to " + abs_path}
	# Image.load (not ResourceLoader): fresh PNGs on disk have no .import
	# sidecar yet, and ResourceLoader only sees imported resources.
	var baseline := Image.new()
	if baseline.load(ProjectSettings.globalize_path(res_path)) != OK:
		return {
			"match": false, "stats": "no baseline at " + res_path + " — run with GOLDEN_UPDATE=1"
		}
	return compare(img, baseline)


static func compare(actual: Image, baseline: Image) -> Dictionary:
	if actual.get_size() != baseline.get_size():
		return {
			"match": false,
			"stats": "size mismatch: %s vs %s" % [actual.get_size(), baseline.get_size()],
		}
	var w := actual.get_width()
	var h := actual.get_height()
	var bad := 0
	var total := 0.0
	for y: int in h:
		for x: int in w:
			var a := actual.get_pixel(x, y)
			var b := baseline.get_pixel(x, y)
			var d := maxi(
				maxi(absi(int(a.r8) - int(b.r8)), absi(int(a.g8) - int(b.g8))),
				absi(int(a.b8) - int(b.b8))
			)
			total += d
			if d > MAX_CHANNEL_DELTA:
				bad += 1
	var ratio := float(bad) / float(w * h)
	var mean := total / float(w * h)
	return {
		"match": ratio <= MAX_BAD_PIXEL_RATIO and mean <= MEAN_ABS_LIMIT,
		"stats": "bad=%.4f%% mean=%.3f" % [ratio * 100.0, mean],
	}
