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
const HEALTH_TIMEOUT_SEC := 10.0

var pid := -1
var port := 0
var base_url := ""
var attached_external := false
var log_path := ""

var _polling := false
var _elapsed := 0.0
var _health_request: HTTPRequest


func spawn(extra_args := PackedStringArray()) -> void:
	var raw_override := OS.get_environment("ANDROMEDA_SIDECAR_URL").strip_edges()
	if raw_override != "":
		var override := raw_override
		if not override.contains("://"):
			override = "http://" + override
		var rest := override.trim_prefix("http://").trim_prefix("https://")
		var host := rest
		var parsed_port := 0
		if rest.contains(":"):
			host = rest.get_slice(":", 0)
			parsed_port = int(rest.get_slice(":", 1))
		if host == "" or parsed_port <= 0:
			boot_failed.emit(
				"ANDROMEDA_SIDECAR_URL must be http://<host>:<port> — got '%s'" % raw_override
			)
			return
		attached_external = true
		base_url = override.rstrip("/")
		port = parsed_port
		_health_check()
		return
	# Exec the venv python DIRECTLY — `uv run` spawns python as a child, so
	# killing the returned pid would orphan the server. With exec, bash is
	# replaced and the returned pid IS the server process.
	var python := _venv_python()
	if python == "":
		boot_failed.emit("no .venv python found — run `uv sync` in the repo first")
		return
	# Per-spawn unique name (ms + random): concurrent runs (live client +
	# test suite) truncate each other's LISTENING line if they share one log
	# file; the random suffix covers two spawns inside the same millisecond.
	_prune_old_logs()
	log_path = OS.get_cache_dir().path_join(
		(
			"andromeda-sidecar-%d-%d.log"
			% [Time.get_unix_time_from_system() * 1000.0, randi() % 100000]
		)
	)
	var log_file := FileAccess.open(log_path, FileAccess.WRITE)
	if log_file != null:
		log_file.store_string("")
		log_file.close()
	var quoted_args := PackedStringArray()
	for arg: String in extra_args:
		quoted_args.append(_sh_quote(arg))
	var cmd := (
		"cd %s && exec %s -m src.server --port 0 %s > %s 2>&1"
		% [
			_sh_quote(Paths.repo_root()),
			_sh_quote(python),
			" ".join(quoted_args),
			_sh_quote(log_path),
		]
	)
	pid = OS.create_process("bash", ["-c", cmd])
	if pid == -1:
		boot_failed.emit("could not spawn bash — is bash on PATH?")
		return
	_polling = true
	_elapsed = 0.0


func kill() -> void:
	if pid > 0 and not attached_external:
		# The spawn execs the venv python, so this pid IS the server.
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
	# HTTPRequest.timeout defaults to 0 (never times out) — a wedged server
	# would hang boot forever. RESULT_TIMEOUT lands in the result != SUCCESS
	# branch of _on_health_completed as a boot_failed.
	_health_request.timeout = HEALTH_TIMEOUT_SEC
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


## Delete sidecar logs older than an hour. Active logs from concurrent runs
## are seconds old, so the threshold never touches them — it only stops
## per-spawn files from accumulating forever in the cache dir.
static func _prune_old_logs() -> void:
	var cache := OS.get_cache_dir()
	var cutoff := Time.get_unix_time_from_system() - 3600.0
	for file: String in DirAccess.get_files_at(cache):
		if not file.begins_with("andromeda-sidecar-") or not file.ends_with(".log"):
			continue
		var path := cache.path_join(file)
		if FileAccess.get_modified_time(path) < cutoff:
			DirAccess.remove_absolute(path)


static func _venv_python() -> String:
	for candidate: String in [".venv/bin/python3", ".venv/bin/python"]:
		var path := Paths.repo_root().path_join(candidate)
		if FileAccess.file_exists(path):
			return path
	return ""
