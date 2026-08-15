extends GdUnitTestSuite
## Integration: boot the real Python sidecar end-to-end (spec §4).
## Each test is self-contained; the server self-exits after 5 idle minutes
## even if a failing assert skips kill().


func test_repo_root_has_pyproject() -> void:
	assert_bool(FileAccess.file_exists(Paths.repo_root().path_join("pyproject.toml"))).is_true()


func test_spawn_listen_health_kill() -> void:
	var sp: SidecarProcess = auto_free(SidecarProcess.new())
	add_child(sp)
	var outcome := {"ok": false, "reason": ""}
	sp.booted.connect(func(_url: String, _p: int) -> void: outcome["ok"] = true)
	sp.boot_failed.connect(func(reason: String) -> void: outcome["reason"] = reason)
	sp.spawn()
	var waited := 0.0
	while not outcome["ok"] and outcome["reason"] == "" and waited < 20.0:
		await get_tree().create_timer(0.1).timeout
		waited += 0.1
	assert_str(outcome["reason"]).is_empty()
	assert_bool(outcome["ok"]).is_true()
	assert_that(sp.port).is_greater(0)
	assert_str(sp.base_url).starts_with("http://127.0.0.1:")
	var spawned_pid := sp.pid
	sp.kill()
	assert_that(sp.pid).is_equal(-1)
	# kill must reap the WHOLE tree (bash→uv→python): OS.kill on the returned
	# pid orphans the python child. Poll until the group leader is gone.
	var gone := false
	for i: int in 50:
		var probe := []
		var exit_code := OS.execute("kill", ["-0", str(spawned_pid)], probe)
		if exit_code != 0:
			gone = true
			break
		await get_tree().create_timer(0.1).timeout
	assert_bool(gone).is_true()


func test_env_override_attaches_without_spawning() -> void:
	var first: SidecarProcess = auto_free(SidecarProcess.new())
	add_child(first)
	var outcome := {"ok": false}
	first.booted.connect(func(_url: String, _p: int) -> void: outcome["ok"] = true)
	first.spawn()
	var waited := 0.0
	while not outcome["ok"] and waited < 20.0:
		await get_tree().create_timer(0.1).timeout
		waited += 0.1
	assert_bool(outcome["ok"]).is_true()

	OS.set_environment("ANDROMEDA_SIDECAR_URL", first.base_url)
	var second: SidecarProcess = auto_free(SidecarProcess.new())
	add_child(second)
	var attached := {"ok": false}
	second.booted.connect(func(_url: String, _p: int) -> void: attached["ok"] = true)
	second.spawn()
	waited = 0.0
	while not attached["ok"] and waited < 5.0:
		await get_tree().create_timer(0.1).timeout
		waited += 0.1
	OS.set_environment("ANDROMEDA_SIDECAR_URL", "")
	assert_bool(attached["ok"]).is_true()
	assert_bool(second.attached_external).is_true()
	assert_that(second.pid).is_equal(-1)
	first.kill()


func test_env_override_rejects_url_without_port() -> void:
	# No scheme and no port — normalization prepends http:// but a missing
	# explicit port must still fail boot instead of attaching to port 80.
	OS.set_environment("ANDROMEDA_SIDECAR_URL", "localhost")
	var sp: SidecarProcess = auto_free(SidecarProcess.new())
	add_child(sp)
	var outcome := {"reason": ""}
	sp.boot_failed.connect(func(msg: String) -> void: outcome["reason"] = msg)
	sp.spawn()
	OS.set_environment("ANDROMEDA_SIDECAR_URL", "")
	assert_str(outcome["reason"]).contains("ANDROMEDA_SIDECAR_URL")
	assert_str(outcome["reason"]).contains("localhost")
	assert_bool(sp.attached_external).is_false()
	assert_that(sp.pid).is_equal(-1)
