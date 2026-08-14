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
	sp.kill()
	assert_that(sp.pid).is_equal(-1)


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
