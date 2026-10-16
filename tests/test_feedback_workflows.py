"""Mouse/keyboard acceptance for rough-guide editing and live elevation colors."""
from copy import deepcopy
from dataclasses import asdict
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_app import qt_app, terrain_path, window, wait_idle, map_position, accept_line
from tracertool.project import save_project, load_project
from tracertool.tracing import validate_segments


def shortcut(window, key):
    window.canvas.setFocus()
    QTest.keyClick(window.canvas, key, Qt.KeyboardModifier.ControlModifier)
    QApplication.processEvents()


@pytest.mark.parametrize('tool', ['stream', 'breakline', 'manual'])
def test_guide_add_insert_drag_delete_undo_redo(window, tool):
    window.set_tool(tool)
    for p in [(8, 40), (70, 40)]:
        QTest.mouseClick(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=map_position(window, *p))
    assert len(window.anchors) == 2
    shortcut(window, Qt.Key.Key_Z)
    assert len(window.anchors) == 1
    shortcut(window, Qt.Key.Key_Z)
    assert not window.anchors and window.redo_button.isEnabled()
    shortcut(window, Qt.Key.Key_Y)
    shortcut(window, Qt.Key.Key_Y)
    assert window.anchors == [(8, 40), (70, 40)]
    window.guide_edit_button.click()
    QTest.mouseClick(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=map_position(window, 35, 40))
    assert window.anchors == [(8, 40), (35, 40), (70, 40)]
    start, end = map_position(window, 35, 40), map_position(window, 36, 43)
    QTest.mousePress(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window.canvas.viewport(), end, delay=30)
    QTest.mouseRelease(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
    assert window.anchors[1] == (36, 43)
    shortcut(window, Qt.Key.Key_Z)
    assert window.anchors[1] == (35, 40)
    shortcut(window, Qt.Key.Key_Y)
    assert window.anchors[1] == (36, 43)
    QTest.keyClick(window.canvas, Qt.Key.Key_Delete)
    assert window.anchors == [(8, 40), (70, 40)]
    shortcut(window, Qt.Key.Key_Z)
    assert len(window.anchors) == 3
    assert not window.features
    window.clear_draft()


def test_guide_edit_invalidates_preview_and_accept_finishes_history(window):
    window.set_tool('stream')
    window.add_anchor(8, 43)
    window.add_anchor(70, 43)
    window.trace_preview(); wait_idle(window)
    assert window.preview is not None
    assert max(abs(c[1] - 40) for c in window.preview.cells) < 3
    window.move_anchor(1, 69, 42)
    assert window.preview is None and not window.accept_button.isEnabled()
    shortcut(window, Qt.Key.Key_Z)
    assert window.anchors[1] == (70, 43)
    window.trace_preview(); wait_idle(window)
    window.accept_preview()
    assert len(window.features) == 1
    assert not window.draft_history and not window.draft_future
    shortcut(window, Qt.Key.Key_Z)
    assert not window.features
    shortcut(window, Qt.Key.Key_Y)
    assert len(window.features) == 1


def test_wide_radius_and_rough_guides_roundtrip_without_clamping(window, tmp_path):
    window.set_tool('stream')
    window.param_widgets['corridor'].setValue(5000)
    assert window.params().corridor == 5000
    assert not window.advanced_panel.isVisible()
    assert window.params().smoothing == window.params().line_smoothing == 0
    window.add_anchor(8, 44); window.add_anchor(70, 44)
    path = tmp_path / 'draft.tracer.json'
    settings = window.settings()
    save_project(path, window.terrain.path, [], settings)
    window.open_project(str(path)); wait_idle(window)
    assert window.anchors == [(8, 44), (70, 44)]
    assert window.params().corridor == 5000
    assert window.params().relax_anchors
    window.trace_preview(); wait_idle(window)
    assert window.preview is not None
    assert window.preview.metrics['spacing_max_pixels'] <= 3.000001
    validate_segments(window.terrain, window.preview.coordinates)
    window.clear_draft()


def test_snapped_guide_survives_draft_save_and_retrace(window, tmp_path):
    feature = accept_line(window, kind='manual', anchors=((8, 35), (70, 35)))
    window.set_tool('stream')
    window.add_anchor(8, 35)
    window.add_anchor(70, 44)
    assert window._fixed_anchor_indices == {0}
    path = tmp_path / 'snapped.tracer.json'
    save_project(path, window.terrain.path, window.features, window.settings())
    window.open_project(str(path)); wait_idle(window)
    assert window._fixed_anchor_indices == {0}
    window.trace_preview(); wait_idle(window)
    assert window.preview.coordinates[0] == feature['coordinates'][0]
    window.accept_preview()
    current = window.current_feature()
    assert current['fixed_anchor_indices'] == [0]
    window.begin_retrace()
    assert window._fixed_anchor_indices == {0}
    window.clear_draft()


def test_segment_boundary_points_stay_fixed_through_guide_history(window):
    feature = accept_line(window)
    window.begin_segment(); window.pick_segment_boundary(2); window.pick_segment_boundary(10)
    original = deepcopy(window.anchors)
    window.add_anchor(25, 42)
    assert window._fixed_anchor_indices == {0, 2}
    window.move_anchor(0, 12, 43)
    assert window.anchors[0] == original[0]
    window.choose_anchor(2); window.delete_anchor()
    assert len(window.anchors) == 3
    shortcut(window, Qt.Key.Key_Z)
    assert window.anchors == original
    assert window._fixed_anchor_indices == {0, 1}
    shortcut(window, Qt.Key.Key_Y)
    assert len(window.anchors) == 3
    assert window.features == [feature]
    window.clear_draft()


def image_bytes(window):
    image = window.canvas.raster_item.pixmap().toImage()
    return bytes(image.constBits())


def settle_view(window):
    QTest.qWait(250); wait_idle(window); QTest.qWait(220); wait_idle(window)


def test_view_minmax_refreshes_after_zoom_pan_and_fit_without_changing_data(window):
    original_data = window.terrain.data.copy()
    feature = accept_line(window)
    original_features = deepcopy(window.features)
    window.palette_choice.setCurrentIndex(window.palette_choice.findData('ras'))
    window.range_choice.setCurrentIndex(window.range_choice.findData('view'))
    window.change_display_controls(); settle_view(window)
    full = image_bytes(window)
    window.canvas.scale(4, 4)
    window.canvas.centerOn(QPointF(40, 40))
    window.canvas.viewChanged.emit(); settle_view(window)
    zoomed = image_bytes(window)
    assert zoomed != full
    window.canvas.centerOn(QPointF(15, 15)); settle_view(window)
    assert image_bytes(window) != zoomed
    window.canvas.fit(); settle_view(window)
    assert image_bytes(window) == full
    np.testing.assert_array_equal(window.terrain.data, original_data)
    assert window.features == original_features
    assert window.current_feature() == feature


def test_tooltips_explain_limits_and_advanced_can_be_opened(window):
    for name in ['corridor', 'smoothing', 'line_smoothing', 'terrain_weight', 'spacing', 'simplify']:
        assert len(window.param_widgets[name].toolTip()) > 100
    assert '0–200' in window.param_widgets['simplify'].toolTip()
    assert not window.advanced_panel.isVisible()
    window.advanced_button.click()
    assert window.advanced_panel.isVisible()
    assert window.param_widgets['smoothing'].value() == 0
    assert window.param_widgets['line_smoothing'].value() == 0


def test_empty_guide_edit_can_start_again_after_undo(window):
    window.set_tool('stream')
    window.add_anchor(8, 40); window.add_anchor(70, 40)
    window.guide_edit_button.click()
    shortcut(window, Qt.Key.Key_Z); shortcut(window, Qt.Key.Key_Z)
    assert not window.canvas.guide_edit
    assert not window.guide_edit_button.isChecked()
    QTest.mouseClick(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=map_position(window, 9, 40))
    assert window.anchors == [(9, 40)]
    window.clear_draft()


def test_invalid_custom_toolbar_range_keeps_previous_preferences(window, monkeypatch):
    errors = []
    monkeypatch.setattr(window, 'error', lambda message: errors.append(message))
    window.preferences['display']['low'] = 100
    window.preferences['display']['high'] = 100
    original = deepcopy(window.preferences)
    window.range_choice.setCurrentIndex(window.range_choice.findData('custom'))
    window.change_display_controls()
    assert errors and 'maximum' in errors[0]
    assert window.preferences == original
    assert window.range_choice.currentData() == original['display']['stretch']


def test_palette_and_view_range_changes_preserve_trace_preview(window):
    window.set_tool('stream')
    window.add_anchor(8, 43); window.add_anchor(70, 43)
    window.trace_preview(); wait_idle(window)
    preview = window.preview
    assert preview is not None and window.accept_button.isEnabled()
    for control, value in [(window.palette_choice, 'ras'), (window.range_choice, 'view')]:
        control.setCurrentIndex(control.findData(value))
        window.change_display_controls(); settle_view(window)
        assert window.preview is preview
        assert window.accept_button.isEnabled()
    window.accept_preview()
    assert window.features[0]['coordinates'] == preview.coordinates


def test_auto_preview_waits_for_view_render(window, monkeypatch):
    import time
    real_rgb = window.terrain.rgb
    def slow_rgb(*args, **kwargs):
        time.sleep(.65)
        return real_rgb(*args, **kwargs)
    monkeypatch.setattr(window.terrain, 'rgb', slow_rgb)
    window.preferences['display']['stretch'] = 'view'
    window.preferences['editing']['auto_preview'] = True
    window.set_tool('manual')
    window.add_anchor(8, 40); window.add_anchor(70, 40)
    window.schedule_view_stretch()
    deadline = time.monotonic() + 5
    while window.preview is None and time.monotonic() < deadline:
        QTest.qWait(30)
    wait_idle(window)
    assert window.preview is not None
    window.clear_draft()


def test_view_stretch_settles_without_resizing_itself_forever(window, monkeypatch):
    calls = []
    rgb = window.terrain.rgb
    def counted_rgb(*args, **kwargs):
        calls.append(kwargs.get('view_bounds'))
        return rgb(*args, **kwargs)
    monkeypatch.setattr(window.terrain, 'rgb', counted_rgb)
    window.range_choice.setCurrentIndex(window.range_choice.findData('view'))
    window.change_display_controls()
    # Iterate so both Python worker callbacks and Qt's timers get time.
    for _ in range(60):
        QTest.qWait(25)
    wait_idle(window)
    assert len(calls) <= 3
    assert not window._view_stretch_pending
    assert not window.view_debounce.isActive()
    assert window.param_widgets['corridor'].isEnabled()


def test_quick_insert_then_drag_guide_does_not_insert_a_second_point(window):
    window.set_tool('stream')
    window.add_anchor(8, 40); window.add_anchor(70, 40)
    window.guide_edit_button.click()
    point, destination = map_position(window, 35, 40), map_position(window, 36, 43)
    QTest.mouseClick(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert len(window.anchors) == 3
    QTest.mouseDClick(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseMove(window.canvas.viewport(), destination, delay=30)
    QTest.mouseRelease(window.canvas.viewport(), Qt.MouseButton.LeftButton, pos=destination)
    assert window.anchors == [(8, 40), (36, 43), (70, 40)]
    window.clear_draft()
