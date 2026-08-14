extends Control
## Boot root (spec §6): spawn sidecar → LISTENING → health → Title.
## Mounts ScreenStack + OverlayLayer only — no global backdrop in M2
## (mocks 02/03/05 are flat-bg screens; Title owns its viewport pane).

var _stack: ScreenStack
var _overlay: OverlayLayer
var _boot_lines: Array = []
var _boot_error: Control


func _ready() -> void:
	_overlay = OverlayLayer.new()
	add_child(_overlay)
	Services.overlay = _overlay
	_stack = ScreenStack.new()
	_stack.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(_stack)
	_boot()


func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_CLOSE_REQUEST:
		Services.shutdown()
		get_tree().quit()


func _boot() -> void:
	if Services.sidecar == null:
		Services.sidecar = SidecarProcess.new()
		add_child(Services.sidecar)
	if Services.client == null:
		Services.client = EngineClient.new()
		add_child(Services.client)
	_boot_lines = ["REFEREE: WAKING…"]
	# one-shot so a RETRY after failure can't double-fire the handlers
	Services.sidecar.boot_failed.connect(_on_boot_failed, CONNECT_ONE_SHOT)
	Services.sidecar.booted.connect(_on_booted, CONNECT_ONE_SHOT)
	Services.sidecar.spawn()


func _on_booted(base_url: String, port: int) -> void:
	Services.client.setup(base_url)
	await Services.client.refresh_contracts()
	_boot_lines.append("REFEREE: LISTENING · 127.0.0.1:%d" % port)
	_boot_lines.append("SAVES: OK · DICE STREAMS: PRIMED")
	_register_screens()
	_stack.replace("title", {"boot_lines": _boot_lines})


func _on_boot_failed(reason: String) -> void:
	var t := PackThemes.current
	_boot_error = CenterContainer.new()
	_boot_error.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(_boot_error)
	var frame := Kit.px_frame(t, "danger", "panel")
	frame.custom_minimum_size = Vector2(520, 0)
	_boot_error.add_child(frame)
	var box := VBoxContainer.new()
	box.add_theme_constant_override("separation", 12)
	frame.add_content(box)
	frame.set_content_margins(18, 16, 18, 16)
	box.add_child(Fonts.label("REFEREE NOT ANSWERING", Fonts.inter(), 15, t.danger))
	var msg := Fonts.label(reason, Fonts.data(), 11, t.muted)
	msg.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	msg.custom_minimum_size = Vector2(480, 0)
	box.add_child(msg)
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 12)
	box.add_child(row)
	var retry := Kit.btn("RETRY", t)
	retry.pressed.connect(_on_retry)
	row.add_child(retry)
	var quit := Kit.ghost_btn("QUIT", t)
	quit.pressed.connect(
		func() -> void:
			Services.shutdown()
			get_tree().quit()
	)
	row.add_child(quit)


func _on_retry() -> void:
	if _boot_error != null:
		_boot_error.queue_free()
		_boot_error = null
	_boot()


## Task 7 replaces this with the real set. Until then the shell boots to a
## placeholder so the wiring is inspectable.
func _register_screens() -> void:
	_stack.register("title", TitleScreen.new())
	_stack.register("settings", SettingsScreen.new())
	_stack.register("chronicles", ChroniclesScreen.new())
	_stack.register("new_journey", _placeholder("NEW JOURNEY arrives in Task 10"))
	_stack.register("stub", _placeholder("SHELL STUB arrives in Task 10"))


func _placeholder(text: String) -> Control:
	var c := Control.new()
	var t := PackThemes.current
	var bg := ColorRect.new()
	bg.color = t.bg
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	c.add_child(bg)
	var center := CenterContainer.new()
	center.set_anchors_preset(Control.PRESET_FULL_RECT)
	c.add_child(center)
	center.add_child(Fonts.label(text, Fonts.micro_tracked(), 13, t.muted))
	return c
