class_name BaseScreen
extends Control
## Screen contract for the ScreenStack (spec §6).

## Emitted to navigate; ScreenStack.register auto-connects it to replace().
signal navigate(target: String, params: Dictionary)


## Called by the stack when the screen becomes visible. Params come from the
## navigating caller ("" keys documented per screen).
func screen_enter(_params: Dictionary) -> void:
	pass


## Called when the screen is navigated away from.
func screen_exit() -> void:
	pass


## Where ESC goes; "" = ESC does nothing.
func esc_target() -> String:
	return ""
