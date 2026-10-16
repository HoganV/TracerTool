"""Desktop line controls, legacy parameter restoration, and spacing readouts."""

import copy
from dataclasses import asdict
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton

from test_app import qt_app, terrain_path, window, accept_line, wait_idle
from tracertool.project import load_project, save_project
from tracertool.tracing import TraceParams


LEGACY_PARAMETERS = {"corridor": 30., "smoothing": 1.2, "terrain_weight": 8.,
                     "spacing": 3., "simplify": .5}


def test_line_control_defaults_match_engine_and_reset_button(window):
    defaults = asdict(TraceParams())
    assert defaults["spacing"] == 3
    assert defaults["smoothing"] == 0
    assert defaults["line_smoothing"] == 0
    assert defaults["simplify"] == .75
    assert asdict(window.params()) == defaults
    assert not window.advanced_panel.isVisible()
    for key, value in {"spacing": 64, "smoothing": 40, "line_smoothing": 0, "simplify": 5}.items():
        window.param_widgets[key].setValue(value)
    reset = next(button for button in window.findChildren(QPushButton)
                 if button.text() == "Restore sensible defaults")
    QTest.mouseClick(reset, Qt.MouseButton.LeftButton)
    assert asdict(window.params()) == defaults


def test_levee_preset_sets_distinct_terrain_and_line_controls(window):
    window.param_widgets["line_smoothing"].setValue(0)
    window.param_widgets["smoothing"].setValue(40)
    window.param_widgets["spacing"].setValue(64)
    index = window.preset.findText("Levee / embankment")
    assert index >= 0
    window.preset.setCurrentIndex(index)
    window.preset.activated.emit(index)
    assert asdict(window.params()) == {
        "corridor": 12, "smoothing": 0, "line_smoothing": 0,
        "terrain_weight": 10, "spacing": 3, "simplify": .5, "relax_anchors": True,
    }
    assert "Target spacing: 3" in window.units_label.text()


@pytest.mark.parametrize("include_settings", [True, False])
def test_legacy_project_and_feature_restore_zero_line_smoothing_without_geometry_changes(window, tmp_path, include_settings):
    original = accept_line(window)
    original["parameters"] = dict(LEGACY_PARAMETERS)
    settings = copy.deepcopy(window.settings())
    if include_settings:
        settings["parameters"] = dict(LEGACY_PARAMETERS)
    else:
        settings.pop("parameters")
    path = tmp_path / "legacy.tracer.json"
    save_project(path, window.terrain.path, [original], settings)
    saved_bytes = path.read_bytes()
    window.param_widgets["line_smoothing"].setValue(25)
    window.open_project(str(path))
    wait_idle(window)
    assert window.features == [original]
    assert window.param_widgets["line_smoothing"].value() == 0
    assert not window.dirty
    assert path.read_bytes() == saved_bytes
    if include_settings:
        assert asdict(window.params()) == {**LEGACY_PARAMETERS, "line_smoothing": 0, "relax_anchors": False}

    window.param_widgets["line_smoothing"].setValue(8)
    window.param_widgets["spacing"].setValue(64)
    window.select_feature(original["id"])
    window.begin_retrace()
    assert window.edit_target == original["id"]
    assert asdict(window.params()) == {**LEGACY_PARAMETERS, "line_smoothing": 0, "relax_anchors": False}
    assert window.features == [original]
    window.clear_draft()
    assert window.features == [original]
    assert "line_smoothing" not in load_project(path)["features"][0]["parameters"]


@pytest.mark.parametrize("values", [
    {"smoothing": 0, "line_smoothing": 0, "spacing": 64, "simplify": 0},
    {"smoothing": 50, "line_smoothing": 50, "spacing": 2000, "simplify": 200},
    {"smoothing": 12.25, "line_smoothing": 6.75, "spacing": 31.25, "simplify": 1.25},
])
def test_extended_control_ranges_roundtrip_feature_settings_and_retrace(window, tmp_path, values):
    source_bytes = Path(window.terrain.path).read_bytes()
    for key, value in values.items():
        window.param_widgets[key].setValue(value)
        assert window.param_widgets[key].value() == value, f"{key} silently clamped the requested value"
    desired = asdict(window.params())
    original = accept_line(window, kind="manual")
    assert original["parameters"] == desired
    path = tmp_path / "extended.tracer.json"
    window.project_path = str(path)
    assert window.save()
    saved = load_project(path)
    assert saved["settings"]["parameters"] == desired
    assert saved["features"] == [original]

    window.reset_parameters()
    window.open_project(str(path))
    wait_idle(window)
    assert asdict(window.params()) == desired
    assert window.features == [original]
    assert not window.dirty
    window.select_feature(original["id"])
    window.begin_retrace()
    assert asdict(window.params()) == desired
    assert window.features == [original]
    window.clear_draft()
    assert Path(window.terrain.path).read_bytes() == source_bytes


def test_legacy_unfinished_draft_reopens_with_zero_line_smoothing(window, tmp_path):
    window.tool_buttons["manual"].click()
    window.add_anchor(8, 40)
    window.add_anchor(70, 40)
    settings = copy.deepcopy(window.settings())
    settings["parameters"] = dict(LEGACY_PARAMETERS)
    settings["draft"]["parameters"] = dict(LEGACY_PARAMETERS)
    path = tmp_path / "legacy-draft.tracer.json"
    save_project(path, window.terrain.path, [], settings)
    window.clear_draft()
    window.param_widgets["line_smoothing"].setValue(50)
    window.open_project(str(path))
    wait_idle(window)
    assert window.anchors == [(8, 40), (70, 40)]
    assert window.kind() == "manual"
    assert asdict(window.params()) == {**LEGACY_PARAMETERS, "line_smoothing": 0, "relax_anchors": False}
    assert window.preview is None
    assert window.features == []


def test_spacing_readout_reports_accepted_geometry_independently_of_next_target(window):
    original = accept_line(window, kind="manual")
    distances = np.linalg.norm(np.diff(np.asarray(original["coordinates"])[:, :2], axis=0), axis=1)
    expected = (f"Spacing: {np.median(distances):.1f} median "
                f"({distances.min():.1f}–{distances.max():.1f} {window.terrain.units})")
    assert expected in window.metrics_label.text()
    assert "Target spacing: 3" in window.units_label.text()
    window.param_widgets["spacing"].setValue(40)
    assert "Target spacing: 40" in window.units_label.text()
    assert expected in window.metrics_label.text()
    assert window.features == [original]


@pytest.mark.parametrize("styled", [False, True])
def test_trace_sidebar_never_scrolls_horizontally_when_controls_gain_focus(window, qt_app, styled):
    from PySide6.QtWidgets import QScrollArea
    from tracertool.app import STYLE
    original_style = qt_app.style().objectName()
    original_stylesheet = qt_app.styleSheet()
    sidebar = next(area for area in window.findChildren(QScrollArea)
                   if area.widget() is window.left_panel)
    try:
        if styled:
            qt_app.setStyle("Fusion")
            qt_app.setStyleSheet(STYLE)
        window.resize(1040, 690)
        for tool in ("breakline", "edit", "stream", "manual", "pan"):
            window.set_tool(tool)
            window.preset.setCurrentIndex(window.preset.findText("Levee / embankment"))
            window.param_widgets["simplify"].setFocus()
            qt_app.processEvents()
            assert sidebar.horizontalScrollBar().maximum() == 0
            assert window.left_panel.x() == 0
    finally:
        qt_app.setStyleSheet(original_stylesheet)
        qt_app.setStyle(original_style)
        qt_app.processEvents()
