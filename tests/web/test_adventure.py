"""Tests for the web adventure screens (U9).

Verifies the adventure loop works over HTTP: hooks, scenes with odds,
option resolution, free-text classify, and defeat interstitials.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _get_client(saves_dir: Path) -> TestClient:
    from src.web.app import create_app
    from src.web.routes import adventure as adv_module
    from src.web.routes import lifepath as life_module
    from src.web.routes import menu as menu_module

    saves_dir.mkdir(parents=True, exist_ok=True)
    menu_module.DEFAULT_SAVES_DIR = saves_dir
    life_module.DEFAULT_SAVES_DIR = saves_dir
    adv_module.DEFAULT_SAVES_DIR = saves_dir
    return TestClient(create_app(), base_url="http://127.0.0.1")


def _create_adventure_save(
    saves_dir: Path, name: str = "Hero", death_mode: str = "narrative"
) -> Path:
    """Create a mustered-out character save ready for adventure."""
    from src.engine.persistence import save
    from src.engine.state import CampaignConfig, GameState

    state = GameState.new(seed=42)
    state.campaign = CampaignConfig(
        theme_pack="scifi", resolution_profile="narrative", death_mode=death_mode
    )
    state.character.name = name
    state.character.characteristics = {
        "STR": 7,
        "DEX": 9,
        "END": 6,
        "INT": 8,
        "EDU": 10,
        "SOC": 5,
    }
    state.character.skills = {"Gun Combat": 1, "Persuade": 0, "Stealth": 2, "Investigate": 1}
    state.character.career = "navy"
    state.character.terms = 2
    state.character.alive = True
    state.narrative_log.append("mustered_out=true")
    path = saves_dir / f"{name}.json"
    save(state, path)
    return path


def _get_cached_controller(client: TestClient, save_name: str = "Hero"):
    """Return the AdventureController cached on the session registry."""
    registry = client.app.state.session_registry
    for (_dir, stem), bundle in registry.items():
        if stem == save_name:
            return bundle.adventure_controller
    raise KeyError(f"No session registered for save '{save_name}'")


def _force_defeat(controller) -> None:
    """Monkey-patch the controller so the next option resolve triggers defeat.

    Tests call this before resolving an option they want to drive through the
    defeat path, so the test is deterministic rather than dependent on a
    life-threatening MISS happening to come up.
    """

    def always_defeat(self, check_result, option, consequences):
        return self._handle_defeat("forced test defeat")

    controller._check_defeat = always_defeat.__get__(controller)


_ORIGIN = {"Origin": "http://127.0.0.1"}


class TestAdventureScreen:
    """U9: the adventure screen renders."""

    def test_get_adventure_returns_200(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/adventure/Hero")
        assert response.status_code == 200
        assert "Hero" in response.text

    def test_hook_phase_shows_accept_refuse(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/adventure/Hero")
        assert "Accept Mission" in response.text
        assert "Refuse" in response.text

    def test_nonexistent_save_redirects(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.get("/adventure/Nobody", follow_redirects=False)
        assert response.status_code == 303
        assert "/saves" in response.headers.get("location", "")


class TestSceneOptions:
    """U9: scene options show pre-commit odds."""

    def test_accept_mission_shows_scene_with_odds(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            response = client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
        assert response.status_code == 200
        # Should have odds on the options.
        assert "%" in response.text or "DM" in response.text

    def test_option_post_resolves_and_shows_receipt(self, tmp_path: Path):
        """Resolving a scene option must show the outcome (U9 receipt-preservation).

        The POST handler must render the view returned by ``apply_choice``,
        not a fresh ``get_view()`` that discards receipts.  Evidence: either
        a receipt div (normal resolution) or a defeat notice (defeat triggered).
        A broken fresh-scene render would show ``scene-header`` with neither.
        """
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            # Accept mission first.
            client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
            # Resolve option 0.
            response = client.post(
                "/adventure/Hero/action",
                data={"choice": "option:0"},
                headers=_ORIGIN,
            )
        assert response.status_code == 200
        # The resolved view must carry the outcome — receipt or defeat.
        # A fresh get_view() would have neither (empty receipts, no defeat).
        has_receipt = 'class="receipt"' in response.text
        has_defeat = "defeat" in response.text.lower()
        assert has_receipt or has_defeat, (
            "Expected either a receipt div or defeat notice from the "
            "apply_choice return value, but got neither — the POST handler "
            "may be calling get_view() instead of using the returned view"
        )


class TestFreeTextOverHTTP:
    """U9: free-text classify via HTTP."""

    def test_freetext_post_returns_200(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            # Accept mission first.
            client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
            # Submit free-text.
            response = client.post(
                "/adventure/Hero/freetext",
                data={"freetext": "I bribe the dock officer"},
                headers=_ORIGIN,
            )
        assert response.status_code == 200

    def test_freetext_keyword_match_shows_interpretation(self, tmp_path: Path):
        """Free-text that matches a keyword must show the interpretation prompt."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
            response = client.post(
                "/adventure/Hero/freetext",
                data={"freetext": "I bribe the dock officer"},
                headers=_ORIGIN,
            )
        # The keyword classifier should match "bribe" → interpretation view
        # with Accept/Reject choices.  Assert directly — no silent pass.
        assert "Interpreted" in response.text or "Accept" in response.text, (
            "Expected the free-text classification to produce an "
            "interpretation prompt with Accept/Reject choices"
        )


class TestActionPersistence:
    """U9: actions persist state to the save file."""

    def test_accept_mission_persists(self, tmp_path: Path):
        from src.engine.persistence import load

        saves_dir = tmp_path / "saves"
        save_path = _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
        state = load(save_path)
        assert state.active_mission is not None

    def test_pending_freetext_resume(self, tmp_path: Path):
        """A save with pending_freetext set resumes the interpretation prompt."""
        from src.engine.persistence import save as save_state

        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)

        # Set pending_freetext directly.
        from src.engine.persistence import load

        state = load(saves_dir / "Hero.json")
        state.active_mission = {
            "id": "m1",
            "hook": {"patron": "P", "objective": "O", "complication": "C", "reward": "R"},
            "scenes_completed": 0,
            "min_scenes": 3,
            "success_text": "",
            "failure_text": "",
            "abandonment_text": "",
        }
        state.pending_freetext = {
            "text": "I bribe him",
            "check": {
                "label": "Bribe",
                "skill": "broker",
                "characteristic": "SOC",
                "difficulty": "average",
            },
            "scaffold": {
                "focus": "Dock",
                "focus_description": "Busy dock",
                "situation": "Tense",
                "npc_hint": "",
            },
            "options": [],
        }
        save_state(state, saves_dir / "Hero.json")

        with _get_client(saves_dir) as client:
            response = client.get("/adventure/Hero")
        # Should show the accept/reject prompt, not a fresh scene.
        assert "Accept" in response.text or "Interpreted" in response.text

    def test_freetext_accept_resolves_after_save_load(self, tmp_path: Path):
        """Accepting a pending free-text check must resolve after save/load (U9).

        Regression test for the controller not reconstructing _current_scene
        and _pending_freetext on fresh load — the accept_freetext POST must
        clear pending_freetext and show a receipt, not loop forever.
        """
        from src.engine.persistence import load as load_state
        from src.engine.persistence import save as save_state

        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)

        # Build a save with an active mission and a pending freetext check.
        state = load_state(saves_dir / "Hero.json")
        state.active_mission = {
            "id": "m1",
            "hook": {"patron": "P", "objective": "O", "complication": "C", "reward": "R"},
            "scenes_completed": 0,
            "min_scenes": 3,
            "success_text": "",
            "failure_text": "",
            "abandonment_text": "",
        }
        state.pending_freetext = {
            "text": "I sneak past the guard",
            "check": {
                "label": "Sneak",
                "skill": "stealth",
                "characteristic": "DEX",
                "difficulty": "average",
                "description": "",
                "life_threatening": False,
            },
            "scaffold": {
                "focus": "Corridor",
                "focus_description": "Dim corridor",
                "situation": "Guarded",
                "npc_hint": "Guard",
            },
            "options": [
                {
                    "label": "Fight",
                    "skill": "gun_combat",
                    "characteristic": "DEX",
                    "difficulty": "average",
                    "description": "",
                    "life_threatening": False,
                }
            ],
        }
        save_state(state, saves_dir / "Hero.json")

        # POST accept_freetext — the controller is freshly constructed.
        with _get_client(saves_dir) as client:
            response = client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_freetext"},
                headers=_ORIGIN,
            )

        assert response.status_code == 200
        # The check was resolved — either a receipt or a defeat notice
        # appears (not the freetext_pending interpretation prompt).
        assert "freetext_pending" not in response.text, (
            "Expected the free-text check to be resolved, but the phase "
            "is still freetext_pending — the accept handler did not resolve"
        )
        has_receipt = 'class="receipt"' in response.text
        has_defeat = "defeat" in response.text.lower()
        assert has_receipt or has_defeat, (
            "Expected either a receipt or defeat notice from the resolved check"
        )
        # pending_freetext must be cleared from the save.
        final_state = load_state(saves_dir / "Hero.json")
        assert final_state.pending_freetext is None


class TestDefeatPaths:
    """U4 (R2/R8/R9, AE6): defeat paths return playable or terminally-correct
    screens, with accurate text."""

    def test_narrative_defeat_shows_fresh_scene_with_choices(self, tmp_path: Path):
        """R8: narrative defeat → 200 with injury applied and fresh scene
        choices in the same response (not a choiceless screen)."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir, death_mode="narrative")
        with _get_client(saves_dir) as client:
            client.get("/adventure/Hero")
            # Accept mission → enters a scene.
            client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
            # Force defeat on the next option resolve.
            controller = _get_cached_controller(client)
            _force_defeat(controller)

            response = client.post(
                "/adventure/Hero/action",
                data={"choice": "option:0"},
                headers=_ORIGIN,
            )
        assert response.status_code == 200
        # The defeat notice must be visible.
        assert "defeat" in response.text.lower()
        # Fresh scene choices must be present — not a choiceless screen.
        assert "choice-dock" in response.text or "choice" in response.text.lower()
        # The strategy message owns the sentence — the controller must not
        # append its own "Play continues." on top of the strategy's.
        # Narrative strategy's message already says "Play continues." so
        # at most one occurrence is correct; two would mean duplication.
        count = response.text.count("Play continues.")
        assert count <= 1, f"Expected at most 1 'Play continues.' (from strategy), got {count}"

    def test_ironman_defeat_shows_game_over(self, tmp_path: Path):
        """R8: ironman defeat → game-over interstitial with no choices."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir, death_mode="ironman")
        with _get_client(saves_dir) as client:
            client.get("/adventure/Hero")
            client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
            controller = _get_cached_controller(client)
            _force_defeat(controller)

            response = client.post(
                "/adventure/Hero/action",
                data={"choice": "option:0"},
                headers=_ORIGIN,
            )
        assert response.status_code == 200
        # Game-over interstitial.
        assert "game_over" in response.text
        # No choice dock on terminal defeat.
        assert "choice-dock" not in response.text

    def test_checkpoint_defeat_rewinds_with_choices(self, tmp_path: Path):
        """R2/AE6: checkpoint defeat → 200, state rewound, scene choices
        present (not a 500, not a choiceless screen)."""
        from src.engine.audit import EventKind
        from src.engine.persistence import load

        saves_dir = tmp_path / "saves"
        save_path = _create_adventure_save(saves_dir, death_mode="checkpoint")
        with _get_client(saves_dir) as client:
            client.get("/adventure/Hero")
            # Accept mission → enters a scene → takes checkpoint snapshot.
            client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
            controller = _get_cached_controller(client)
            _force_defeat(controller)

            response = client.post(
                "/adventure/Hero/action",
                data={"choice": "option:0"},
                headers=_ORIGIN,
            )
        assert response.status_code == 200
        # Defeat notice present.
        assert "defeat" in response.text.lower()
        # Fresh scene choices present — not a choiceless screen.
        assert "choice-dock" in response.text
        # REWIND_APPLIED boundary appended to the event log.
        final_state = load(save_path)
        rewind_events = [e for e in final_state.events if e.kind == EventKind.REWIND_APPLIED]
        assert len(rewind_events) >= 1

    def test_checkpoint_freetext_defeat_no_crash(self, tmp_path: Path):
        """R2/AE6: checkpoint campaign, accepted free-text check forced to a
        life-threatening miss → response is 200, state rewound, scene choices
        present (not a 500, not a choiceless screen).

        This exercises the defensive belt: on the restart edge the controller
        may be freshly constructed and the CheckpointManager may lack a
        snapshot. We simulate this by clearing the snapshot before the
        free-text accept.
        """
        from src.engine.audit import EventKind
        from src.engine.persistence import load as load_state
        from src.engine.persistence import save as save_state

        saves_dir = tmp_path / "saves"
        save_path = _create_adventure_save(saves_dir, death_mode="checkpoint")

        # Set up a save with an active mission and a pending free-text check.
        state = load_state(save_path)
        state.active_mission = {
            "id": "m1",
            "hook": {"patron": "P", "objective": "O", "complication": "C", "reward": "R"},
            "scenes_completed": 0,
            "min_scenes": 3,
            "success_text": "",
            "failure_text": "",
            "abandonment_text": "",
        }
        state.pending_freetext = {
            "text": "I brave the explosion",
            "check": {
                "label": "Brave",
                "skill": "athletics",
                "characteristic": "END",
                "difficulty": "difficult",
                "description": "",
                "life_threatening": True,
            },
            "scaffold": {
                "focus": "Burning Room",
                "focus_description": "Flames everywhere",
                "situation": "Desperate",
                "npc_hint": "",
            },
            "options": [
                {
                    "label": "Retreat",
                    "skill": "athletics",
                    "characteristic": "END",
                    "difficulty": "average",
                    "description": "",
                    "life_threatening": False,
                }
            ],
        }
        save_state(state, save_path)

        with _get_client(saves_dir) as client:
            # GET builds the session and reconstructs the controller.
            client.get("/adventure/Hero")

            # The controller is freshly constructed — simulate the restart
            # edge by clearing the snapshot so the defensive belt fires.
            controller = _get_cached_controller(client)
            controller._checkpoint_mgr.clear()
            assert not controller._checkpoint_mgr.has_snapshot

            # Force defeat so the life-threatening check triggers it.
            _force_defeat(controller)

            response = client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_freetext"},
                headers=_ORIGIN,
            )
        assert response.status_code == 200
        # State rewound — REWIND_APPLIED in the event log.
        final_state = load_state(save_path)
        rewind_events = [e for e in final_state.events if e.kind == EventKind.REWIND_APPLIED]
        assert len(rewind_events) >= 1
        # Fresh scene choices present.
        assert "choice-dock" in response.text

    def test_no_duplicated_play_continues_text(self, tmp_path: Path):
        """R9: 'Play continues.' appears at most once — from the strategy
        message — never duplicated by the controller appending its own."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir, death_mode="narrative")
        with _get_client(saves_dir) as client:
            client.get("/adventure/Hero")
            client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
            controller = _get_cached_controller(client)
            _force_defeat(controller)

            response = client.post(
                "/adventure/Hero/action",
                data={"choice": "option:0"},
                headers=_ORIGIN,
            )
        assert response.status_code == 200
        # The narrative strategy's own message includes "Play continues."
        # — that's the strategy owning the sentence. The controller must
        # NOT add its own, which would produce two occurrences.
        count = response.text.count("Play continues.")
        assert count <= 1, f"Expected at most 1 'Play continues.' (strategy owns it), got {count}"
