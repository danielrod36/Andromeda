class_name BeatDirector
extends Node
## The one client-side pipeline (spec §3, M3-C1): every gameplay action runs
## choose → receipts → narrate, so rolls render before prose types and
## choices unlock only when the beat lands. Template degradation needs no
## client branching — the server streams the same block types either way.
##
## State machine: IDLE → CHOOSING → RECEIPTS → NARRATING → IDLE.
## narrate_only() (ceremony, reveal, steered re-tells) enters at NARRATING.
##
## Completion signals: run() ends with beat_finished(new_envelope);
## narrate_only() ends with narration_finished(). Skip closes the pump and
## synthesizes the wire protocol's `done` terminator — the typewriter
## completes its collected text on `done` (C2); no extra block type exists.
##
## Failure contract: a failed step emits beat_failed(code, message) and
## returns to IDLE. A stream failure AFTER a successful choose additionally
## emits beat_finished with the retained envelope — the mechanical outcome
## already happened, so choices must unlock (spec §9: outcomes display even
## when the narrator fails). The 409 `action_in_flight` envelope is an
## ordinary choose failure (code string is the discriminator, not status).

signal beat_finished(session: Dictionary)
signal narration_finished
signal block_received(block_type: String, content: String)
signal receipts_ready(events: Array)
signal beat_failed(error_code: String, message: String)

enum State { IDLE, CHOOSING, RECEIPTS, NARRATING }

const NARRATE_BEAT := "chargen_beat"

## Current pipeline state (State enum) — UI binds enable/disable to this.
var state: int = State.IDLE
## C9 cursor discipline: max(seq) seen from any events source (choose
## responses now; audit fetches in C9). Monotonic; never resets.
var last_seen_seq := 0

var _client: Node
var _pump: Node
var _pump_wired := false
var _envelope := {}
var _session_id := ""
var _narrate_only := false


## Inject the client (EngineClient or a fake with the same surface) and,
## optionally, the pump (StreamPump or a fake). Without a pump a real
## StreamPump is created in _ready. Call once, before or after add_child.
func configure(p_client: Node, p_pump: Node = null) -> void:
	_client = p_client
	if p_pump != null and p_pump != _pump:
		_pump = p_pump
		_wire_pump()


func _ready() -> void:
	if _pump == null:
		_pump = StreamPump.new()
		add_child(_pump)
		_wire_pump()


## The full pipeline for one player choice (or an advisor-applied one).
func run(session_id: String, option_id: String, origin := "player") -> void:
	if not _begin(session_id):
		return
	_narrate_only = false
	state = State.CHOOSING
	var res: EngineResult = await _client.choose(session_id, option_id, origin)
	if not res.ok:
		_fail(res.error_code, res.error_message)
		return
	_envelope = res.data.get("session", {})
	var events: Array = res.data.get("events", [])
	advance_seq(events)
	state = State.RECEIPTS
	receipts_ready.emit(events)
	_start_stream(NARRATE_BEAT, "")


## Ceremony world-intro, reveal close, steered re-tells: narration without a
## choose. Ends with narration_finished() (no envelope changes).
func narrate_only(session_id: String, beat: String, steering := "") -> void:
	if not _begin(session_id):
		return
	_narrate_only = true
	_start_stream(beat, steering)


## Skip the typewriter: close the stream, synthesize `done`, unlock.
func skip() -> void:
	if state != State.NARRATING:
		return
	_pump.stop()
	# Synthesize the wire protocol's terminator — real streams deliver their
	# own `done`; only a skip needs the stand-in (the typewriter completes on it).
	block_received.emit("done", "")
	_complete()


## Fold an events source (choose response now; audit rows in C9) into the
## cursor — max(seq) wins so replays and re-fetches never move it back.
func advance_seq(events: Array) -> void:
	for e: Dictionary in events:
		var seq := int(e.get("seq", 0))
		if seq > last_seen_seq:
			last_seen_seq = seq


func _begin(session_id: String) -> bool:
	if state != State.IDLE:
		_fail("director_busy", "a beat is already in flight for this session")
		return false
	_session_id = session_id
	return true


func _start_stream(beat: String, steering: String) -> void:
	state = State.NARRATING
	_pump.start(_client.base_url, _session_id, beat, steering)


func _wire_pump() -> void:
	if _pump_wired:
		return
	_pump_wired = true
	_pump.block_received.connect(_on_block_received)
	_pump.stream_finished.connect(_on_stream_finished)
	_pump.stream_failed.connect(_on_stream_failed)


func _on_block_received(block_type: String, content: String) -> void:
	block_received.emit(block_type, content)


func _on_stream_finished() -> void:
	_complete()


func _on_stream_failed(message: String) -> void:
	# The stream died mid-narration. beat_failed always fires; when a choose
	# already succeeded the retained envelope still unlocks the stage.
	_fail("narration_failed", message)
	if not _narrate_only:
		_complete()


func _complete() -> void:
	state = State.IDLE
	if _narrate_only:
		narration_finished.emit()
	else:
		beat_finished.emit(_envelope)


func _fail(error_code: String, message: String) -> void:
	state = State.IDLE
	beat_failed.emit(error_code, message)
