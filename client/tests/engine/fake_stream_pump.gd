class_name FakeStreamPump
extends Node
## Test double for StreamPump (M3-C1): same signal surface and start/stop
## shape, scriptable emissions. The suite drives blocks by hand — the real
## pump polls HTTP in _process and is exercised by its own integration suite.

signal block_received(block_type: String, content: String)
signal stream_finished
signal stream_failed(message: String)

var start_calls: Array = []
var stop_count := 0


func start(base_url: String, session_id: String, beat := "scene", steering := "") -> void:
	start_calls.append(
		{"base_url": base_url, "session_id": session_id, "beat": beat, "steering": steering}
	)


func stop() -> void:
	stop_count += 1


## Emit a canned block sequence exactly as the server would (caller includes
## the trailing `done` block), then the terminator signal.
func play_forward(blocks: Array) -> void:
	for b: Dictionary in blocks:
		block_received.emit(str(b["type"]), str(b["content"]))
	stream_finished.emit()


func fail(message: String) -> void:
	stream_failed.emit(message)
