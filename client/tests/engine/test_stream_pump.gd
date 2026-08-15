extends GdUnitTestSuite
## StreamPump integration: a real world_intro beat over NDJSON (§A4).
## The server runs unconfigured → template narration — same block types.

var _sidecar: SidecarProcess
var _client: EngineClient


func before() -> void:
	# Isolated settings/saves: the dev machine may have a real LLM key stored
	# — tests must never use it (live calls + credits) and never touch real
	# saves. Template narration is the deterministic contract (§A4).
	var iso := OS.get_cache_dir().path_join(
		"andromeda-m2-pump-%d" % int(Time.get_unix_time_from_system() * 1000.0)
	)
	DirAccess.make_dir_recursive_absolute(iso.path_join("settings"))
	DirAccess.make_dir_recursive_absolute(iso.path_join("saves"))
	_sidecar = SidecarProcess.new()
	add_child(_sidecar)
	var outcome := {"ok": false}
	_sidecar.booted.connect(func(_url: String, _p: int) -> void: outcome["ok"] = true)
	_sidecar.spawn(
		PackedStringArray(
			["--settings-dir", iso.path_join("settings"), "--saves-dir", iso.path_join("saves")]
		)
	)
	var waited := 0.0
	while not outcome["ok"] and waited < 20.0:
		await get_tree().create_timer(0.1).timeout
		waited += 0.1
	if not outcome["ok"]:
		push_error("sidecar failed to boot")
	_client = EngineClient.new()
	add_child(_client)
	_client.setup(_sidecar.base_url)


func after() -> void:
	_sidecar.kill()


func _new_session() -> Dictionary:
	var name := "m2-pump-%d" % int(Time.get_unix_time_from_system() * 1000.0)
	var created: EngineResult = await _client.create_session(
		{"kind": "chargen", "name": name, "seed": 99, "pack_id": "scifi"}
	)
	return created.data["session"]


func _cleanup(session_id: String, save_name: String) -> void:
	await _client.delete_session(session_id)
	await _client.delete_save(save_name)


func test_world_intro_streams_the_block_sequence() -> void:
	var session := await _new_session()
	var pump: StreamPump = auto_free(StreamPump.new())
	add_child(pump)
	var blocks: Array = []
	var state := {"finished": false, "failed": ""}
	pump.block_received.connect(func(t: String, c: String) -> void: blocks.append([t, c]))
	pump.stream_finished.connect(func() -> void: state["finished"] = true)
	pump.stream_failed.connect(func(msg: String) -> void: state["failed"] = msg)
	pump.start(_sidecar.base_url, session["id"], "world_intro")
	var waited := 0.0
	while not state["finished"] and state["failed"] == "" and waited < 30.0:
		await get_tree().create_timer(0.1).timeout
		waited += 0.1
	assert_str(state["failed"]).is_empty()
	assert_bool(state["finished"]).is_true()
	# §A4: ≥1 narration, types only from BLOCK_TYPES, exactly one done, last.
	assert_bool(blocks.size() >= 2).is_true()
	var types := blocks.map(func(b: Array) -> String: return b[0])
	for t: String in types:
		assert_bool(t in StreamPump.BLOCK_TYPES).is_true()
	assert_str(types[0]).is_equal("narration")
	assert_str(types[-1]).is_equal("done")
	assert_that(types.count("done")).is_equal(1)
	for b: Array in blocks:
		if b[0] == "narration":
			assert_str(b[1]).is_not_empty()
		if b[0] == "badge":
			(
				assert_bool(
					(
						b[1]
						in [
							"narration unavailable — showing mechanical outcomes",
							"connection lost — template narration",
						]
					)
				)
				. is_true()
			)
	await _cleanup(session["id"], session["name"])


func test_stop_is_silent() -> void:
	# Close-on-skip contract: stop() closes the stream without emitting
	# stream_finished and emits nothing afterward. (Template-mode streams
	# complete in a few frames, so "mid-stream" isn't reproducible here —
	# stopping before the first block is the deterministic check.)
	var session := await _new_session()
	var pump: StreamPump = auto_free(StreamPump.new())
	add_child(pump)
	var blocks: Array = []
	var finished := {"called": false}
	var failed := {"message": ""}
	pump.block_received.connect(func(t: String, _c: String) -> void: blocks.append(t))
	pump.stream_finished.connect(func() -> void: finished["called"] = true)
	pump.stream_failed.connect(func(msg: String) -> void: failed["message"] = msg)
	pump.start(_sidecar.base_url, session["id"], "world_intro")
	pump.stop()
	await get_tree().create_timer(0.5).timeout
	assert_that(blocks).is_empty()
	assert_bool(finished["called"]).is_false()
	assert_str(failed["message"]).is_empty()
	await _cleanup(session["id"], session["name"])


func test_unknown_session_fails_with_engine_message() -> void:
	var pump: StreamPump = auto_free(StreamPump.new())
	add_child(pump)
	var state := {"failed": ""}
	pump.stream_failed.connect(func(msg: String) -> void: state["failed"] = msg)
	pump.start(_sidecar.base_url, "no-such-session", "world_intro")
	var waited := 0.0
	while state["failed"] == "" and waited < 15.0:
		await get_tree().create_timer(0.1).timeout
		waited += 0.1
	assert_str(state["failed"]).is_not_empty()
