"""Acceptance coverage for correction, recovery, preferences, and export workflows."""

import copy
import json
from pathlib import Path
import threading

import numpy as np
import pytest
import rasterio
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                              QDialogButtonBox, QFileDialog, QInputDialog, QLineEdit)
from PySide6.QtWidgets import QMessageBox
import shapefile

from test_app import (qt_app, terrain_path, window, accept_line, add_map_anchor,
                      map_position, select_tool, wait_idle)
from tracertool.preferences import PreferencesDialog
from tracertool.project import load_project
from tracertool.raster_ops import transform_features


def preview(window):
    QTest.mouseClick(window.trace_button, Qt.MouseButton.LeftButton)
    wait_idle(window)
    assert window.preview is not None, window.test_errors


def click_saved_vertex(window, feature, index):
    row, column = window.terrain.rc(*feature["coordinates"][index][:2])
    QTest.mouseClick(window.canvas.viewport(), Qt.MouseButton.LeftButton,
                     pos=map_position(window, row, column))


def test_segment_correction_preserves_all_outside_xyz_and_is_undoable(window):
    window.param_widgets["spacing"].setValue(10)
    original = accept_line(window, anchors=((8, 30), (25, 30), (45, 30), (70, 30)))
    start, end = 2, len(original["coordinates"]) - 3
    assert start < end
    QTest.mouseClick(window.edit_buttons["segment"], Qt.MouseButton.LeftButton)
    click_saved_vertex(window, original, start)
    click_saved_vertex(window, original, end)
    assert window.segment_range == (start, end)
    assert window.edit_target == original["id"]
    boundaries = copy.deepcopy(window.anchors)
    window.move_anchor(0, 12, 10)
    assert window.anchors == boundaries, "Correction endpoints must remain fixed"
    mid_row = sum(point[0] for point in boundaries) / 2
    add_map_anchor(window, round(mid_row), 35)
    assert len(window.anchors) == 3
    preview(window)
    assert window.features == [original], "A preview cannot alter accepted work"
    assert "apply" in window.accept_button.text().lower()
    QTest.mouseClick(window.accept_button, Qt.MouseButton.LeftButton)
    corrected = window.features[0]
    assert corrected["id"] == original["id"]
    assert corrected["coordinates"][:start + 1] == original["coordinates"][:start + 1]
    tail_count = len(original["coordinates"]) - end
    assert corrected["coordinates"][-tail_count:] == original["coordinates"][end:]
    assert corrected["coordinates"] != original["coordinates"]
    assert corrected["provenance"]
    QTest.mouseClick(window.undo_button, Qt.MouseButton.LeftButton)
    assert window.features == [original]


def test_retrace_preview_can_be_cancelled_without_geometry_change(window):
    original = accept_line(window, "stream")
    QTest.mouseClick(window.edit_buttons["retrace"], Qt.MouseButton.LeftButton)
    assert window.edit_target == original["id"]
    assert len(window.anchors) >= 2
    window.move_anchor(len(window.anchors) - 1, 68, 43)
    preview(window)
    assert window.features == [original]
    assert "cancel" in window.clear_button.text().lower()
    QTest.mouseClick(window.clear_button, Qt.MouseButton.LeftButton)
    assert window.features == [original]
    assert not window.anchors and window.preview is None and window.edit_target is None


def test_retrace_apply_replaces_line_without_creating_duplicate(window):
    original = accept_line(window, "manual")
    window.begin_retrace()
    window.move_anchor(len(window.anchors) - 1, 68, 43)
    preview(window)
    QTest.mouseClick(window.accept_button, Qt.MouseButton.LeftButton)
    assert len(window.features) == 1
    changed = window.features[0]
    assert changed["id"] == original["id"]
    assert changed["coordinates"] != original["coordinates"]
    assert changed["anchors"][-1] == list(window.terrain.xy(68, 43))
    assert changed["provenance"][-1]["operation"] == "retrace"


def test_insert_delete_split_join_reverse_workflow(window):
    window.param_widgets["spacing"].setValue(20)
    original = accept_line(window, anchors=((8, 25), (40, 25), (70, 25)))
    original_count = len(original["coordinates"])
    row_a, col_a = window.terrain.rc(*original["coordinates"][1][:2])
    row_b, col_b = window.terrain.rc(*original["coordinates"][2][:2])
    QTest.mouseClick(window.edit_buttons["insert"], Qt.MouseButton.LeftButton)
    add_map_anchor(window, (row_a + row_b) / 2, (col_a + col_b) / 2 + .55)
    assert len(window.features[0]["coordinates"]) == original_count + 1
    assert window.selected_vertex == 2
    QTest.mouseClick(window.edit_buttons["remove"], Qt.MouseButton.LeftButton)
    assert window.features[0]["coordinates"] == original["coordinates"]
    window.choose_vertex(2)
    QTest.mouseClick(window.edit_buttons["split"], Qt.MouseButton.LeftButton)
    assert len(window.features) == 2
    assert window.features[0]["coordinates"][-1] == window.features[1]["coordinates"][0]
    assert len({feature["id"] for feature in window.features}) == 2
    for index in range(window.feature_list.count()):
        window.feature_list.item(index).setSelected(True)
    assert window.edit_buttons["join"].isEnabled()
    QTest.mouseClick(window.edit_buttons["join"], Qt.MouseButton.LeftButton)
    assert len(window.features) == 1
    assert window.features[0]["coordinates"] == original["coordinates"]
    QTest.mouseClick(window.edit_buttons["reverse"], Qt.MouseButton.LeftButton)
    assert window.features[0]["coordinates"] == list(reversed(original["coordinates"]))
    QTest.mouseClick(window.undo_button, Qt.MouseButton.LeftButton)
    assert window.features[0]["coordinates"] == original["coordinates"]


def test_feature_snapping_and_alt_bypass(window):
    original = accept_line(window)
    select_tool(window, "manual")
    window.preferences["editing"]["raster_snap"] = False
    window.preferences["editing"]["snap_enabled"] = True
    window.add_anchor(8.25, 40.25)
    assert window.anchors == [(8, 40)]
    assert window._anchor_exact[0] == original["coordinates"][0][:2]
    window.clear_draft()
    position = map_position(window, 8.25, 40.25)
    QTest.mouseClick(window.canvas.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.AltModifier, position)
    assert len(window.anchors) == 1
    assert window.anchors[0] != (8, 40)
    assert np.linalg.norm(np.asarray(window.anchors[0]) - (8, 40)) < 1


def test_recovery_restores_unfinished_draft_without_overwriting_saved_project(window, tmp_path, monkeypatch):
    original = accept_line(window)
    saved = tmp_path / "accepted.tracer.json"
    window.project_path = str(saved)
    assert window.save()
    saved_bytes = saved.read_bytes()
    select_tool(window, "stream")
    add_map_anchor(window, 15, 50)
    add_map_anchor(window, 55, 50)
    draft = copy.deepcopy(window.settings()["draft"])
    window.save_recovery()
    entries = window.recovery_store.list_entries()
    assert len(entries) == 1
    assert entries[0]["draft_anchor_count"] == 2
    assert saved.read_bytes() == saved_bytes
    window.clear_draft()
    window.features = []
    window.refresh_features()
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **kw: (a[3][0], True))
    window.recover_work()
    wait_idle(window)
    assert window.features == [original]
    assert window.settings()["draft"] == draft
    assert window.project_path == str(saved)
    assert window.dirty, "Recovered unsaved work must be saved explicitly"
    assert saved.read_bytes() == saved_bytes


def test_explicit_save_preserves_active_correction_draft(window, tmp_path):
    window.param_widgets["spacing"].setValue(10)
    original = accept_line(window, anchors=((8, 30), (40, 30), (70, 30)))
    window.begin_segment()
    window.pick_segment_boundary(1)
    window.pick_segment_boundary(len(original["coordinates"]) - 2)
    window.add_anchor(35, 34)
    draft = copy.deepcopy(window.settings()["draft"])
    saved = tmp_path / "correction.tracer.json"
    window.project_path = str(saved)
    assert window.save()
    assert load_project(saved)["settings"]["draft"] == draft
    window.clear_draft()
    window.open_project(str(saved))
    wait_idle(window)
    assert window.features == [original]
    assert window.settings()["draft"] == draft
    assert window.edit_target == original["id"]
    assert window.segment_range == tuple(draft["segment_range"])
    assert not window.dirty


def test_all_preferences_tabs_apply_and_roundtrip_without_changing_source_xyz(window, tmp_path):
    original = accept_line(window)
    raster_before = Path(window.terrain.path).read_bytes()
    dialog = PreferencesDialog(window.preferences, window.terrain, window)
    dialog.show()
    assert [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())] == ["Terrain & CRS", "Display", "Editing", "Recovery", "Export"]
    desired = {
        ("display", "palette"): "viridis", ("display", "stretch"): "custom",
        ("display", "low"): 80., ("display", "high"): 140., ("display", "altitude"): 32.,
        ("display", "shade_strength"): .4, ("display", "gamma"): 1.2,
        ("display", "multidirectional"): True, ("display", "vertical_units"): "m",
        ("display", "contour_interval"): 5., ("editing", "snap_enabled"): False,
        ("editing", "snap_radius"): 12., ("editing", "raster_snap"): False,
        ("editing", "auto_preview"): False, ("editing", "join_tolerance"): 2.,
        ("editing", "history_limit"): 120, ("session", "autosave_seconds"): 5,
        ("session", "remember_view"): False, ("export", "scope"): "all",
        ("export", "target_crs"): "EPSG:32614", ("export", "z_scale"): .3048,
    }
    for index in range(dialog.tabs.count()):
        dialog.tabs.setCurrentIndex(index)
        QApplication.processEvents()
    for key, value in desired.items():
        widget = dialog.widgets[key]
        if isinstance(widget, QComboBox):
            widget.setCurrentIndex(widget.findData(value))
        elif isinstance(widget, QCheckBox):
            widget.setChecked(value)
        elif isinstance(widget, QLineEdit):
            widget.setText(value)
        else:
            widget.setValue(value)
    buttons = dialog.findChild(QDialogButtonBox)
    QTest.mouseClick(buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton)
    assert dialog.result() == QDialog.DialogCode.Accepted
    window.apply_preferences(dialog.preferences)
    wait_idle(window)
    assert window.features == [original]
    assert Path(window.terrain.path).read_bytes() == raster_before
    assert window.autosave_timer.interval() == 5000
    assert window.canvas.contours
    for (group, key), value in desired.items():
        assert window.preferences[group][key] == value
    saved = tmp_path / "preferences.tracer.json"
    window.project_path = str(saved)
    assert window.save()
    preferences = copy.deepcopy(window.preferences)
    window.open_project(str(saved))
    wait_idle(window)
    assert window.preferences == preferences
    assert window.features == [original]
    assert not window.dirty
    dialog.deleteLater()


def test_source_content_identity_rejects_changed_dem_with_same_grid(window, tmp_path):
    original = accept_line(window)
    window.terrain.fingerprint()
    saved = tmp_path / "identity.tracer.json"
    window.project_path = str(saved)
    assert window.save()
    old_terrain = window.terrain
    with rasterio.open(window.terrain.path, "r+") as source:
        values = source.read(1)
        values[0, 0] += 5
        source.write(values, 1)
    window.open_project(str(saved))
    wait_idle(window)
    assert window.test_errors, "A changed DEM must not silently replace a fingerprinted source"
    window.test_errors.clear()
    assert window.terrain is old_terrain
    assert window.features == [original]


def test_cancelling_worker_discards_late_success_and_restores_controls(window):
    original = accept_line(window)
    released = threading.Event()
    delivered = []

    def delayed_result():
        assert released.wait(5), "Test failed to release the background worker"
        return "late preview"

    window.start_job("Test cancellable calculation", delayed_result, delivered.append)
    assert window.busy and window.canvas.locked
    QTest.mouseClick(window.cancel_button, Qt.MouseButton.LeftButton)
    released.set()
    wait_idle(window)
    assert delivered == []
    assert window.features == [original]
    assert not window.canvas.locked
    assert window.open_button.isEnabled() and window.export_button.isEnabled()


def test_export_settings_apply_scope_crs_and_explicit_z_scale_only_to_copy(window, tmp_path, monkeypatch):
    first = accept_line(window)
    second = accept_line(window, anchors=((8, 50), (70, 50)))
    window.feature_list.item(0).setCheckState(Qt.CheckState.Unchecked)
    originals = copy.deepcopy(window.features)
    window.preferences["export"].update(scope="all", target_crs="EPSG:32614", z_scale=.3048)
    destination = tmp_path / "transformed.shp"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (str(destination), "ESRI Shapefile with Z (*.shp)"))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    window.export()
    assert destination.is_file()
    expected = transform_features(originals, window.terrain.crs, "EPSG:32614", z_scale=.3048)
    with shapefile.Reader(str(destination)) as reader:
        assert len(reader) == 2
        for shape, feature in zip(reader.shapes(), expected):
            assert np.allclose(shape.points, np.asarray(feature["coordinates"])[:, :2], rtol=0, atol=1e-8)
            assert list(shape.z) == [point[2] for point in feature["coordinates"]]
    assert rasterio.crs.CRS.from_wkt(destination.with_suffix(".prj").read_text()).to_epsg() == 32614
    assert window.features == originals
