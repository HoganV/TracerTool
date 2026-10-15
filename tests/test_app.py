"""Desktop workflows through real Qt signals, map input, and worker threads."""

import copy
import json
import os
from pathlib import Path
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
import rasterio
from rasterio.transform import from_origin
import shapefile

from tracertool.app import MainWindow
from tracertool.project import load_project
from tracertool.tracing import validate_segments


@pytest.fixture(scope="session")
def qt_app():
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    return application


def wait_idle(window, timeout=10):
    deadline = time.monotonic() + timeout
    while window.busy and time.monotonic() < deadline:
        QTest.qWait(10)
    assert not window.busy, "Background terrain operation did not finish"
    QApplication.processEvents()


def write_terrain(path, *, crs="EPSG:32615"):
    rows, columns = np.mgrid[:80, :80]
    values = (100 + (columns - 40) ** 2 * 0.02 - rows * 0.15).astype("float32")
    values[30:35, 10:15] = -9999
    values[45, 45] = -9999
    with rasterio.open(path, "w", driver="GTiff", height=80, width=80, count=1,
                       dtype="float32", crs=crs, transform=from_origin(500000, 4500000, 1, 1),
                       nodata=-9999) as dataset:
        dataset.write(values, 1)
    return path


@pytest.fixture
def terrain_path(tmp_path):
    return write_terrain(tmp_path / "valley.tif")


@pytest.fixture
def window(qt_app, terrain_path, monkeypatch):
    errors = []
    monkeypatch.setattr(MainWindow, "error", lambda self, message: errors.append(str(message)))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: errors.append(str(a[-1])))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Discard)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **kw: ("", ""))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: ("", ""))
    view = MainWindow()
    view.test_errors = errors
    view.show()
    qt_app.processEvents()
    view.install_terrain(view.load_terrain_image(terrain_path))
    qt_app.processEvents()
    view.canvas.fit()
    yield view
    wait_idle(view)
    view.dirty = False
    view.close()
    view.deleteLater()
    qt_app.processEvents()
    assert not errors, f"Unexpected application errors: {errors}"


def map_position(window, row, column):
    position = window.canvas.mapFromScene(QPointF(column + 0.5, row + 0.5))
    assert window.canvas.viewport().rect().contains(position)
    return position


def add_map_anchor(window, row, column):
    QTest.mouseClick(window.canvas.viewport(), Qt.MouseButton.LeftButton,
                     pos=map_position(window, row, column))


def select_tool(window, kind):
    tool = "breakline" if kind in ("ridge", "slope_break") else kind
    QTest.mouseClick(window.tool_buttons[tool], Qt.MouseButton.LeftButton)
    if tool == "breakline":
        window.break_mode.setCurrentIndex(window.break_mode.findData(kind))
    QApplication.processEvents()
    window.canvas.fit()


def accept_line(window, kind="manual", anchors=((8, 40), (70, 40))):
    select_tool(window, kind)
    for row, column in anchors:
        add_map_anchor(window, row, column)
    assert window.anchors == list(anchors)
    assert window.trace_button.isEnabled()
    QTest.mouseClick(window.trace_button, Qt.MouseButton.LeftButton)
    wait_idle(window)
    assert window.preview is not None, window.test_errors
    assert window.accept_button.isEnabled()
    QTest.mouseClick(window.accept_button, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert window.preview is None
    assert window.anchors == []
    return copy.deepcopy(window.features[-1])


@pytest.mark.parametrize("kind", ["stream", "ridge", "slope_break", "manual"])
def test_map_trace_accept_undo_redo(window, kind):
    assert not window.dirty
    assert not window.export_button.isEnabled()
    feature = accept_line(window, kind)
    assert feature["kind"] == kind
    assert len(feature["coordinates"]) >= 2
    assert feature["coordinates"][0][:2] == list(window.terrain.xy(8, 40))
    assert feature["coordinates"][-1][:2] == list(window.terrain.xy(70, 40))
    assert window.selected == feature["id"]
    assert window.feature_list.count() == 1
    assert window.dirty and window.export_button.isEnabled()
    QTest.mouseClick(window.undo_button, Qt.MouseButton.LeftButton)
    assert window.features == []
    assert window.redo_button.isEnabled()
    QTest.mouseClick(window.redo_button, Qt.MouseButton.LeftButton)
    assert window.features == [feature]
    assert window.feature_list.count() == 1


def test_canvas_keyboard_removes_anchors_and_accepts_preview(window):
    select_tool(window, "stream")
    add_map_anchor(window, 8, 40)
    add_map_anchor(window, 40, 40)
    add_map_anchor(window, 70, 40)
    QTest.keyClick(window.canvas, Qt.Key.Key_Backspace)
    assert window.anchors == [(8, 40), (40, 40)]
    QTest.keyClick(window.canvas, Qt.Key.Key_Return)
    wait_idle(window)
    assert window.preview is not None
    QTest.keyClick(window.canvas, Qt.Key.Key_Return)
    assert len(window.features) == 1
    add_map_anchor(window, 15, 30)
    QTest.keyClick(window.canvas, Qt.Key.Key_Escape)
    assert not window.anchors and window.preview is None


def test_drag_vertex_resamples_source_elevation_and_is_undoable(window):
    original = accept_line(window, anchors=((8, 25), (40, 25), (70, 25)))
    select_tool(window, "edit")
    start = map_position(window, 8, 25)
    finish = map_position(window, 12, 22)
    QTest.mousePress(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window.canvas.viewport(), finish)
    QTest.mouseRelease(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=finish)
    edited = window.features[0]
    x, y = window.terrain.xy(12, 22)
    assert edited["coordinates"][0] == [x, y, window.terrain.sample(x, y)]
    assert edited["metrics"]["manually_edited"] is True
    assert edited["warnings"]
    QTest.mouseClick(window.undo_button, Qt.MouseButton.LeftButton)
    assert window.features == [original]
    QTest.mouseClick(window.redo_button, Qt.MouseButton.LeftButton)
    assert window.features[0]["coordinates"][0] == [x, y, window.terrain.sample(x, y)]


def test_invalid_anchor_and_vertex_stay_off_nodata(window):
    original = accept_line(window)
    select_tool(window, "stream")
    add_map_anchor(window, 32, 12)
    assert window.anchors == []
    window.move_vertex(0, 32, 12)
    assert window.features == [original]


def test_vertex_drag_rejects_exact_nodata_corner_without_changing_line(window, tmp_path):
    # The proposed diagonal touches (45, 45) only at the pixel corner. A
    # regularly spaced sampling check can miss this zero-length intersection.
    window.param_widgets["spacing"].setValue(10)
    original = accept_line(window, anchors=((42, 47), (42, 43)))
    assert len(original["coordinates"]) == 2
    assert window.terrain.valid[42, 47] and window.terrain.valid[47, 42]
    assert not window.terrain.valid[45, 45]
    x, y = window.terrain.xy(47, 42)
    proposed = [original["coordinates"][0], [x, y, window.terrain.sample(x, y)]]
    with pytest.raises(ValueError, match="NoData"):
        validate_segments(window.terrain, proposed)
    window.project_path = str(tmp_path / "safe-line.tracer.json")
    assert window.save()
    old_history = copy.deepcopy(window.history)
    select_tool(window, "edit")
    start = map_position(window, 42, 43)
    finish = map_position(window, 47, 42)
    QTest.mousePress(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window.canvas.viewport(), finish)
    QTest.mouseRelease(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=finish)
    assert any("NoData" in message for message in window.test_errors)
    window.test_errors.clear()
    assert window.features == [original]
    assert window.history == old_history
    assert not window.dirty


def test_save_and_async_reopen_restore_lines_and_settings(window, tmp_path, monkeypatch):
    feature = accept_line(window)
    window.param_widgets["spacing"].setValue(4.5)
    window.view_style.setCurrentText("Hillshade")
    wait_idle(window)
    window.azimuth.setValue(235)
    window.exaggeration.setValue(2.0)
    destination = tmp_path / "session.tracer.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (str(destination), "TracerTool project"))
    QTest.mouseClick(window.save_button, Qt.MouseButton.LeftButton)
    assert destination.is_file()
    assert not window.dirty
    assert load_project(destination)["features"] == [feature]
    window.features.clear()
    window.refresh_features()
    window.param_widgets["spacing"].setValue(9)
    window.open_project(str(destination))
    wait_idle(window)
    assert window.features == [feature]
    assert window.param_widgets["spacing"].value() == 4.5
    assert window.view_style.currentText() == "Hillshade"
    assert window.azimuth.value() == 235
    assert window.exaggeration.value() == 2
    assert window.project_path == str(destination)
    assert not window.dirty


def test_changed_persisted_settings_mark_project_dirty(window, tmp_path):
    window.project_path = str(tmp_path / "session.tracer.json")
    assert window.save()
    assert not window.dirty
    window.param_widgets["spacing"].setValue(4)
    assert window.dirty
    assert window.save()
    window.view_style.setCurrentText("Slope")
    wait_idle(window)
    assert window.dirty


def test_small_raster_fitted_view_can_reopen_its_saved_project(window, tmp_path):
    tiny_path = tmp_path / "tiny.tif"
    with rasterio.open(tiny_path, "w", driver="GTiff", height=3, width=3, count=1,
                       dtype="float32", crs="EPSG:32615", transform=from_origin(500000, 4500000, 1, 1)) as dataset:
        dataset.write(np.arange(9, dtype="float32").reshape(3, 3), 1)
    window.install_terrain(window.load_terrain_image(tiny_path))
    window.canvas.fit()
    fitted_scale = window.canvas.transform().m11()
    assert fitted_scale > 100  # Fit legitimately exceeds ordinary wheel zoom.
    destination = tmp_path / "tiny.tracer.json"
    window.project_path = str(destination)
    assert window.save()
    window.open_project(str(destination))
    wait_idle(window)
    assert not window.test_errors
    assert window.canvas.transform().m11() == pytest.approx(fitted_scale)
    assert not window.dirty


def test_canceling_unfinished_draft_keeps_anchors_and_current_terrain(window, monkeypatch):
    select_tool(window, "stream")
    add_map_anchor(window, 8, 40)
    old_terrain = window.terrain
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Cancel)
    QTest.mouseClick(window.open_button, Qt.MouseButton.LeftButton)
    assert window.terrain is old_terrain
    assert window.anchors == [(8, 40)]
    assert not window.busy
    window.clear_draft()


def test_failed_raster_load_keeps_existing_project(window, tmp_path):
    original = accept_line(window)
    old_terrain = window.terrain
    bad_raster = tmp_path / "broken.tif"
    bad_raster.write_text("not a raster")
    window.open_terrain(str(bad_raster))
    wait_idle(window)
    assert window.test_errors
    window.test_errors.clear()
    assert window.terrain is old_terrain
    assert window.features == [original]
    assert window.dirty


@pytest.mark.parametrize("bad_settings", [{"parameters": []}, {"view": {"scale": "bad", "center": [1, 2]}}])
def test_malformed_project_settings_do_not_replace_live_state(window, tmp_path, bad_settings):
    original = accept_line(window)
    window.project_path = str(tmp_path / "original.tracer.json")
    assert window.save()
    old_terrain = window.terrain
    old_project_path = window.project_path
    old_history = copy.deepcopy(window.history)
    malformed = json.loads(Path(old_project_path).read_text())
    malformed["features"] = []
    malformed["settings"] = bad_settings
    destination = tmp_path / "malformed.tracer.json"
    destination.write_text(json.dumps(malformed))
    window.open_project(str(destination))
    wait_idle(window)
    assert window.test_errors, "Malformed settings must be reported to the user"
    window.test_errors.clear()
    assert window.terrain is old_terrain
    assert window.features == [original]
    assert window.project_path == old_project_path
    assert window.history == old_history


def test_missing_raster_can_be_relinked_and_saved(window, terrain_path, tmp_path, monkeypatch):
    original = accept_line(window)
    destination = tmp_path / "session.tracer.json"
    window.project_path = str(destination)
    assert window.save()
    relocated = tmp_path / "relocated.tif"
    terrain_path.rename(relocated)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **kw: (str(relocated), "GeoTIFF"))
    window.open_project(str(destination))
    wait_idle(window)
    assert Path(window.terrain.path) == relocated
    assert window.features == [original]
    assert window.dirty, "Relinking changes the project and must enable a save prompt"
    assert window.save()
    assert load_project(destination)["terrain_path"] == str(relocated)


def test_relink_rejects_different_crs_without_relabeling_existing_lines(window, terrain_path, tmp_path, monkeypatch):
    original = accept_line(window)
    destination = tmp_path / "session.tracer.json"
    window.project_path = str(destination)
    assert window.save()
    old_terrain = window.terrain
    terrain_path.rename(tmp_path / "moved-original.tif")
    replacement = write_terrain(tmp_path / "different-crs.tif", crs="EPSG:32614")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **kw: (str(replacement), "GeoTIFF"))
    window.open_project(str(destination))
    wait_idle(window)
    assert window.test_errors, "CRS mismatch must be reported instead of relabeling saved geometry"
    window.test_errors.clear()
    assert window.terrain is old_terrain
    assert window.features == [original]


def test_export_only_checked_lines_as_polylinez(window, tmp_path, monkeypatch):
    first = accept_line(window)
    accept_line(window, anchors=((8, 50), (70, 50)))
    window.feature_list.item(1).setCheckState(Qt.CheckState.Unchecked)
    destination = tmp_path / "checked.shp"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (str(destination), "ESRI Shapefile with Z (*.shp)"))
    QTest.mouseClick(window.export_button, Qt.MouseButton.LeftButton)
    assert destination.is_file()
    with shapefile.Reader(str(destination)) as reader:
        assert len(reader) == 1
        assert reader.shapeType == shapefile.POLYLINEZ
        assert reader.record(0).as_dict()["line_id"] == first["id"]
        assert list(reader.shape(0).z) == [point[2] for point in first["coordinates"]]
