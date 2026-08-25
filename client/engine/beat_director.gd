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
## Concurrency contract: exactly one beat may be in flight. A busy call is
## rejected emit-only (its beat_failed fires but the in-flight beat's state
## is untouched — the rejected call never owned the machine). Every beat
## carries a generation token; completions/failures no-op when stale, so a
## handler reacting to beat_failed by immediately chaining a retry can never
## be corrupted by the failed beat's late bookkeeping.
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
## responses now; audit fetches in C9). Monotonic within a session; resets
## when the director switches session ids (a stale cursor would skip rows).
var last_seen_seq := 0

var _client: Node
var _pump: Node
var _pump_wired := false
var _envelope := {}
var _session_id := ""
var _narrate_only := false
## Beat-generation token: bumped by every started beat. Completions carry
## their beat's token and no-op when stale.
var _generation := 0
## The generation whose stream the pump is running; -1 = none. Late pump
## signals after a completed/superseded beat are dropped on it.
var _stream_gen := -1


## Inject the client (EngineClient or a fake with the same surface) and,
## optionally, the pump (StreamPump or a fake). Without a pump a real
## StreamPump is created in _ready. Re-configuring with a different pump
## rewires the signal connections (the retired pump is disconnected).
## Rejected while a beat is in flight: a mid-beat swap would orphan the
## streaming beat (its pump's signals unobservable → NARRATING forever).
## Configure between beats.
func configure(p_client: Node, p_pump: Node = null) -> void:
	if state != State.IDLE and (p_pump != null and p_pump != _pump):
		beat_failed.emit("director_busy", "cannot swap the stream pump while a beat is in flight")
		return
	_client = p_client
	if p_pump != null and p_pump != _pump:
		_unwire_pump()
		_pump = p_pump
		_wire_pump()


func _ready() -> void:
	if _pump == null:
		_pump = StreamPump.new()
		add_child(_pump)
		_wire_pump()


## The full pipeline for one player choice (or an advisor-applied one).
func run(session_id: String, option_id: String, origin := "player") -> void:
	var gen := _begin(session_id)
	if gen < 0:
		return
	_narrate_only = false
	state = State.CHOOSING
	var res: EngineResult = await _client.choose(session_id, option_id, origin)
	if gen != _generation:
		return  # superseded mid-choose — drop silently
	if not res.ok:
		_fail(gen, res.error_code, res.error_message)
		return
	_envelope = res.data.get("session", {})
	var events: Array = res.data.get("events", [])
	advance_seq(events)
	state = State.RECEIPTS
	receipts_ready.emit(events)
	_start_stream(gen, NARRATE_BEAT, "")


## Ceremony world-intro, reveal close, steered re-tells: narration without a
## choose. Ends with narration_finished() (no envelope changes).
func narrate_only(session_id: String, beat: String, steering := "") -> void:
	var gen := _begin(session_id)
	if gen < 0:
		return
	_narrate_only = true
	_start_stream(gen, beat, steering)


## Skip the typewriter: close the stream, synthesize `done`, unlock.
func skip() -> void:
	if state != State.NARRATING:
		return
	_pump.stop()
	# Synthesize the wire protocol's terminator — real streams deliver their
	# own `done`; only a skip needs the stand-in (the typewriter completes on it).
	block_received.emit("done", "")
	_complete(_generation)


## Fold an events source (choose response now; audit rows in C9) into the
## cursor — max(seq) wins so replays and re-fetches never move it back.
func advance_seq(events: Array) -> void:
	for e: Dictionary in events:
		var seq := int(e.get("seq", 0))
		if seq > last_seen_seq:
			last_seen_seq = seq


## Begin a beat: returns its generation token, or -1 when busy (emit-only
## rejection — the in-flight beat keeps its state and its completions).
func _begin(session_id: String) -> int:
	if state != State.IDLE:
		beat_failed.emit("director_busy", "a beat is already in flight for this session")
		return -1
	if session_id != _session_id:
		# Session switch: reset the audit cursor — the old session's max seq
		# bears no relation to the new log (C9's since= fetch would skip rows).
		_session_id = session_id
		last_seen_seq = 0
	_generation += 1
	return _generation


func _start_stream(gen: int, beat: String, steering: String) -> void:
	state = State.NARRATING
	_stream_gen = gen
	_pump.start(_client.base_url, _session_id, beat, steering)


func _wire_pump() -> void:
	if _pump_wired or _pump == null:
		return
	_pump_wired = true
	_pump.block_received.connect(_on_block_received)
	_pump.stream_finished.connect(_on_stream_finished)
	_pump.stream_failed.connect(_on_stream_failed)


func _unwire_pump() -> void:
	if not _pump_wired or _pump == null:
		return
	_pump_wired = false
	_pump.block_received.disconnect(_on_block_received)
	_pump.stream_finished.disconnect(_on_stream_finished)
	_pump.stream_failed.disconnect(_on_stream_failed)


func _on_block_received(block_type: String, content: String) -> void:
	block_received.emit(block_type, content)


func _on_stream_finished() -> void:
	_complete(_stream_gen)


func _on_stream_failed(message: String) -> void:
	var gen := _stream_gen
	if gen < 0 or gen != _generation:
		return  # late/superseded pump signal — its beat already ended
	# The stream died mid-narration. beat_failed always fires; when a choose
	# already succeeded the retained envelope still unlocks the stage. Both
	# carry this beat's token — a handler that chains a new beat inside
	# beat_failed bumps the generation and the late _complete no-ops.
	_fail(gen, "narration_failed", message)
	if not _narrate_only:
		_complete(gen)


func _complete(gen: int) -> void:
	if gen < 0 or gen != _generation:
		return  # stale completion — the machine belongs to a newer beat
	_stream_gen = -1
	state = State.IDLE
	if _narrate_only:
		narration_finished.emit()
	else:
		beat_finished.emit(_envelope)


func _fail(gen: int, error_code: String, message: String) -> void:
	if gen != _generation:
		return  # stale failure — drop
	if _stream_gen == gen:
		_stream_gen = -1
	state = State.IDLE
	beat_failed.emit(error_code, message)
