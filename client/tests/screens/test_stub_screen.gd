extends GdUnitTestSuite
## Boundary stubs (spec M2-D8): honest gates for M3/M4 screens.


func test_chargen_session_gets_the_ceremony_stub() -> void:
	var stub: StubScreen = auto_free(StubScreen.new())
	add_child(stub)
	(
		stub
		. screen_enter(
			{
				"session":
				{
					"id": "s1",
					"name": "x",
					"kind": "chargen",
					"phase": "homeworld",
					"view": {"prompt": "Where?"},
					"contract_version": 1,
				}
			}
		)
	)
	assert_str(stub.title_text()).is_equal("THE CEREMONY arrives in M3")
	assert_str(stub.esc_target()).is_equal("title")


func test_adventure_session_gets_the_shell_stub() -> void:
	var stub: StubScreen = auto_free(StubScreen.new())
	add_child(stub)
	(
		stub
		. screen_enter(
			{
				"session":
				{
					"id": "s2",
					"name": "x",
					"kind": "adventure",
					"phase": "scene",
					"view": {"phase": "scene", "game_over": false},
					"contract_version": 1,
				}
			}
		)
	)
	assert_str(stub.title_text()).is_equal("THE ADVENTURE SHELL arrives in M4")


func test_game_over_view_gets_the_memorial_stub() -> void:
	var stub: StubScreen = auto_free(StubScreen.new())
	add_child(stub)
	(
		stub
		. screen_enter(
			{
				"session":
				{
					"id": "s3",
					"name": "x",
					"kind": "adventure",
					"phase": "game_over",
					"view": {"phase": "game_over", "game_over": true},
					"contract_version": 1,
				}
			}
		)
	)
	assert_str(stub.title_text()).is_equal("THE MEMORIAL arrives in M4")
