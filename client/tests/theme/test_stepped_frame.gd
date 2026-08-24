extends GdUnitTestSuite
## SteppedFrame geometry: the tokens.css clip-path polygons, converted.


func test_outer_polygon_matches_px_clip_path() -> void:
	# tokens.css .px: (0,8)(4,8)(4,4)(8,4)(8,0) then mirrored — 20 points.
	var pts := SteppedFrame._stepped(Rect2(0, 0, 100, 100), 4.0, 8.0)
	assert_that(pts.size()).is_equal(20)
	assert_that(pts[0]).is_equal(Vector2(0, 8))
	assert_that(pts[1]).is_equal(Vector2(4, 8))
	assert_that(pts[2]).is_equal(Vector2(4, 4))
	assert_that(pts[3]).is_equal(Vector2(8, 4))
	assert_that(pts[4]).is_equal(Vector2(8, 0))
	assert_that(pts[5]).is_equal(Vector2(92, 0))
	assert_that(pts[10]).is_equal(Vector2(100, 92))


func test_inner_polygon_matches_px_in_clip_path() -> void:
	# tokens.css .px-in: (0,6)(3,6)(3,3)(6,3)(6,0) then mirrored.
	var pts := SteppedFrame._stepped(Rect2(2, 2, 98, 98), 3.0, 6.0)
	assert_that(pts[0]).is_equal(Vector2(2, 8))
	assert_that(pts[4]).is_equal(Vector2(8, 2))


func test_apply_theme_sets_colors() -> void:
	var frame: SteppedFrame = auto_free(SteppedFrame.new())
	var t := PackTheme.new()
	t.accent = Color("F5A623")
	t.panel = Color("101830")
	frame.apply_theme(t)
	assert_that(frame.ring_color).is_equal(Color("F5A623"))
	assert_that(frame.fill_color).is_equal(Color("101830"))


func test_off_tree_frame_frees_unparented_content() -> void:
	# Regression: _content is created in the field initializer but parented
	# only in _ready(); freeing an off-tree frame used to orphan it (the
	# gdUnit run exited 101 with a leaked CanvasItem RID). SteppedFrame now
	# frees unparented content on PREDELETE — this pins that contract.
	var frame := SteppedFrame.new()
	var content: MarginContainer = frame._content
	frame.free()
	assert_bool(is_instance_valid(content)).is_false()
