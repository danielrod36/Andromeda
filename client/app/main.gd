extends Control
## Boot root (spec §6): spawn sidecar → LISTENING → health → Title.
## Mounts ScreenStack + OverlayLayer only — no global backdrop in M2
## (mocks 02/03/05 are flat-bg screens; Title owns its viewport pane).

var _stack: ScreenStack
var _overlay: OverlayLayer
var _boot_lines: Array = []
var _boot_error: Control


func _ready() -> void:
	# mount the stack BEFORE the overlay: _unhandled_input propagates in
	# reverse tree order, so the overlay's modals must be later children to
	# consume ESC before ScreenStack navigates behind an open modal (the
	# overlay draws above via CanvasLayer.layer = 10 either way)
	_stack = ScreenStack.new()
	_stack.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(_stack)
	_overlay = OverlayLayer.new()
	add_child(_overlay)
	Services.overlay = _overlay
	_boot()


func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_CLOSE_REQUEST:
		Services.shutdown()
		get_tree().quit()


func _boot() -> void:
	if Services.sidecar == null:
		Services.sidecar = SidecarProcess.new()
		add_child(Services.sidecar)
	else:
		Services.sidecar.kill()  # a failed attempt may still be spawning
	if Services.client == null:
		Services.client = EngineClient.new()
		add_child(Services.client)
	_boot_lines = ["REFEREE: WAKING…"]
	# drop only OUR stale connections from a previous attempt (one-shot per
	# signal leaves the unfired one connected — a RETRY would double-fire;
	# a blanket disconnect would also tear down every other listener's hooks)
	for sig: Signal in [Services.sidecar.boot_failed, Services.sidecar.booted]:
		for conn: Dictionary in sig.get_connections():
			var cb: Callable = conn["callable"]
			if cb == Callable(self, "_on_boot_failed") or cb == Callable(self, "_on_booted"):
				sig.disconnect(cb)
	Services.sidecar.boot_failed.connect(_on_boot_failed)
	Services.sidecar.booted.connect(_on_booted)
	Services.sidecar.spawn()


func _on_booted(base_url: String, port: int) -> void:
	Services.client.setup(base_url)
	# record the LISTENING lines before the refresh so a failed attempt and
	# its RETRY tell one coherent story (RETRY resets _boot_lines anyway)
	_boot_lines.append("REFEREE: LISTENING · 127.0.0.1:%d" % port)
	_boot_lines.append("SAVES: OK · DICE STREAMS: PRIMED")
	var contracts: EngineResult = await Services.client.refresh_contracts()
	# a swallowed failure leaves the contract versions at 0 — every later
	# session would trip a false "contract drift" toast with the session
	# already created; fail the boot so RETRY re-runs it instead
	if not contracts.ok:
		_on_boot_failed("contract refresh failed — %s" % contracts.error_message)
		return
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


## The M2 screen set (Tasks 7-10); M3/M4 replace the stubs.
func _register_screens() -> void:
	_stack.register("title", TitleScreen.new())
	_stack.register("settings", SettingsScreen.new())
	_stack.register("chronicles", ChroniclesScreen.new())
	_stack.register("new_journey", NewJourneyScreen.new())
	_stack.register("stub", StubScreen.new())


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
