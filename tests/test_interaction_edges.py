"""Regressions for native anchor precision and correction-draft state safety.

These exercise application actions and real Qt list selection independently of
other UI test modules, using only generated rasters and isolated state folders.
"""
from copy import deepcopy
import math
import os
import time

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from tracertool.app import MainWindow
from tracertool.project import new_feature
from tracertool.tracing import TraceParams, trace


@pytest.fixture(scope='session')
def interaction_qt():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def wait_for_job(window):
    deadline = time.monotonic() + 10
    while window.busy and time.monotonic() < deadline:
        QTest.qWait(10)
    assert not window.busy, 'The background operation did not complete.'
    QApplication.processEvents()


@pytest.fixture
def interaction_window(interaction_qt, tmp_path, monkeypatch):
    errors = []
    monkeypatch.setattr(MainWindow, 'error', lambda self, message: errors.append(str(message)))
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Discard)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: errors.append(str(a[-1])))
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: ('', ''))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a, **k: ('', ''))
    path = tmp_path / 'interaction.tif'
    rr, cc = np.mgrid[:50, :50]
    data = (200 - rr + cc * .25).astype('float32')
    with rasterio.open(path, 'w', driver='GTiff', width=50, height=50, count=1,
                       dtype='float32', crs='EPSG:32615',
                       transform=from_origin(500000, 4500000, 1, 1)) as dataset:
        dataset.write(data, 1)
        dataset.set_band_unit(1, 'm')
    window = MainWindow()
    window.interaction_errors = errors
    window.show()
    interaction_qt.processEvents()
    window.install_terrain(window.load_terrain_image(path))
    window.preferences['editing']['raster_snap'] = False
    window.preferences['editing']['snap_enabled'] = False
    window.param_widgets['spacing'].setValue(30)
    interaction_qt.processEvents()
    yield window
    wait_for_job(window)
    window.clear_draft()
    window.dirty = False
    window.close()
    window.deleteLater()
    interaction_qt.processEvents()


def make_feature(window, points, kind='manual', name='Fixture line'):
    params = TraceParams(spacing=30)
    return new_feature(name, kind, trace(window.terrain, points, 'manual', params), params)


def install_features(window, features):
    window.features = deepcopy(features)
    window.selected = features[0]['id']
    window.refresh_features()
    window.select_feature(features[0]['id'])
    QApplication.processEvents()


def preview(window, points):
    window.set_tool('manual')
    for row, col in points:
        window.add_anchor(row, col)
    window.trace_preview()
    wait_for_job(window)
    assert window.preview is not None, window.interaction_errors
    assert not window.interaction_errors
    return window.preview


@pytest.mark.parametrize('points', [
    [(5.1, 5.1), (5.4, 5.4)],
    [(5.1, 5.1), (12.2, 12.2), (5.4, 5.4)],
])
def test_manual_native_guides_preserve_same_cell_and_revisited_cell(interaction_window, points):
    window = interaction_window
    result = preview(window, points)
    expected = [list(window.terrain.xy(*point)) for point in points]
    # Large vertex spacing means these short segments need no inserted vertices.
    assert len(result.coordinates) == len(expected)
    np.testing.assert_allclose(np.array(result.coordinates)[:, :2], expected, rtol=0, atol=1e-8)
    np.testing.assert_allclose(result.anchors, expected, rtol=0, atol=1e-8)
    for x, y, z in result.coordinates:
        assert z == window.terrain.sample(x, y)
    window.accept_preview()
    np.testing.assert_allclose(np.array(window.features[0]['coordinates'])[:, :2], expected, rtol=0, atol=1e-8)
    assert not window.interaction_errors


def test_exact_anchor_preview_metrics_match_accepted_geometry(interaction_window):
    window = interaction_window
    result = preview(window, [(5.4, 5.4), (5.2, 20.2)])
    expected_length = math.dist(result.coordinates[0][:2], result.coordinates[-1][:2])
    assert result.metrics['length'] == pytest.approx(expected_length, abs=1e-9)
    assert result.metrics['elevation_start'] == result.coordinates[0][2]
    assert result.metrics['elevation_end'] == result.coordinates[-1][2]
    window.accept_preview()
    feature = window.features[0]
    assert feature['metrics']['length'] == pytest.approx(expected_length, abs=1e-9)


def test_switching_lines_between_segment_boundaries_resets_or_locks_selection(interaction_window):
    window = interaction_window
    first = make_feature(window, [(5, 5), (10, 5), (15, 5), (20, 5), (25, 5)], name='Five vertices')
    second = make_feature(window, [(5, 15), (25, 15)], name='Two vertices')
    install_features(window, [first, second])
    window.begin_segment()
    window.pick_segment_boundary(3)
    second_item = window.feature_list.item(1)
    QTest.mouseClick(window.feature_list.viewport(), Qt.MouseButton.LeftButton,
                     pos=window.feature_list.visualItemRect(second_item).center())
    QApplication.processEvents()
    if window.selected == first['id']:
        # Locking the list is valid: the next boundary must still refer to first.
        window.pick_segment_boundary(1)
        assert window.edit_target == first['id']
        assert window.segment_range == (1, 3)
    else:
        # Allowing selection is also valid, but it must clear the old index 3.
        assert window.selected == second['id']
        assert window.segment_first is None
        assert window.segment_range is None
        window.pick_segment_boundary(1)
        assert window.segment_range is None
        window.pick_segment_boundary(0)
        assert window.edit_target == second['id']
        assert window.segment_range == (0, 1)
    assert not window.interaction_errors


@pytest.mark.parametrize('kind', ['ridge', 'slope_break'])
@pytest.mark.parametrize('operation', ['retrace', 'segment'])
def test_pinned_retrace_kind_dropdown_disabled_and_restored(interaction_window, kind, operation):
    window = interaction_window
    feature = make_feature(window, [(5, 20), (15, 20), (25, 20)], kind=kind)
    install_features(window, [feature])
    if operation == 'retrace':
        window.begin_retrace()
    else:
        window.begin_segment()
        window.pick_segment_boundary(0)
        window.pick_segment_boundary(2)
    assert window.kind() == kind
    assert window.break_mode.currentData() == kind
    assert not window.break_mode.isEnabled(), 'The displayed kind must not offer changes while the trace kind is pinned.'
    window.clear_draft()
    assert window.break_mode.isEnabled(), 'New traces must regain the choice of breakline kind.'


@pytest.mark.parametrize('draft_stage', ['first_boundary', 'correction'])
def test_history_and_delete_actions_cannot_mutate_a_correction_target(interaction_window, draft_stage):
    window = interaction_window
    feature = make_feature(window, [(5, 20), (15, 20), (25, 20), (35, 20)])
    install_features(window, [feature])
    historical = deepcopy(feature)
    historical['coordinates'] = historical['coordinates'][:2]
    window.history = [[historical]]
    window.future = [[]]
    window.begin_segment()
    window.pick_segment_boundary(1)
    if draft_stage == 'correction':
        window.pick_segment_boundary(3)
    before = deepcopy(window.features)
    history, future = deepcopy(window.history), deepcopy(window.future)
    window.undo()
    window.redo()
    window.delete_feature()
    assert window.features == before
    assert window.history == history
    assert window.future == future
    assert not window.undo_button.isEnabled()
    assert not window.redo_button.isEnabled()
    assert not window.delete_button.isEnabled()
    assert not window.interaction_errors


def test_local_manual_correction_keeps_fractional_boundary_xyz_and_undo(interaction_window):
    window = interaction_window
    feature = make_feature(window, [(5, 10), (10.2, 10.3), (20.1, 10.2), (30, 10)])
    install_features(window, [feature])
    window.begin_segment()
    window.pick_segment_boundary(1)
    window.pick_segment_boundary(2)
    original_anchors = deepcopy(window.anchors)
    window.move_anchor(0, 15, 15)
    assert window.anchors == original_anchors, 'Correction boundaries must not move with draggable guides.'
    window.add_anchor(15, 14)
    window.trace_preview()
    wait_for_job(window)
    assert window.preview is not None, window.interaction_errors
    window.accept_preview()
    edited = window.features[0]
    assert edited['id'] == feature['id']
    assert edited['coordinates'][:2] == feature['coordinates'][:2]
    assert edited['coordinates'][-2:] == feature['coordinates'][-2:]
    assert len(edited['coordinates']) > len(feature['coordinates'])
    window.undo()
    assert window.features == [feature]
    assert not window.interaction_errors
