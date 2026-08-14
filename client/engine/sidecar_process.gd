class_name SidecarProcess
extends Node
## Owns the Python sidecar lifecycle (spec §4).
##
## Spawn: `bash -c "cd <repo> && exec uv run python -m src.server --port 0
## > <log> 2>&1"` — the `exec` keeps the returned PID pointed at the server,
## and the log redirect avoids Godot's unmaintained stdio-pipe path (parent
## spec D2). Boot completes when the log prints `LISTENING <port>` and a
## GET /health returns {"status": "ok"} (§A2).
##
## Dev override: ANDROMEDA_SIDECAR_URL=http://127.0.0.1:<port> attaches to an
## already-running server instead of spawning (screen iteration without
## respawn). The server self-exits after 5 idle minutes, so a crashed client
## never leaves a permanent orphan.

signal booted(base_url: String, port: int)
signal boot_failed(reason: String)

const BOOT_TIMEOUT_SEC := 15.0

var pid := -1
var port := 0
var base_url := ""
var attached_external := false
var log_path := ""

var _polling := false
var _elapsed := 0.0
var _health_request: HTTPRequest


func spawn() -> void:
	var override := OS.get_environment("ANDROMEDA_SIDECAR_URL").strip_edges()
	if override != "":
		attached_external = true
		base_url = override.rstrip("/")
		port = int(base_url.get_slice(":", base_url.get_slice_count(":") - 1))
		_health_check()
		return
	log_path = OS.get_cache_dir().path_join("andromeda-sidecar.log")
	var log_file := FileAccess.open(log_path, FileAccess.WRITE)
	if log_file != null:
		log_file.store_string("")
		log_file.close()
	var cmd := (
		"cd %s && exec uv run python -m src.server --port 0 > %s 2>&1"
		% [_sh_quote(Paths.repo_root()), _sh_quote(log_path)]
	)
	pid = OS.create_process("bash", ["-c", cmd])
	if pid == -1:
		boot_failed.emit("could not spawn bash — is bash on PATH?")
		return
	_polling = true
	_elapsed = 0.0


func kill() -> void:
	if pid > 0 and not attached_external:
		OS.kill(pid)
	pid = -1


func _exit_tree() -> void:
	kill()


func _process(delta: float) -> void:
	if not _polling:
		return
	_elapsed += delta
	if _elapsed >= BOOT_TIMEOUT_SEC:
		_polling = false
		kill()
		boot_failed.emit(
			"sidecar did not print LISTENING within %ds — see %s" % [BOOT_TIMEOUT_SEC, log_path]
		)
		return
	if not FileAccess.file_exists(log_path):
		return
	var f := FileAccess.open(log_path, FileAccess.READ)
	if f == null:
		return
	var text := f.get_as_text()
	f.close()
	for line: String in text.split("\n"):
		if line.begins_with("LISTENING "):
			var parsed_port := int(line.trim_prefix("LISTENING ").strip_edges())
			if parsed_port > 0:
				port = parsed_port
				base_url = "http://127.0.0.1:%d" % port
				_polling = false
				_health_check()
			return


func _health_check() -> void:
	_health_request = HTTPRequest.new()
	add_child(_health_request)
	_health_request.request_completed.connect(_on_health_completed)
	var err := _health_request.request(base_url + "/health")
	if err != OK:
		_health_request.queue_free()
		boot_failed.emit("health request failed to start: %s" % error_string(err))


func _on_health_completed(
	result: int, code: int, _headers: PackedStringArray, body: PackedByteArray
) -> void:
	_health_request.queue_free()
	if result != HTTPRequest.RESULT_SUCCESS or code != 200:
		boot_failed.emit(
			"health check failed (HTTP %d) at %s — is the sidecar up?" % [code, base_url]
		)
		return
	var parsed: Variant = JSON.parse_string(body.get_string_from_utf8())
	if not (parsed is Dictionary) or parsed.get("status") != "ok":
		boot_failed.emit("health check returned an unexpected body at %s" % base_url)
		return
	booted.emit(base_url, port)


static func _sh_quote(s: String) -> String:
	return "'" + s.replace("'", "'\\''") + "'"
