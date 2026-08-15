class_name StreamPump
extends Node
## NDJSON narration stream reader (§A4) on the low-level HTTPClient —
## HTTPRequest buffers whole bodies and cannot stream. Polls in _process;
## no threads.
##
## Wire format: one JSON object per line, {"type": ..., "content": ...};
## block types are exactly narration | change | badge | done; `done` is
## always last; the server closes the body after it (routes_sessions.py:387-394).
## Pre-stream errors (e.g. 404 session_not_found) arrive as the HTTP error
## envelope (§A1) — surfaced via stream_failed with the engine's message
## verbatim.

signal block_received(block_type: String, content: String)
signal stream_finished
signal stream_failed(message: String)

enum State { IDLE, CONNECTING, REQUESTING, READING_BODY }

const BLOCK_TYPES := ["narration", "change", "badge", "done"]
## CONNECTING/REQUESTING/READING_BODY can each hang indefinitely on a wedged
## connection. This is an INACTIVITY deadline: every delivered chunk resets
## it, so a healthy stream running long (LLM retries in one request) is
## never cut — only a connection silent for 180s fails.
const STREAM_TIMEOUT_SEC := 180.0
const _TRANSPORT_MESSAGE := "could not reach the referee — is the sidecar running?"

var _http := HTTPClient.new()
var _state: int = State.IDLE
var _buffer := PackedByteArray()
var _resp_code := 0
var _path := ""
var _body := ""
var _stream_elapsed := 0.0


func start(base_url: String, session_id: String, beat := "scene", steering := "") -> void:
	stop()
	_stream_elapsed = 0.0
	var rest := base_url.trim_prefix("http://").trim_prefix("https://")
	var host := rest
	var p := 80
	if rest.contains(":"):
		host = rest.get_slice(":", 0)
		p = int(rest.get_slice(":", 1))
	var err := _http.connect_to_host(host, p)
	if err != OK:
		stream_failed.emit(_TRANSPORT_MESSAGE)
		return
	_path = "/v1/sessions/%s/narrate" % session_id.uri_encode()
	_body = JSON.stringify({"beat": beat, "steering": steering})
	_resp_code = 0
	_state = State.CONNECTING


## Close-on-skip: closes the connection without emitting stream_finished.
func stop() -> void:
	if _state != State.IDLE:
		_http.close()
	_state = State.IDLE
	_buffer = PackedByteArray()


func _exit_tree() -> void:
	stop()


func _process(delta: float) -> void:
	if _state == State.IDLE:
		return
	_stream_elapsed += delta
	if _stream_elapsed >= STREAM_TIMEOUT_SEC:
		_fail_transport()
		return
	_http.poll()
	match _state:
		State.CONNECTING:
			match _http.get_status():
				HTTPClient.STATUS_CONNECTED:
					_send_request()
				HTTPClient.STATUS_CANT_CONNECT, HTTPClient.STATUS_CONNECTION_ERROR:
					_fail_transport()
		State.REQUESTING:
			match _http.get_status():
				HTTPClient.STATUS_BODY:
					_resp_code = _http.get_response_code()
					_state = State.READING_BODY
					_read_chunks()
				HTTPClient.STATUS_CONNECTION_ERROR, HTTPClient.STATUS_CANT_CONNECT:
					_fail_transport()
		State.READING_BODY:
			_read_chunks()


func _send_request() -> void:
	var headers := PackedStringArray(["Content-Type: application/json"])
	var err := _http.request(HTTPClient.METHOD_POST, _path, headers, _body)
	if err != OK:
		_fail_transport()
		return
	_state = State.REQUESTING


func _read_chunks() -> void:
	while _http.get_status() == HTTPClient.STATUS_BODY and _state == State.READING_BODY:
		var chunk := _http.read_response_body_chunk()
		if chunk.size() == 0:
			break
		_stream_elapsed = 0.0  # data flowed — the stream is alive
		_buffer.append_array(chunk)
		_drain_lines()
	if _state != State.READING_BODY:
		return  # done-block already finished the stream
	match _http.get_status():
		HTTPClient.STATUS_DISCONNECTED, HTTPClient.STATUS_CONNECTED:
			# The body is over (server closed, or keep-alive left the socket
			# open). Without a `done` block this is abnormal (200) or an error
			# envelope (non-200) — don't wait for a TCP close that may only
			# come at the server's keep-alive timeout.
			if _resp_code == 200:
				_drain_lines(true)
				_state = State.IDLE
				_http.close()
				stream_finished.emit()
			else:
				_fail_with_envelope()
		HTTPClient.STATUS_CONNECTION_ERROR:
			_fail_transport()


## Split the byte buffer on \n (byte 10). Byte-level framing is the pin:
## a chunk boundary can fall inside a UTF-8 multibyte character, and decoding
## a partial sequence corrupts it — \n never appears inside a multibyte
## sequence, so splitting bytes first is safe.
func _drain_lines(flush_partial := false) -> void:
	while true:
		var idx := -1
		for i: int in _buffer.size():
			if _buffer[i] == 10:  # '\n'
				idx = i
				break
		if idx == -1:
			break
		var line := _buffer.slice(0, idx).get_string_from_utf8()
		_buffer = _buffer.slice(idx + 1)
		_emit_line(line)
	if flush_partial and not _buffer.is_empty():
		_emit_line(_buffer.get_string_from_utf8())
		_buffer = PackedByteArray()


func _emit_line(line: String) -> void:
	var stripped := line.strip_edges()
	if stripped == "":
		return
	var parsed: Variant = JSON.parse_string(stripped)
	if not (parsed is Dictionary):
		return  # malformed line — skip; the stream continues
	var block_type := str(parsed.get("type", ""))
	var content := str(parsed.get("content", ""))
	if block_type in BLOCK_TYPES:
		block_received.emit(block_type, content)
		if block_type == "done":
			# `done` is the protocol terminator (§A4) — finish on it, not on
			# TCP teardown. HTTP/1.1 keep-alive keeps the socket open after
			# the body; waiting for a close that only comes at the server's
			# keep-alive timeout would stall the stream ~5s and read as a
			# connection error.
			_finish()


func _finish() -> void:
	_http.close()
	_state = State.IDLE
	_buffer = PackedByteArray()
	stream_finished.emit()


func _fail_transport() -> void:
	_http.close()
	_state = State.IDLE
	stream_failed.emit(_TRANSPORT_MESSAGE)


## Non-200 before/at the stream: the body is the §A1 error envelope.
func _fail_with_envelope() -> void:
	var text := _buffer.get_string_from_utf8()
	_buffer = PackedByteArray()
	_http.close()
	_state = State.IDLE
	var message := "the referee answered with something unreadable"
	var parsed: Variant = JSON.parse_string(text)
	# guard the VALUE type: a non-Andromeda server can answer with
	# {"error": "<string>"} — untyped access would raise here
	if parsed is Dictionary and parsed.get("error") is Dictionary:
		message = str(parsed["error"].get("message", message))
	stream_failed.emit(message)
