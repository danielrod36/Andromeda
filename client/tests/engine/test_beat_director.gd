extends GdUnitTestSuite
## BeatDirector state machine (M3-C1): choose → receipts → narrate → unlock,
## skip, narrate_only, and the failure contract (409 action_in_flight, 422
## invalid_choice, stream loss after a successful choose).


func _make_director(fake_client: FakeEngineClient, fake_pump: FakeStreamPump) -> BeatDirector:
	var director: BeatDirector = auto_free(BeatDirector.new())
	director.configure(fake_client, fake_pump)
	add_child(director)
	return director


func _client_with_choose(result: EngineResult) -> FakeEngineClient:
	var fake_client: FakeEngineClient = auto_free(FakeEngineClient.new())
	fake_client.responses["choose"] = result
	return fake_client


func _ok_choose(events: Array, phase := "run_survival") -> EngineResult:
	var session := {
		"id": "abc123",
		"name": "Mara Voss",
		"kind": "chargen",
		"phase": phase,
		"view": {},
		"contract_version": 1,
		"seed": 42,
		"death_mode": "narrative",
	}
	return FakeEngineClient.ok({"session": session, "result": {}, "events": events})


func _blocks() -> Array:
	return [
		{"type": "narration", "content": "The beacons lied."},
		{"type": "change", "content": "END +1"},
		{"type": "done", "content": ""},
	]


func test_run_forwards_receipts_blocks_and_new_envelope() -> void:
	var fake_client := _client_with_choose(
		_ok_choose([{"seq": 5, "kind": "roll"}, {"seq": 6, "kind": "state_change"}])
	)
	var fake_pump: FakeStreamPump = auto_free(FakeStreamPump.new())
	add_child(fake_pump)
	var director := _make_director(fake_client, fake_pump)

	var finished: Array = []
	var blocks: Array = []
	var receipts: Array = []
	var failures: Array = []
	director.beat_finished.connect(func(s: Dictionary) -> void: finished.append(s))
	director.block_received.connect(func(t: String, c: String) -> void: blocks.append([t, c]))
	director.receipts_ready.connect(func(e: Array) -> void: receipts.append(e))
	director.beat_failed.connect(func(c: String, m: String) -> void: failures.append([c, m]))

	director.run("abc123", "roll_pool")
	await get_tree().create_timer(0.05).timeout

	assert_that(fake_pump.start_calls).has_size(1)
	assert_str(fake_pump.start_calls[0]["beat"]).is_equal("chargen_beat")
	assert_str(fake_pump.start_calls[0]["session_id"]).is_equal("abc123")
	assert_str(fake_pump.start_calls[0]["steering"]).is_equal("")

	fake_pump.play_forward(_blocks())

	assert_that(blocks).has_size(3)
	assert_str(blocks[0][0]).is_equal("narration")
	assert_str(blocks[1][0]).is_equal("change")
	assert_str(blocks[2][0]).is_equal("done")
	assert_that(receipts).has_size(1)
	assert_that(receipts[0]).has_size(2)  # both choose events forwarded
	assert_that(finished).has_size(1)
	assert_str(finished[0]["phase"]).is_equal("run_survival")
	assert_int(director.state).is_equal(BeatDirector.State.IDLE)
	assert_int(director.last_seen_seq).is_equal(6)
	assert_that(failures).is_empty()
	assert_that(fake_client.calls).has_size(1)
	assert_str(fake_client.calls[0][0]).is_equal("choose")


func test_skip_closes_stream_and_synthesizes_done() -> void:
	var fake_client := _client_with_choose(_ok_choose([]))
	var fake_pump: FakeStreamPump = auto_free(FakeStreamPump.new())
	add_child(fake_pump)
	var director := _make_director(fake_client, fake_pump)

	var blocks: Array = []
	var finished: Array = []
	director.block_received.connect(func(t: String, c: String) -> void: blocks.append([t, c]))
	director.beat_finished.connect(func(s: Dictionary) -> void: finished.append(s))

	director.run("abc123", "roll_pool")
	await get_tree().create_timer(0.05).timeout
	# Mid-stream: emit a narration block WITHOUT the terminator (play_forward
	# would finish the stream and complete the beat before skip() runs).
	fake_pump.block_received.emit("narration", "The beacons")

	director.skip()

	assert_int(fake_pump.stop_count).is_equal(1)
	assert_that(blocks).has_size(2)
	assert_str(blocks[1][0]).is_equal("done")  # synthesized terminator
	assert_that(finished).has_size(1)
	assert_int(director.state).is_equal(BeatDirector.State.IDLE)


func test_stream_failure_after_choose_retains_envelope_and_unlocks() -> void:
	var fake_client := _client_with_choose(_ok_choose([]))
	var fake_pump: FakeStreamPump = auto_free(FakeStreamPump.new())
	add_child(fake_pump)
	var director := _make_director(fake_client, fake_pump)

	var finished: Array = []
	var failures: Array = []
	director.beat_finished.connect(func(s: Dictionary) -> void: finished.append(s))
	director.beat_failed.connect(func(c: String, m: String) -> void: failures.append([c, m]))

	director.run("abc123", "roll_pool")
	await get_tree().create_timer(0.05).timeout
	fake_pump.fail("could not reach the referee")

	assert_that(failures).has_size(1)
	assert_str(failures[0][0]).is_equal("narration_failed")
	assert_str(failures[0][1]).is_equal("could not reach the referee")
	# The mechanical outcome already happened — the envelope unlocks choices.
	assert_that(finished).has_size(1)
	assert_str(finished[0]["phase"]).is_equal("run_survival")
	assert_int(director.state).is_equal(BeatDirector.State.IDLE)


func test_409_action_in_flight_fails_without_narrating() -> void:
	var fake_client := _client_with_choose(
		FakeEngineClient.err(409, "action_in_flight", "A beat is already in flight")
	)
	var fake_pump: FakeStreamPump = auto_free(FakeStreamPump.new())
	add_child(fake_pump)
	var director := _make_director(fake_client, fake_pump)

	var finished: Array = []
	var failures: Array = []
	director.beat_finished.connect(func(s: Dictionary) -> void: finished.append(s))
	director.beat_failed.connect(func(c: String, m: String) -> void: failures.append([c, m]))

	director.run("abc123", "roll_pool")
	await get_tree().create_timer(0.05).timeout

	assert_that(failures).has_size(1)
	assert_str(failures[0][0]).is_equal("action_in_flight")
	assert_that(finished).is_empty()  # no envelope — nothing to unlock
	assert_that(fake_pump.start_calls).is_empty()
	assert_int(director.state).is_equal(BeatDirector.State.IDLE)


func test_422_invalid_choice_fails_to_idle() -> void:
	var fake_client := _client_with_choose(
		FakeEngineClient.err(422, "invalid_choice", "Invalid option: nope")
	)
	var fake_pump: FakeStreamPump = auto_free(FakeStreamPump.new())
	add_child(fake_pump)
	var director := _make_director(fake_client, fake_pump)

	var failures: Array = []
	director.beat_failed.connect(func(c: String, m: String) -> void: failures.append([c, m]))

	director.run("abc123", "nope")
	await get_tree().create_timer(0.05).timeout

	assert_that(failures).has_size(1)
	assert_str(failures[0][0]).is_equal("invalid_choice")
	assert_that(fake_pump.start_calls).is_empty()
	assert_int(director.state).is_equal(BeatDirector.State.IDLE)


func test_narrate_only_streams_without_choose() -> void:
	var fake_client: FakeEngineClient = auto_free(FakeEngineClient.new())
	var fake_pump: FakeStreamPump = auto_free(FakeStreamPump.new())
	add_child(fake_pump)
	var director := _make_director(fake_client, fake_pump)

	var narrated := {"called": false}
	var beat_ended: Array = []
	director.narration_finished.connect(func() -> void: narrated["called"] = true)
	director.beat_finished.connect(func(s: Dictionary) -> void: beat_ended.append(s))

	director.narrate_only("abc123", "world_intro", "lean into the loneliness")
	await get_tree().create_timer(0.05).timeout

	assert_that(fake_pump.start_calls).has_size(1)
	assert_str(fake_pump.start_calls[0]["beat"]).is_equal("world_intro")
	assert_str(fake_pump.start_calls[0]["steering"]).is_equal("lean into the loneliness")
	assert_that(fake_client.calls).is_empty()  # narration never chooses

	fake_pump.play_forward(_blocks())
	assert_bool(narrated["called"]).is_true()
	assert_that(beat_ended).is_empty()  # narrate-only never emits beat_finished
	assert_int(director.state).is_equal(BeatDirector.State.IDLE)


func test_narrate_only_failure_does_not_emit_envelope() -> void:
	var fake_client: FakeEngineClient = auto_free(FakeEngineClient.new())
	var fake_pump: FakeStreamPump = auto_free(FakeStreamPump.new())
	add_child(fake_pump)
	var director := _make_director(fake_client, fake_pump)

	var narrated := {"called": false}
	var failures: Array = []
	director.narration_finished.connect(func() -> void: narrated["called"] = true)
	director.beat_failed.connect(func(c: String, m: String) -> void: failures.append([c, m]))

	director.narrate_only("abc123", "world_intro")
	await get_tree().create_timer(0.05).timeout
	fake_pump.fail("could not reach the referee")

	assert_that(failures).has_size(1)
	assert_str(failures[0][0]).is_equal("narration_failed")
	assert_bool(narrated["called"]).is_false()
	assert_int(director.state).is_equal(BeatDirector.State.IDLE)


func test_busy_director_rejects_a_second_beat() -> void:
	var fake_client: FakeEngineClient = auto_free(FakeEngineClient.new())
	var fake_pump: FakeStreamPump = auto_free(FakeStreamPump.new())
	add_child(fake_pump)
	var director := _make_director(fake_client, fake_pump)

	director.narrate_only("abc123", "world_intro")  # occupies NARRATING
	await get_tree().create_timer(0.05).timeout
	assert_int(director.state).is_equal(BeatDirector.State.NARRATING)

	var failures: Array = []
	director.beat_failed.connect(func(c: String, m: String) -> void: failures.append([c, m]))
	director.run("abc123", "roll_pool")
	await get_tree().create_timer(0.05).timeout

	assert_that(failures).has_size(1)
	assert_str(failures[0][0]).is_equal("director_busy")
	assert_that(fake_client.calls).is_empty()
	assert_that(fake_pump.start_calls).has_size(1)  # only the first beat started
	# The rejection is emit-only: the in-flight beat keeps its state and
	# still completes normally afterwards.
	assert_int(director.state).is_equal(BeatDirector.State.NARRATING)
	var narrated := {"called": false}
	director.narration_finished.connect(func() -> void: narrated["called"] = true)
	fake_pump.play_forward(_blocks())
	assert_bool(narrated["called"]).is_true()
	assert_int(director.state).is_equal(BeatDirector.State.IDLE)


func test_configure_pump_swap_rewires_signals() -> void:
	var fake_client := _client_with_choose(_ok_choose([]))
	var pump_a: FakeStreamPump = auto_free(FakeStreamPump.new())
	add_child(pump_a)
	var director := _make_director(fake_client, pump_a)
	var pump_b: FakeStreamPump = auto_free(FakeStreamPump.new())
	add_child(pump_b)

	director.configure(fake_client, pump_b)
	var finished: Array = []
	var blocks: Array = []
	director.beat_finished.connect(func(s: Dictionary) -> void: finished.append(s))
	director.block_received.connect(func(t: String, c: String) -> void: blocks.append(t))

	director.run("abc123", "roll_pool")
	await get_tree().create_timer(0.05).timeout
	assert_that(pump_b.start_calls).has_size(1)
	pump_b.play_forward(_blocks())
	assert_that(finished).has_size(1)

	# The retired pump is disconnected — its late signals are ignored.
	pump_a.play_forward(_blocks())
	assert_that(finished).has_size(1)
	assert_that(blocks).has_size(3)


func test_failed_stream_handler_can_chain_a_retry_beat_safely() -> void:
	# Kilo PR#46 re-entrancy: a beat_failed handler that immediately chains
	# a new beat must not be corrupted by the failed beat's late completion.
	var fake_client: FakeEngineClient = auto_free(FakeEngineClient.new())
	fake_client.responses["choose"] = [
		_ok_choose([], "run_survival"), _ok_choose([], "choose_skills")
	]
	var fake_pump: FakeStreamPump = auto_free(FakeStreamPump.new())
	add_child(fake_pump)
	var director := _make_director(fake_client, fake_pump)

	var finished: Array = []
	director.beat_finished.connect(func(s: Dictionary) -> void: finished.append(s))
	director.beat_failed.connect(
		func(code: String, _m: String) -> void:
			if code == "narration_failed":
				director.run("abc123", "roll_pool")
	)

	director.run("abc123", "roll_pool")
	await get_tree().create_timer(0.05).timeout
	fake_pump.fail("could not reach the referee")
	# The handler chained retry #2 inside beat_failed; its stream is current.
	assert_that(fake_client.calls).has_size(2)
	assert_that(fake_pump.start_calls).has_size(2)
	assert_int(director.state).is_equal(BeatDirector.State.NARRATING)

	fake_pump.play_forward(_blocks())
	assert_that(finished).has_size(1)  # exactly once, with the retry's envelope
	assert_str(finished[0]["phase"]).is_equal("choose_skills")
	assert_int(director.state).is_equal(BeatDirector.State.IDLE)


func test_mid_beat_pump_swap_is_rejected() -> void:
	# Kilo PR#46 follow-up: swapping the pump while a beat streams would
	# orphan it (signals unobservable → NARRATING forever). The swap is
	# rejected; the in-flight beat keeps its pump and completes normally.
	var fake_client := _client_with_choose(_ok_choose([]))
	var pump_a: FakeStreamPump = auto_free(FakeStreamPump.new())
	add_child(pump_a)
	var director := _make_director(fake_client, pump_a)

	director.run("abc123", "roll_pool")
	await get_tree().create_timer(0.05).timeout
	assert_int(director.state).is_equal(BeatDirector.State.NARRATING)

	var pump_b: FakeStreamPump = auto_free(FakeStreamPump.new())
	add_child(pump_b)
	var failures: Array = []
	var finished: Array = []
	director.beat_failed.connect(func(c: String, _m: String) -> void: failures.append(c))
	director.beat_finished.connect(func(s: Dictionary) -> void: finished.append(s))

	director.configure(fake_client, pump_b)
	assert_that(failures).has_size(1)
	assert_str(failures[0]).is_equal("director_busy")
	assert_that(pump_b.start_calls).is_empty()
	assert_int(director.state).is_equal(BeatDirector.State.NARRATING)

	fake_client.responses["choose"] = _ok_choose([])
	pump_a.play_forward(_blocks())  # the original pump still owns the beat
	assert_that(finished).has_size(1)
	assert_int(director.state).is_equal(BeatDirector.State.IDLE)


func test_cursor_resets_on_session_change() -> void:
	var fake_client: FakeEngineClient = auto_free(FakeEngineClient.new())
	var fake_pump: FakeStreamPump = auto_free(FakeStreamPump.new())
	add_child(fake_pump)
	var director := _make_director(fake_client, fake_pump)

	director.narrate_only("session-a", "world_intro")
	await get_tree().create_timer(0.05).timeout
	director.advance_seq([{"seq": 50}])
	assert_int(director.last_seen_seq).is_equal(50)
	fake_pump.play_forward(_blocks())

	director.narrate_only("session-b", "world_intro")
	await get_tree().create_timer(0.05).timeout
	assert_int(director.last_seen_seq).is_equal(0)  # old session's cursor is meaningless
	fake_pump.play_forward(_blocks())
	director.advance_seq([{"seq": 2}])
	assert_int(director.last_seen_seq).is_equal(2)


func test_advance_seq_never_regresses() -> void:
	var fake_client: FakeEngineClient = auto_free(FakeEngineClient.new())
	var fake_pump: FakeStreamPump = auto_free(FakeStreamPump.new())
	add_child(fake_pump)
	var director := _make_director(fake_client, fake_pump)

	director.advance_seq([{"seq": 10}, {"seq": 7}])
	assert_int(director.last_seen_seq).is_equal(10)
	director.advance_seq([{"seq": 3}])  # replayed rows must not move it back
	assert_int(director.last_seen_seq).is_equal(10)
