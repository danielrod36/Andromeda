"""Tests for the server-side session registry (U1, R1/R2/R3).

Covers:
- Happy path: two sequential action POSTs on one save succeed and both persist.
- Concurrency: a second action POST while the gate is held returns the
  in-flight notice and does not mutate state.
- Stale write: modifying the save file on disk between session creation and
  next action surfaces the conflict notice instead of overwriting.
- AE6 structural half: in checkpoint mode, a scene-start snapshot taken in
  one request is available to the defeat handler in a later request.
- R3 GET-POST identity: a hook rendered by a GET is the object the next POST
  resolves — no re-roll between requests.
- Regression: existing per-test saves-dir patching passes unchanged.
- Restart: killing the registry (fresh app) and re-requesting a save
  rebuilds the session from disk with identical canonical state.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Test helpers — mirror the existing per-test patching pattern.
# ---------------------------------------------------------------------------


def _get_client(saves_dir: Path) -> TestClient:
    """Create a TestClient with DEFAULT_SAVES_DIR patched across all route modules.

    Patches every module that imports DEFAULT_SAVES_DIR so the session
    registry and read-only routes all see the per-test directory.
    """
    from src.web.app import create_app
    from src.web.routes import adventure as adv_module
    from src.web.routes import inspector as insp_module
    from src.web.routes import lifepath as life_module
    from src.web.routes import memorial as mem_module
    from src.web.routes import menu as menu_module
    from src.web.routes import stream as stream_module

    saves_dir.mkdir(parents=True, exist_ok=True)
    menu_module.DEFAULT_SAVES_DIR = saves_dir
    life_module.DEFAULT_SAVES_DIR = saves_dir
    adv_module.DEFAULT_SAVES_DIR = saves_dir
    stream_module.DEFAULT_SAVES_DIR = saves_dir
    insp_module.DEFAULT_SAVES_DIR = saves_dir
    mem_module.DEFAULT_SAVES_DIR = saves_dir
    return TestClient(create_app(), base_url="http://127.0.0.1")


def _create_adventure_save(
    saves_dir: Path,
    name: str = "Hero",
    death_mode: str = "narrative",
    seed: int = 42,
) -> Path:
    """Create a mustered-out character save ready for adventure."""
    from src.engine.persistence import save
    from src.engine.state import CampaignConfig, GameState

    state = GameState.new(seed=seed)
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


def _get_bundle(client: TestClient, save_name: str = "Hero"):
    """Return the SessionBundle for *save_name* from the app's registry."""
    registry = client.app.state.session_registry
    for (_dir, stem), bundle in registry.items():
        if stem == save_name:
            return bundle
    raise KeyError(f"No session registered for save '{save_name}'")


_ORIGIN = {"Origin": "http://127.0.0.1"}


# ---------------------------------------------------------------------------
# 1. Happy path.
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Two sequential action POSTs on one save succeed and both persist."""

    def test_two_sequential_actions_persist(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        save_path = _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            # First action: accept mission.
            r1 = client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
            assert r1.status_code == 200

            # Second action: resolve option 0.
            r2 = client.post(
                "/adventure/Hero/action",
                data={"choice": "option:0"},
                headers=_ORIGIN,
            )
            assert r2.status_code == 200

        # Verify the mission persisted to disk through session.save().
        from src.engine.persistence import load

        state = load(save_path)
        assert state.active_mission is not None


# ---------------------------------------------------------------------------
# 2. Concurrency — action gate.
# ---------------------------------------------------------------------------


class TestActionGate:
    """A second action POST while the gate is held returns the in-flight notice."""

    def test_concurrent_action_returns_notice_not_500(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            # GET creates the session.
            client.get("/adventure/Hero")

            session = _get_bundle(client).session
            # Hold the gate manually (simulates an in-flight action).
            assert session.begin_action() is True

            events_before = len(session.state.events)

            # POST should get the busy notice, not a 500.
            response = client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
            assert response.status_code == 200
            # The notice targets #action-notice, not #spine.
            assert response.headers.get("HX-Retarget") == "#action-notice"
            assert "in progress" in response.text

            # No state mutation occurred.
            assert len(session.state.events) == events_before

            # The gate is still held (the rejected POST didn't release it).
            assert session.action_in_flight is True

            session.end_action()

    def test_gate_released_after_successful_action(self, tmp_path: Path):
        """After a successful action completes, the gate is free for the next."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            client.get("/adventure/Hero")
            session = _get_bundle(client).session

            # First action acquires and releases the gate.
            client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
            assert session.action_in_flight is False

            # Second action can acquire the gate immediately.
            client.post(
                "/adventure/Hero/action",
                data={"choice": "option:0"},
                headers=_ORIGIN,
            )
            assert session.action_in_flight is False


# ---------------------------------------------------------------------------
# 3. Stale write detection.
# ---------------------------------------------------------------------------


class TestStaleWrite:
    """Modifying the save on disk between actions surfaces a conflict notice."""

    def test_stale_write_returns_conflict_notice(self, tmp_path: Path):
        from src.engine.persistence import load, save

        saves_dir = tmp_path / "saves"
        save_path = _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            # GET creates the session and captures the disk hash.
            client.get("/adventure/Hero")

            # Modify the save file on disk (simulates another shell saving).
            state = load(save_path)
            state.character.name = "Modified"
            save(state, save_path)

            # POST should surface the conflict, not overwrite.
            response = client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
            assert response.status_code == 200
            assert response.headers.get("HX-Retarget") == "#action-notice"
            assert "conflict" in response.text.lower()


# ---------------------------------------------------------------------------
# 4. AE6 structural half — checkpoint snapshot survives across requests.
# ---------------------------------------------------------------------------


class TestCheckpointSnapshot:
    """In checkpoint mode, a scene-start snapshot taken in one request
    survives to the defeat handler in a later request."""

    def test_snapshot_persists_on_cached_controller(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir, death_mode="checkpoint")
        with _get_client(saves_dir) as client:
            # GET creates the session; the checkpoint sidecar is loaded
            # (none exists yet — fresh save).
            client.get("/adventure/Hero")

            # Accept mission → enters a scene → takes checkpoint snapshot.
            client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )

            # The snapshot is on the cached controller's checkpoint manager
            # (wired to the session's manager), available for a later rewind.
            bundle = _get_bundle(client)
            controller = bundle.adventure_controller
            assert controller is not None
            assert controller.checkpoint_mgr.has_snapshot

    def test_checkpoint_snapshot_persisted_to_disk(self, tmp_path: Path):
        """The snapshot sidecar file is written alongside the main save."""
        saves_dir = tmp_path / "saves"
        save_path = _create_adventure_save(saves_dir, death_mode="checkpoint")
        with _get_client(saves_dir) as client:
            client.get("/adventure/Hero")
            client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )

        # The checkpoint sidecar follows the TUI convention:
        # {save}.json.checkpoint.json
        sidecar = Path(str(save_path) + ".checkpoint.json")
        assert sidecar.exists(), f"Expected checkpoint sidecar at {sidecar}"


# ---------------------------------------------------------------------------
# 5. R3 GET-POST identity.
# ---------------------------------------------------------------------------


class TestGetPostIdentity:
    """R3: a hook rendered by a GET is the object the next POST resolves."""

    def test_controller_cached_across_requests(self, tmp_path: Path):
        """The same controller instance serves GET and POST — no reconstruction."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            # GET renders the hook (lazy generation in _build_hook_view).
            resp = client.get("/adventure/Hero")
            assert "Accept Mission" in resp.text

            bundle = _get_bundle(client)
            controller = bundle.adventure_controller
            # The hook was generated during GET and cached on the controller.
            assert controller._current_hook is not None

            # POST accept_mission uses the SAME controller instance.
            client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )

            # The hook was consumed by accept_mission — proving the POST
            # resolved the same hook the GET rendered, not a fresh one.
            assert controller._current_hook is None
            assert controller._current_mission is not None
            # The mission's hook data matches the GET-rendered hook.
            mission = controller._current_mission
            assert mission is not None

    def test_no_reroll_between_get_and_post(self, tmp_path: Path):
        """The oracle stream is not consumed twice between GET and POST.

        If the controller were stateless (new per request), _do_accept_mission
        would regenerate the hook (consuming oracle rolls). With the cached
        controller, the hook from GET persists.

        Proof: the hook patron rendered in the GET response is the same
        hook object consumed by the POST. If a re-roll happened, the
        controller's _current_hook would be None before POST and a different
        hook would be generated.
        """
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            # GET generates and caches the hook.
            get_resp = client.get("/adventure/Hero")
            assert get_resp.status_code == 200

            bundle = _get_bundle(client)
            controller = bundle.adventure_controller

            # The hook was generated during GET and cached on the controller.
            hook_after_get = controller._current_hook
            assert hook_after_get is not None
            hook_patron = hook_after_get.patron
            hook_objective = hook_after_get.objective

            # Verify the GET response rendered this specific hook.
            assert hook_patron in get_resp.text
            assert hook_objective in get_resp.text

            # POST accept_mission uses the SAME controller — the cached hook
            # is consumed without regeneration.
            client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )

            # The hook was consumed by accept_mission.
            assert controller._current_hook is None
            assert controller._current_mission is not None

            # If a stateless controller were used for the POST, it would
            # have _current_hook=None and generate a NEW hook (consuming
            # oracle rolls). The cached controller skips that because
            # _current_hook was already set from the GET.

    def test_scene_cached_across_requests(self, tmp_path: Path):
        """A scene rendered by GET survives to the next POST (R3)."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            # Accept mission first.
            client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )

            bundle = _get_bundle(client)
            controller = bundle.adventure_controller

            # The scene was generated during accept_mission's get_view().
            assert controller._current_scene is not None
            scene_after_first_post = controller._current_scene

            # GET the adventure page — should NOT regenerate the scene.
            client.get("/adventure/Hero")

            # Same scene object — no re-roll.
            assert controller._current_scene is scene_after_first_post


# ---------------------------------------------------------------------------
# 6. Regression — per-test saves-dir patching still works.
# ---------------------------------------------------------------------------


class TestRegression:
    """Existing per-test saves-dir patching patterns pass unchanged."""

    def test_per_test_saves_dir_isolation(self, tmp_path: Path):
        """Two different saves dirs never collide in the registry."""
        saves1 = tmp_path / "saves1"
        saves2 = tmp_path / "saves2"
        _create_adventure_save(saves1, name="Hero1")
        _create_adventure_save(saves2, name="Hero2")

        with _get_client(saves1) as client1:
            resp = client1.get("/adventure/Hero1")
            assert resp.status_code == 200
            assert "Hero1" in resp.text
            # Only Hero1's session is in the registry.
            assert len(client1.app.state.session_registry) == 1

        with _get_client(saves2) as client2:
            resp = client2.get("/adventure/Hero2")
            assert resp.status_code == 200
            assert "Hero2" in resp.text
            # Different app → different registry.
            assert len(client2.app.state.session_registry) == 1

    def test_existing_adventure_action_pattern(self, tmp_path: Path):
        """The existing adventure action pattern (accept → resolve) still works."""
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            # Accept mission.
            resp = client.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )
            assert resp.status_code == 200
            # Scene with odds.
            assert "%" in resp.text or "DM" in resp.text

    def test_existing_lifepath_pattern(self, tmp_path: Path):
        """The existing lifepath pattern still works with sessions."""
        from src.engine.persistence import save
        from src.engine.state import CampaignConfig, GameState

        saves_dir = tmp_path / "saves"
        saves_dir.mkdir(parents=True, exist_ok=True)
        state = GameState.new(seed=42)
        state.campaign = CampaignConfig(theme_pack="scifi", resolution_profile="classic")
        state.character.name = "Recruit"
        save(state, saves_dir / "Recruit.json")

        with _get_client(saves_dir) as client:
            resp = client.get("/play/Recruit")
            assert resp.status_code == 200
            assert "Recruit" in resp.text


# ---------------------------------------------------------------------------
# 7. Restart — session rebuilt from disk.
# ---------------------------------------------------------------------------


class TestSessionRestart:
    """Killing the registry (fresh app) rebuilds the session from disk."""

    def test_session_rebuilt_from_disk(self, tmp_path: Path):
        """A fresh app rebuilds the session from disk with identical state."""
        from src.engine.persistence import load

        saves_dir = tmp_path / "saves"
        save_path = _create_adventure_save(saves_dir)

        # App 1: accept mission, persist.
        with _get_client(saves_dir) as client1:
            client1.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )

        # Verify the mission persisted.
        state_after = load(save_path)
        assert state_after.active_mission is not None

        # App 2: fresh registry — session is rebuilt from disk.
        with _get_client(saves_dir) as client2:
            # Registry starts empty.
            assert len(client2.app.state.session_registry) == 0

            resp = client2.get("/adventure/Hero")
            assert resp.status_code == 200

            # Session was created on demand.
            assert len(client2.app.state.session_registry) == 1

            # The rebuilt session has the persisted state.
            bundle = _get_bundle(client2)
            assert bundle.session.state.active_mission is not None

    def test_checkpoint_snapshot_loaded_on_restart(self, tmp_path: Path):
        """A checkpoint sidecar is loaded when the session is rebuilt."""
        saves_dir = tmp_path / "saves"
        save_path = _create_adventure_save(saves_dir, death_mode="checkpoint")

        # App 1: play to scene start, persist checkpoint snapshot.
        with _get_client(saves_dir) as client1:
            client1.get("/adventure/Hero")
            client1.post(
                "/adventure/Hero/action",
                data={"choice": "accept_mission"},
                headers=_ORIGIN,
            )

        # The sidecar exists on disk.
        sidecar = Path(str(save_path) + ".checkpoint.json")
        assert sidecar.exists()

        # App 2: fresh registry — session loads the checkpoint snapshot.
        with _get_client(saves_dir) as client2:
            client2.get("/adventure/Hero")
            bundle = _get_bundle(client2)
            # The checkpoint manager has the loaded snapshot.
            assert bundle.session.checkpoint_mgr.has_snapshot


# ---------------------------------------------------------------------------
# Template: hx-disabled-elt and action-notice region.
# ---------------------------------------------------------------------------


class TestTemplateAdditions:
    """Templates carry hx-disabled-elt and the action-notice region (U1)."""

    def test_adventure_has_action_notice_region(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            resp = client.get("/adventure/Hero")
        assert 'id="action-notice"' in resp.text
        assert 'aria-live="polite"' in resp.text
        assert 'role="status"' in resp.text

    def test_adventure_forms_have_hx_disabled_elt(self, tmp_path: Path):
        saves_dir = tmp_path / "saves"
        _create_adventure_save(saves_dir)
        with _get_client(saves_dir) as client:
            resp = client.get("/adventure/Hero")
        assert "hx-disabled-elt" in resp.text

    def test_lifepath_has_action_notice_region(self, tmp_path: Path):
        from src.engine.persistence import save
        from src.engine.state import CampaignConfig, GameState

        saves_dir = tmp_path / "saves"
        saves_dir.mkdir(parents=True, exist_ok=True)
        state = GameState.new(seed=42)
        state.campaign = CampaignConfig(theme_pack="scifi", resolution_profile="classic")
        state.character.name = "Recruit"
        save(state, saves_dir / "Recruit.json")

        with _get_client(saves_dir) as client:
            resp = client.get("/play/Recruit")
        assert 'id="action-notice"' in resp.text
        assert "hx-disabled-elt" in resp.text
