"""Preferences validation and nonfatal settings/recovery failure handling."""

import copy
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QInputDialog
from rasterio.crs import CRS

from test_app import qt_app, terrain_path, window, accept_line, wait_idle
from tracertool import desktop_actions
from tracertool.app import MainWindow
from tracertool.preferences import DEFAULTS, display_kwargs, normalize_preferences
from tracertool.project import load_project
from tracertool.terrain import Terrain


def test_default_preferences_are_valid_and_independent():
    defaults = normalize_preferences()
    assert defaults == DEFAULTS
    assert normalize_preferences(defaults) == defaults
    defaults["display"]["palette"] = "gray"
    defaults["session"]["working_dimension"] = 1024
    assert DEFAULTS["display"]["palette"] == "earth"
    assert normalize_preferences()["session"]["working_dimension"] == 2400


def test_partial_preferences_merge_without_mutating_input():
    supplied = {"display": {"gamma": 1.4}, "session": {"working_dimension": 4096},
                "future_group": {"future_key": True}}
    before = copy.deepcopy(supplied)
    normalized = normalize_preferences(supplied)
    assert normalized["display"]["gamma"] == 1.4
    assert normalized["display"]["palette"] == "earth"
    assert normalized["session"]["working_dimension"] == 4096
    assert "future_group" not in normalized
    assert supplied == before


@pytest.mark.parametrize("preferences", [
    [], "settings", {"display": []},
    {"display": {"gamma": 0}}, {"display": {"gamma": float("nan")}},
    {"display": {"gamma": float("inf")}}, {"display": {"gamma": True}},
    {"display": {"gamma": "1.2"}}, {"display": {"altitude": 91}},
    {"display": {"shade_strength": -0.1}}, {"display": {"contour_interval": -1}},
    {"display": {"palette": "missing"}}, {"display": {"vertical_units": "fathoms"}},
    {"display": {"stretch": "custom", "low": 10, "high": 10}},
    {"display": {"stretch": "custom", "low": 20, "high": 10}},
    {"display": {"multidirectional": 1}}, {"editing": {"snap_enabled": "yes"}},
    {"editing": {"snap_radius": 0}}, {"editing": {"join_tolerance": -1}},
    {"editing": {"history_limit": 10.5}}, {"session": {"autosave_seconds": 4}},
    {"session": {"autosave_seconds": 30.5}}, {"session": {"remember_view": 0}},
    {"session": {"working_dimension": 128}}, {"session": {"working_dimension": 10000}},
    {"export": {"scope": "visible-ish"}}, {"export": {"target_crs": 32615}},
    {"export": {"z_scale": 0}}, {"export": {"z_scale": -1}},
])
def test_invalid_values_are_actionable_value_errors(preferences):
    with pytest.raises(ValueError):
        normalize_preferences(preferences)


def test_huge_integer_preference_is_rejected_without_overflow_exception():
    with pytest.raises(ValueError):
        normalize_preferences({"display": {"gamma": 10 ** 1000}})


@pytest.mark.parametrize("crs", ["EPSG:32615", "EPSG:26914", CRS.from_epsg(32615).to_wkt()])
def test_projected_export_crs_is_accepted(crs):
    normalized = normalize_preferences({"export": {"target_crs": crs}})
    assert CRS.from_user_input(normalized["export"]["target_crs"]).is_projected


@pytest.mark.parametrize("crs", ["EPSG:4326", "CRS:84", "not a CRS", "EPSG:0"])
def test_invalid_or_geographic_export_crs_is_rejected(crs):
    with pytest.raises(ValueError, match="CRS"):
        normalize_preferences({"export": {"target_crs": crs}})


def test_whitespace_export_crs_normalizes_to_native_export():
    normalized = normalize_preferences({"export": {"target_crs": "  \t "}})
    assert normalized["export"]["target_crs"] == "", "Whitespace must not trigger a bogus explicit CRS transformation"


def test_display_options_are_detached_and_do_not_request_geometry_changes():
    preferences = normalize_preferences({"display": {"vertical_units": "foot", "contour_interval": 5}})
    options = display_kwargs(preferences)
    assert options["vertical_units"] == "foot"
    assert options["low"] is None and options["high"] is None
    assert "contour_interval" not in options and "z_scale" not in options and "target_crs" not in options
    options["palette"] = "gray"
    assert preferences["display"]["palette"] == "earth"
    assert display_kwargs(normalize_preferences())["vertical_units"] is None


def test_vertical_unit_override_changes_display_only(terrain_path):
    terrain = Terrain.load(terrain_path)
    original_bytes = terrain_path.read_bytes()
    original_data = terrain.data.copy()
    original_sample = terrain.sample(*terrain.xy(10, 40))
    in_meters = normalize_preferences({"display": {"vertical_units": "m"}})
    in_feet = normalize_preferences({"display": {"vertical_units": "foot"}})
    meter_display = terrain.rgb("Slope", **display_kwargs(in_meters))
    foot_display = terrain.rgb("Slope", **display_kwargs(in_feet))
    assert not np.array_equal(meter_display, foot_display)
    assert np.array_equal(terrain.data, original_data, equal_nan=True)
    assert terrain.sample(*terrain.xy(10, 40)) == original_sample
    assert terrain_path.read_bytes() == original_bytes


def test_custom_display_range_is_forwarded_without_affecting_export_defaults():
    preferences = normalize_preferences({"display": {"stretch": "custom", "low": -10, "high": 50}})
    options = display_kwargs(preferences)
    assert (options["low"], options["high"]) == (-10, 50)
    assert preferences["export"] == DEFAULTS["export"]


def test_invalid_contour_settings_roll_back_active_and_default_preferences(window, tmp_path):
    original = accept_line(window)
    window.project_path = str(tmp_path / "accepted.tracer.json")
    assert window.save()
    before = copy.deepcopy(window.preferences)
    before_defaults = copy.deepcopy(window.default_preferences)
    before_timer = window.autosave_timer.interval()
    desired = copy.deepcopy(before)
    desired["display"]["contour_interval"] = .001  # Thousands of contour levels.
    desired["session"]["autosave_seconds"] = 10
    window.apply_preferences(desired, use_as_default=True)
    wait_idle(window)
    assert any("contour" in message.lower() for message in window.test_errors)
    window.test_errors.clear()
    assert window.preferences == before
    assert window.default_preferences == before_defaults
    assert window.autosave_timer.interval() == before_timer
    assert window.features == [original]
    assert not window.dirty
    assert not (window.state_directory / "defaults.json").exists()


def test_default_write_failure_keeps_existing_defaults_and_active_settings(window, tmp_path, monkeypatch):
    window.project_path = str(tmp_path / "empty.tracer.json")
    assert window.save()
    before = copy.deepcopy(window.preferences)
    target = window.state_directory / "defaults.json"
    target.write_text(json.dumps(before))
    default_bytes = target.read_bytes()
    desired = copy.deepcopy(before)
    desired["display"]["palette"] = "viridis"
    desired["session"]["autosave_seconds"] = 10
    real_replace = desktop_actions.os.replace

    def fail_defaults(source, destination):
        if Path(destination) == target:
            raise PermissionError("default settings locked")
        return real_replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(desktop_actions.os, "replace", fail_defaults)
        window.apply_preferences(desired, use_as_default=True)
        wait_idle(window)
    assert any("locked" in message for message in window.test_errors)
    window.test_errors.clear()
    assert window.preferences == before
    assert window.default_preferences == before
    assert window.autosave_timer.interval() == before["session"]["autosave_seconds"] * 1000
    assert target.read_bytes() == default_bytes
    assert not window.dirty
    assert not list(window.state_directory.glob("*.tmp"))


def test_default_write_failure_without_open_terrain_is_nonfatal(qt_app, monkeypatch):
    errors = []
    monkeypatch.setattr(MainWindow, "error", lambda self, message: errors.append(str(message)))
    view = MainWindow()
    try:
        before = copy.deepcopy(view.preferences)
        target = view.state_directory / "defaults.json"
        target.write_text(json.dumps(before), encoding="utf-8")
        default_bytes = target.read_bytes()
        desired = copy.deepcopy(before)
        desired["editing"]["snap_enabled"] = False
        desired["session"]["autosave_seconds"] = 10
        real_replace = desktop_actions.os.replace

        def fail_defaults(source, destination):
            if Path(destination) == target:
                raise PermissionError("default settings locked")
            return real_replace(source, destination)

        with monkeypatch.context() as patch:
            patch.setattr(desktop_actions.os, "replace", fail_defaults)
            view.apply_preferences(desired, use_as_default=True)
        assert any("locked" in message for message in errors)
        assert view.preferences == before
        assert view.default_preferences == before
        assert view.autosave_timer.interval() == before["session"]["autosave_seconds"] * 1000
        assert target.read_bytes() == default_bytes
        assert not list(view.state_directory.glob("*.tmp"))
    finally:
        view.close()
        view.deleteLater()
        qt_app.processEvents()


def test_blocked_recovery_directory_does_not_prevent_startup_or_manual_save(qt_app, terrain_path, tmp_path, monkeypatch):
    blocked = tmp_path / "blocked-state"
    blocked.write_bytes(b"a file where the configured state directory should be")
    monkeypatch.setenv("TRACERTOOL_STATE_DIR", str(blocked))
    errors = []
    monkeypatch.setattr(MainWindow, "error", lambda self, message: errors.append(str(message)))
    monkeypatch.setattr(desktop_actions.tempfile, "gettempdir", lambda: str(tmp_path))
    view = MainWindow()
    try:
        assert view.state_directory != blocked and view.state_directory.is_dir()
        assert str(view.state_directory) in view.recovery_warning
        view.install_terrain(view.load_terrain_image(terrain_path))
        path = tmp_path / "manual-save.tracer.json"
        view.project_path = str(path)
        assert view.save(), "Recovery storage failure must not prevent explicit project saves"
        assert load_project(path)["terrain_path"] == str(terrain_path)
        assert blocked.read_bytes().startswith(b"a file")
    finally:
        view.dirty = False
        view.close()
        view.deleteLater()
        qt_app.processEvents()


def test_fallback_recovery_is_discovered_and_restored_by_reopened_window(qt_app, terrain_path, tmp_path, monkeypatch):
    blocked = tmp_path / "blocked-state"
    blocked.write_bytes(b"not a directory")
    monkeypatch.setenv("TRACERTOOL_STATE_DIR", str(blocked))
    monkeypatch.setattr(desktop_actions.tempfile, "gettempdir", lambda: str(tmp_path))
    errors = []
    monkeypatch.setattr(MainWindow, "error", lambda self, message: errors.append(str(message)))
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args, **kwargs: (args[3][0], True))
    first = MainWindow()
    reopened = None
    try:
        first.install_terrain(first.load_terrain_image(terrain_path))
        first.add_anchor(8, 40)
        first.add_anchor(70, 40)
        draft = copy.deepcopy(first.settings()["draft"])
        first.save_recovery()
        entries = first.recovery_store.list_entries()
        assert len(entries) == 1 and entries[0]["draft_anchor_count"] == 2
        snapshot = Path(entries[0]["path"])
        original_snapshot = snapshot.read_bytes()
        fallback = first.state_directory
        original_session = first.session_id

        # Preserve the snapshot, as when a process exits before clean-up runs.
        with monkeypatch.context() as patch:
            patch.setattr(first, "check_discard", lambda: True)
            patch.setattr(first, "discard_recovery", lambda: None)
            first.close()

        reopened = MainWindow()
        assert reopened.session_id != original_session
        assert reopened.state_directory == fallback
        assert reopened.recovery_store.list_entries() == entries
        reopened.recover_work()
        wait_idle(reopened)
        assert reopened.settings()["draft"] == draft
        assert reopened.terrain.path == str(terrain_path)
        assert reopened.dirty, "Recovered work still needs an explicit project save"
        assert snapshot.read_bytes() == original_snapshot
        assert not errors
    finally:
        for view in (reopened, first):
            if view is None:
                continue
            wait_idle(view)
            view.clear_draft()
            view.dirty = False
            view.close()
            view.deleteLater()
        qt_app.processEvents()


def test_existing_unwritable_recovery_folder_uses_working_fallback(qt_app, terrain_path, tmp_path, monkeypatch):
    from tracertool import recovery
    state = tmp_path / "existing-state"
    normal = state / "recovery"
    normal.mkdir(parents=True)
    monkeypatch.setenv("TRACERTOOL_STATE_DIR", str(state))
    monkeypatch.setattr(desktop_actions.tempfile, "gettempdir", lambda: str(tmp_path))
    actual_temporary = recovery.tempfile.NamedTemporaryFile

    def deny_normal_folder(*args, **kwargs):
        if Path(kwargs.get("dir", "")) == normal:
            raise PermissionError("Existing recovery folder is locked")
        return actual_temporary(*args, **kwargs)

    monkeypatch.setattr(recovery.tempfile, "NamedTemporaryFile", deny_normal_folder)
    errors = []
    monkeypatch.setattr(MainWindow, "error", lambda self, message: errors.append(str(message)))
    view = MainWindow()
    try:
        assert view.state_directory != state
        assert "Temporary recovery" in view.recovery_warning
        view.install_terrain(view.load_terrain_image(terrain_path))
        view.tool_buttons["manual"].click()
        view.add_anchor(8, 40)
        view.save_recovery()
        entries = view.recovery_store.list_entries()
        assert len(entries) == 1 and entries[0]["draft_anchor_count"] == 1
        assert list(normal.iterdir()) == []
        assert not errors
    finally:
        view.clear_draft()
        view.dirty = False
        view.close()
        view.deleteLater()
        qt_app.processEvents()


def test_corrupted_personal_defaults_fall_back_safely(qt_app, tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    (state / "defaults.json").write_text("{interrupted defaults")
    monkeypatch.setenv("TRACERTOOL_STATE_DIR", str(state))
    view = MainWindow()
    try:
        assert view.preferences == DEFAULTS
        assert view.autosave_timer.interval() == DEFAULTS["session"]["autosave_seconds"] * 1000
    finally:
        view.close()
        view.deleteLater()
        qt_app.processEvents()


def test_recovery_cleanup_failure_does_not_turn_successful_project_save_into_failure(window, tmp_path, monkeypatch):
    original = accept_line(window)
    target = tmp_path / "saved.tracer.json"
    window.project_path = str(target)

    def locked_recovery(*args):
        raise ValueError("Recovery snapshot is locked")

    with monkeypatch.context() as patch:
        patch.setattr(window.recovery_store, "discard", locked_recovery)
        saved = window.save()
    window.test_errors.clear()  # A recovery warning is acceptable; a failed save is not.
    assert saved is True
    assert load_project(target)["features"] == [original]
    assert not window.dirty
    assert "locked" in window.recovery_warning
    assert "pending" in window.recovery_status.text().lower()


def test_recovery_cleanup_failure_does_not_prevent_clean_close(window, monkeypatch):
    def locked_recovery(*args):
        raise ValueError("Recovery snapshot is locked")

    event = QCloseEvent()
    with monkeypatch.context() as patch:
        patch.setattr(window.recovery_store, "discard", locked_recovery)
        window.closeEvent(event)
    window.test_errors.clear()
    assert event.isAccepted()
    assert "locked" in window.recovery_warning
