extends GdUnitTestSuite
## ScreenStack navigation (spec §6): replace/enter/exit/ESC.


class ProbeScreen:
	extends BaseScreen
	var entered_with: Array = []
	var exits := 0

	func screen_enter(params: Dictionary) -> void:
		entered_with.append(params)

	func screen_exit() -> void:
		exits += 1


class EscScreen:
	extends ProbeScreen

	func esc_target() -> String:
		return "home"


func _stack_with_two() -> Array:
	var stack := ScreenStack.new()
	add_child(auto_free(stack))
	var a := ProbeScreen.new()
	var b := EscScreen.new()
	stack.register("home", a)
	stack.register("away", b)
	return [stack, a, b]


func test_replace_enters_and_exits() -> void:
	var ctx: Array = _stack_with_two()
	var stack: ScreenStack = ctx[0]
	var a: ProbeScreen = ctx[1]
	var b: ProbeScreen = ctx[2]
	stack.replace("home", {"from": "test"})
	assert_str(stack.current_name()).is_equal("home")
	assert_that(a.entered_with.size()).is_equal(1)
	assert_that(a.entered_with[0]).is_equal({"from": "test"})
	assert_bool(a.visible).is_true()
	assert_bool(b.visible).is_false()

	stack.replace("away")
	assert_str(stack.current_name()).is_equal("away")
	assert_that(a.exits).is_equal(1)
	assert_bool(a.visible).is_false()
	assert_bool(b.visible).is_true()


func test_esc_routes_to_esc_target() -> void:
	var ctx: Array = _stack_with_two()
	var stack: ScreenStack = ctx[0]
	stack.replace("away")
	var key := InputEventKey.new()
	key.pressed = true
	key.keycode = KEY_ESCAPE
	stack._unhandled_input(key)
	assert_str(stack.current_name()).is_equal("home")


func test_esc_does_nothing_without_target() -> void:
	var ctx: Array = _stack_with_two()
	var stack: ScreenStack = ctx[0]
	stack.replace("home")
	var key := InputEventKey.new()
	key.pressed = true
	key.keycode = KEY_ESCAPE
	stack._unhandled_input(key)
	assert_str(stack.current_name()).is_equal("home")
