"""Native desktop workbench. All GIS data stays on the local machine."""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import traceback

import numpy as np
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QPointF, QEvent
from PySide6.QtGui import QAction, QKeySequence, QColor, QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QFileDialog,
    QMessageBox, QListWidget, QListWidgetItem, QAbstractItemView, QSplitter,
    QProgressBar, QScrollArea, QFrame, QButtonGroup, QToolButton, QGridLayout,
    QLineEdit, QDialog, QCheckBox,
)

from . import __version__
from .canvas import TerrainCanvas, ProfileWidget, COLORS
from .terrain import Terrain
from .tracing import TraceParams, default_params, trace, validate_segments
from .project import new_feature, save_project, load_project, export_shapefile, export_geojson
from .desktop_actions import DesktopActions
from .preferences import normalize_preferences, display_kwargs
from . import editing, project


STYLE = """
QMainWindow, QWidget { background: #13232c; color: #dfebe9; font-family: 'Segoe UI', 'DejaVu Sans', sans-serif; font-size: 12px; }
QMainWindow { background: #0c1b23; }
QLabel { background: transparent; }
QLabel#brand { font-size: 23px; font-weight: 700; color: #e8f5ef; }
QLabel#muted { color: #91aab5; font-size: 11px; }
QLabel#section { font-size: 10px; font-weight: 700; color: #86a6b3; letter-spacing: 2px; }
QLabel#message { background: #18323d; color: #c5dce5; border: 1px solid #2a4652; border-radius: 6px; padding: 10px; }
QPushButton, QToolButton { background: #203741; border: 1px solid #36515c; padding: 8px 11px; border-radius: 5px; color: #e0edeb; }
QPushButton:hover, QToolButton:hover { background: #2c4855; border-color: #61848e; }
QPushButton:checked { background: #28534e; border-color: #72c3ad; color: #e0fff0; }
QPushButton#primary { background: #a9dbc0; border-color: #a9dbc0; color: #102b26; font-weight: 700; }
QPushButton#primary:hover { background: #c3edd4; }
QPushButton#primary:disabled { background: #28443f; color: #6d8e83; border-color: #35534b; }
QPushButton:disabled, QToolButton:disabled { color: #617b86; background: #1a2c35; border-color: #293f49; }
QComboBox, QDoubleSpinBox { background: #0e202a; border: 1px solid #37515d; border-radius: 4px; padding: 5px; min-height: 20px; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView { selection-background-color: #31584f; }
QGroupBox { border: 1px solid #314751; border-radius: 6px; margin-top: 16px; padding: 12px 8px 8px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #a4bdc8; }
QListWidget { background: #0e2029; border: 1px solid #2c424d; border-radius: 4px; outline: none; }
QListWidget::item { padding: 9px 5px; border-bottom: 1px solid #1b323e; }
QListWidget::item:selected { background: #294d51; color: #f5fff9; }
QSplitter::handle { background: #0b1a22; width: 3px; }
QStatusBar { background: #0b1a22; color: #96b3c1; }
QProgressBar { border: none; background: #18303a; max-height: 4px; }
QProgressBar::chunk { background: #8ac7b2; }
QScrollArea { border: none; }
QScrollBar:vertical { background: #142630; width: 8px; }
QScrollBar::handle:vertical { background: #3f5e69; min-height: 20px; border-radius: 3px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QMenuBar, QMenu { background: #142630; }
QMenu::item:selected { background: #31584f; }
QToolTip { color: #edf7f1; background: #243e4b; border: 1px solid #527784; }
"""


class Worker(QThread):
    result = Signal(object)
    failure = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.result.emit(self.fn())
        except Exception as exc:
            traceback.print_exc()
            self.failure.emit(str(exc))


def label(text, name=None, wrap=False):
    out = QLabel(text)
    if name:
        out.setObjectName(name)
    out.setWordWrap(wrap)
    return out


class VerticalSidebar(QScrollArea):
    """Keep controls fully visible across platform fonts and display scaling."""

    def fit_content_width(self):
        if self.widget() is not None:
            width = self.widget().minimumSizeHint().width()
            width += self.verticalScrollBar().sizeHint().width() + 2 * self.frameWidth()
            self.setMinimumWidth(max(332, width))

    def eventFilter(self, watched, event):
        result = super().eventFilter(watched, event)
        if watched is self.widget() and event.type() in (
                QEvent.Type.LayoutRequest, QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self.fit_content_width()
        return result


class MainWindow(DesktopActions, QMainWindow):
    def __init__(self):
        super().__init__()
        self.terrain = None
        self.features = []
        self.anchors = []
        self.preview = None
        self.selected = None
        self.project_path = None
        self.dirty = False
        self.history = []
        self.future = []
        self.job = None
        self._callback = None
        self._refreshing = False
        self._restoring = False
        self._cancel_event = threading.Event()
        self.initialize_session()
        self.setWindowTitle(f"TracerTool {__version__}")
        self.resize(1460, 920)
        self.setMinimumSize(1040, 690)
        self._build_ui()
        self._build_actions()
        self.update_title()
        if self.recovery_warning:
            self.recovery_status.setText("Temporary recovery folder")
            self.recovery_status.setToolTip(self.recovery_warning)
            self.statusBar().showMessage(self.recovery_warning)
        entries = self.recovery_store.list_entries()
        if entries:
            self.recover_button.setText(f"Recover work ({len(entries)})")
            self.recover_button.show()

    def _build_ui(self):
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        top = QWidget()
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(20, 13, 20, 13)
        brand_layout = QVBoxLayout()
        brand_layout.setSpacing(1)
        brand_layout.addWidget(label("◈  TracerTool", "brand"))
        brand_layout.addWidget(label("TERRAIN  /  LINE WORKBENCH", "muted"))
        top_layout.addLayout(brand_layout)
        top_layout.addStretch()
        self.open_button = QPushButton("Open terrain")
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self.open_terrain_dialog)
        self.project_button = QPushButton("Open project")
        self.project_button.clicked.connect(self.open_project_dialog)
        self.save_button = QPushButton("Save project")
        self.save_button.clicked.connect(self.save)
        self.export_button = QPushButton("Export lines")
        self.export_button.clicked.connect(self.export)
        self.preferences_button = QPushButton("Settings")
        self.preferences_button.clicked.connect(self.open_preferences)
        for b in (self.open_button, self.project_button, self.save_button, self.export_button):
            top_layout.addWidget(b)
        top_layout.addWidget(self.preferences_button)
        self.recover_button = QPushButton("Recover work")
        self.recover_button.clicked.connect(self.recover_work)
        self.recover_button.hide()
        top_layout.addWidget(self.recover_button)
        outer.addWidget(top)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 0)
        self.progress.hide()
        outer.addWidget(self.progress)
        self.cancel_button = QPushButton("Cancel operation")
        self.cancel_button.clicked.connect(self.cancel_job)
        self.cancel_button.hide()
        outer.addWidget(self.cancel_button)

        split = QSplitter()
        outer.addWidget(split, 1)
        self.left_panel = QWidget()
        left = QVBoxLayout(self.left_panel)
        left.setContentsMargins(16, 17, 16, 16)
        left.setSpacing(9)
        left.addWidget(label("01   CHOOSE A TOOL", "section"))
        self.tool_group = QButtonGroup(self)
        self.tool_buttons = {}
        for key, title in [("pan", "↔   Navigate"), ("stream", "≈   Stream line"), ("breakline", "⌁   Breakline"), ("manual", "＋   Manual line"), ("edit", "◇   Edit vertices")]:
            b = QPushButton(title)
            b.setCheckable(True)
            b.setMinimumHeight(36)
            b.setStyleSheet("text-align: left;")
            b.clicked.connect(lambda checked=False, k=key: self.set_tool(k))
            self.tool_group.addButton(b)
            self.tool_buttons[key] = b
            left.addWidget(b)
        self.tool_buttons["pan"].setChecked(True)
        self.break_mode = QComboBox()
        self.break_mode.addItem("Ridge / embankment crest", "ridge")
        self.break_mode.addItem("Slope break / bank edge", "slope_break")
        self.break_mode.currentIndexChanged.connect(self.invalidate_preview)
        self.break_mode.hide()
        left.addWidget(self.break_mode)
        self.stream_engine = QComboBox()
        self.stream_engine.addItem("Stream engine: Legacy", "legacy")
        self.stream_engine.addItem("Stream engine: Auto (experimental)", "stream_auto")
        self.stream_engine.setToolTip("Auto is experimental and opt-in. It uses source-native terrain analysis, not the legacy numerical search controls. Review diagnostics; it never falls back to Legacy.")
        self.stream_engine.currentIndexChanged.connect(self.change_stream_engine)
        left.addWidget(self.stream_engine)
        self.instructions = label("Open terrain, then choose Stream line or Breakline. Scroll to zoom; drag to explore.", "message", True)
        left.addWidget(self.instructions)
        left.addSpacing(8)
        left.addWidget(label("02   GUIDE THE TRACE", "section"))
        self.anchor_label = label("No anchors placed", "muted", True)
        left.addWidget(self.anchor_label)
        guide_row = QHBoxLayout()
        self.guide_edit_button = QPushButton("Edit guide points")
        self.guide_edit_button.setCheckable(True)
        self.guide_edit_button.setToolTip("Drag a numbered guide to move it. In this mode, click a guide edge to insert a point; select a point and press Delete to remove it. Ctrl+Z/Y undo and redo guide edits.")
        self.guide_edit_button.toggled.connect(self.toggle_guide_edit)
        self.guide_delete_button = QPushButton("Remove point")
        self.guide_delete_button.clicked.connect(self.delete_anchor)
        guide_row.addWidget(self.guide_edit_button)
        guide_row.addWidget(self.guide_delete_button)
        left.addLayout(guide_row)
        self.trace_button = QPushButton("Trace preview   ↵")
        self.trace_button.setObjectName("primary")
        self.trace_button.clicked.connect(self.trace_preview)
        left.addWidget(self.trace_button)
        row = QHBoxLayout()
        self.accept_button = QPushButton("Accept line")
        self.accept_button.clicked.connect(self.accept_preview)
        self.clear_button = QPushButton("Clear draft")
        self.clear_button.clicked.connect(self.clear_draft)
        row.addWidget(self.accept_button)
        row.addWidget(self.clear_button)
        left.addLayout(row)
        params = QGroupBox("Trace settings · working cells")
        form = QFormLayout(params)
        form.setSpacing(8)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.preset = QComboBox()
        self.preset.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.preset.setMinimumContentsLength(10)
        self.preset.addItems(["Balanced", "Levee / embankment", "Fine ditch / crest", "Broad channel", "Noisy terrain"])
        self.preset.activated.connect(self.apply_preset)
        form.addRow("Starting preset", self.preset)
        self.relax_guides = QCheckBox("Let rough guide points follow terrain")
        self.relax_guides.setChecked(True)
        self.relax_guides.setToolTip("Move rough assisted guide points toward terrain features within the search radius, including the ends. Snapped connections and correction boundaries stay fixed. Uncheck to force the line through every guide; manual lines always follow exact guides.")
        self.relax_guides.toggled.connect(self.invalidate_preview)
        form.addRow(self.relax_guides)
        self.param_widgets = {}
        spec = [
            ("corridor", "Search radius", 1, sys.float_info.max, 12, "Allowed search distance from the rough guide, in working cells. Increase it when the guide misses the channel or crest; a wider search can also reach neighboring features and take longer. Minimum 1; no application upper cap. Does not set vertex spacing or terrain feature scale."),
            ("terrain_weight", "Terrain attraction", 0, 1000, 8, "How strongly the route favors terrain features over a shorter route. Higher values follow stronger channel/crest evidence; lower values stay more direct. Range 0–1000; 0 uses distance and guide proximity only. Start at 8."),
            ("spacing", "Target spacing", .25, 2000, 3, "Desired distance between output vertices along the line, in working cells. Smaller values give more editable vertices; larger values give fewer. Range 0.25–2000. Independent of search radius; bends, fixed connections and NoData may require closer vertices. Dense vertices do not add DEM accuracy."),
            ("simplify", "Bend tolerance", 0, 200, .75, "Allowed plan-view deviation when simplifying the route, in working cells. Range 0–200; 0 retains every raster bend. Smaller values preserve detail and may add vertices; larger values can cut real bends. Start at 0.75. Never permits crossing NoData."),
            ("smoothing", "Terrain smoothing", 0, 50, 0, "Gaussian smoothing radius for terrain guidance, in working cells. Range 0–50; default 0 (off). Higher values suppress small features and can shift a channel or crest. Source elevations and exported Z stay unchanged."),
            ("line_smoothing", "Line smoothing", 0, 50, 0, "Smoothing radius for assisted line geometry, in working cells. Range 0–50; default 0 (off). Higher values soften stair-steps but can round real bends. Manual lines and fixed connections remain exact; NoData stays impassable."),
        ]
        self.advanced_button = QToolButton()
        self.advanced_button.setText("Advanced · Legacy smoothing")
        self.advanced_button.setCheckable(True)
        self.advanced_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_button.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_panel = QWidget()
        advanced_form = QFormLayout(self.advanced_panel)
        advanced_form.setContentsMargins(0, 0, 0, 0)
        advanced_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.advanced_panel.hide()
        self.advanced_button.toggled.connect(lambda checked: (self.advanced_panel.setVisible(checked), self.advanced_button.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)))
        for name, title, low, high, default, tip in spec:
            spin = QDoubleSpinBox()
            spin.setRange(low, high)
            spin.setDecimals(2)
            spin.setSingleStep(0.5)
            spin.setValue(default)
            spin.setFixedWidth(110)
            spin.setToolTip(f"<qt>{tip}</qt>")
            spin.valueChanged.connect(self.invalidate_preview)
            title_label = QLabel(title)
            title_label.setToolTip(f"<qt>{tip}</qt>")
            (advanced_form if name in {'smoothing', 'line_smoothing'} else form).addRow(title_label, spin)
            self.param_widgets[name] = spin
        form.addRow(self.advanced_button)
        form.addRow(self.advanced_panel)
        left.addWidget(params)
        self.units_label = label("Distances will adapt to the terrain resolution.", "muted", True)
        left.addWidget(self.units_label)
        defaults = QPushButton("Restore sensible defaults")
        defaults.clicked.connect(self.reset_parameters)
        left.addWidget(defaults)
        left.addStretch()
        left.addWidget(label("LOCAL FILES • NO ACCOUNT • OPEN SOURCE", "muted", True))
        left_scroll = VerticalSidebar()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(self.left_panel)
        left_scroll.setMinimumWidth(332)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        split.addWidget(left_scroll)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        self.view_controls = QWidget()
        controls = QHBoxLayout(self.view_controls)
        controls.setContentsMargins(12, 8, 12, 8)
        self.view_style = QComboBox()
        self.view_style.addItems(["Terrain", "Hillshade", "Slope", "Elevation"])
        self.view_style.currentTextChanged.connect(self.render_terrain)
        controls.addWidget(self.view_style)
        controls.addWidget(label("Sun"))
        self.azimuth = QDoubleSpinBox()
        self.azimuth.setRange(0, 359)
        self.azimuth.setDecimals(0)
        self.azimuth.setValue(315)
        self.azimuth.setSuffix("°")
        self.azimuth.editingFinished.connect(self.render_terrain)
        controls.addWidget(self.azimuth)
        controls.addWidget(label("Relief"))
        self.exaggeration = QDoubleSpinBox()
        self.exaggeration.setRange(0.1, 10)
        self.exaggeration.setValue(1)
        self.exaggeration.setSuffix("×")
        self.exaggeration.editingFinished.connect(self.render_terrain)
        controls.addWidget(self.exaggeration)
        controls.addStretch()
        fit = QPushButton("Fit  F")
        fit.clicked.connect(lambda: self.canvas.fit())
        controls.addWidget(fit)
        center_layout.addWidget(self.view_controls)
        self.palette_controls = QWidget()
        display_row = QHBoxLayout(self.palette_controls)
        display_row.setContentsMargins(12, 0, 12, 8)
        self.palette_choice = QComboBox()
        for name, key in [("Earth", "earth"), ("RAS-inspired", "ras"), ("Topographic", "topographic"), ("Spectral", "spectral"), ("Viridis", "viridis"), ("Inferno", "inferno"), ("Grayscale", "gray"), ("Ocean", "ocean")]:
            self.palette_choice.addItem(name, key)
        self.range_choice = QComboBox()
        for name, key in [("Terrain range · 1–99%", "percentile"), ("Terrain min–max", "minmax"), ("View min–max", "view"), ("Custom range", "custom")]:
            self.range_choice.addItem(name, key)
        self.range_choice.setToolTip("View min–max updates the elevation colors to the visible valid terrain as you pan and zoom. Custom limits are set in Settings → Display.")
        self.palette_choice.activated.connect(self.change_display_controls)
        self.range_choice.activated.connect(self.change_display_controls)
        display_row.addWidget(self.palette_choice)
        display_row.addWidget(self.range_choice)
        display_row.addStretch()
        center_layout.addWidget(self.palette_controls)
        self.canvas = TerrainCanvas()
        self.canvas.anchorAdded.connect(self.add_anchor)
        self.canvas.positionChanged.connect(self.show_position)
        self.canvas.finishRequested.connect(self.enter_action)
        self.canvas.removeAnchorRequested.connect(self.remove_anchor)
        self.canvas.cancelRequested.connect(self.clear_draft)
        self.canvas.featureSelected.connect(self.select_feature)
        self.canvas.vertexMoved.connect(self.move_vertex)
        self.canvas.vertexSelected.connect(self.choose_vertex)
        self.canvas.vertexInsertRequested.connect(self.insert_vertex)
        self.canvas.anchorMoved.connect(self.move_anchor)
        self.canvas.anchorSelected.connect(self.choose_anchor)
        self.canvas.anchorInsertRequested.connect(self.insert_anchor)
        self.canvas.viewChanged.connect(self.schedule_view_stretch)
        self.canvas.segmentPointSelected.connect(self.pick_segment_boundary)
        self.canvas.deleteRequested.connect(self.delete_context)
        center_layout.addWidget(self.canvas, 1)
        self.map_caption = label("   Scroll to zoom  ·  Right-drag to pan  ·  F to fit", "muted")
        self.map_caption.setMinimumHeight(30)
        center_layout.addWidget(self.map_caption)
        split.addWidget(center)

        self.right_panel = QWidget()
        right = QVBoxLayout(self.right_panel)
        right.setContentsMargins(14, 18, 14, 16)
        right.addWidget(label("TERRAIN SOURCE", "section"))
        self.source_label = label("No terrain loaded", None, True)
        self.source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        right.addWidget(self.source_label)
        self.source_detail = label("Open a single-band elevation GeoTIFF.", "muted", True)
        right.addWidget(self.source_detail)
        right.addSpacing(18)
        feature_header = QHBoxLayout()
        feature_header.addWidget(label("03   REVIEW YOUR LINES", "section"))
        self.count_label = label("0", "muted")
        feature_header.addStretch()
        feature_header.addWidget(self.count_label)
        right.addLayout(feature_header)
        self.feature_list = QListWidget()
        self.feature_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.feature_list.setMinimumHeight(130)
        self.feature_list.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.feature_list.currentItemChanged.connect(self.list_selection)
        self.feature_list.itemChanged.connect(self.item_changed)
        self.feature_list.itemSelectionChanged.connect(self.update_buttons)
        right.addWidget(self.feature_list, 2)
        right.addWidget(label("Double-click a name to rename. Uncheck to hide.", "muted", True))
        actionrow = QHBoxLayout()
        self.undo_button = QPushButton("Undo")
        self.undo_button.clicked.connect(self.undo)
        self.redo_button = QPushButton("Redo")
        self.redo_button.clicked.connect(self.redo)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_feature)
        for b in (self.undo_button, self.redo_button, self.delete_button):
            actionrow.addWidget(b)
        right.addLayout(actionrow)
        edit_grid = QGridLayout()
        self.edit_buttons = {}
        for i, (key, text, fn) in enumerate([
            ("retrace", "Retrace line", self.begin_retrace),
            ("segment", "Correct segment", self.begin_segment),
            ("insert", "Insert vertex", self.begin_insert),
            ("remove", "Remove vertex", self.delete_vertex),
            ("split", "Split here", self.split_line),
            ("join", "Join selected", self.join_lines),
            ("reverse", "Reverse line", self.reverse_line),
        ]):
            button = QPushButton(text)
            button.clicked.connect(fn)
            self.edit_buttons[key] = button
            edit_grid.addWidget(button, i // 2, i % 2)
        right.addLayout(edit_grid)
        right.addSpacing(14)
        right.addWidget(label("ELEVATION PROFILE", "section"))
        self.profile = ProfileWidget()
        right.addWidget(self.profile)
        self.metrics_label = label("Select or preview a line.", "muted", True)
        right.addWidget(self.metrics_label)
        self.qa_label = label("Every trace is a draft for review.", "message", True)
        right.addWidget(self.qa_label)
        right.addStretch()
        help_button = QPushButton("Workflow & shortcuts")
        help_button.clicked.connect(self.show_help)
        right.addWidget(help_button)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setWidget(self.right_panel)
        right_scroll.setMinimumWidth(285)
        split.addWidget(right_scroll)
        split.setSizes([305, 850, 300])
        split.setStretchFactor(1, 1)
        self.setCentralWidget(container)
        self.statusBar().showMessage("Ready · open a terrain file to begin")
        self.coord_label = QLabel("")
        self.statusBar().addPermanentWidget(self.coord_label)
        self.recovery_status = QLabel("")
        self.statusBar().addPermanentWidget(self.recovery_status)
        self.update_buttons()

    def _build_actions(self):
        self.actions = []
        menu = self.menuBar().addMenu("File")
        for text, shortcut, fn in [("Open terrain…", "Ctrl+O", self.open_terrain_dialog), ("Open project…", "Ctrl+Shift+O", self.open_project_dialog), ("Save project", "Ctrl+S", self.save), ("Save project as…", "Ctrl+Shift+S", lambda: self.save(True)), ("Export lines…", "Ctrl+E", self.export)]:
            action = QAction(text, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(fn)
            menu.addAction(action)
            self.actions.append(action)
        menu.addSeparator()
        menu.addAction("Project settings…", self.open_preferences)
        menu.addAction("Recover work…", self.recover_work)
        menu.addAction("Reproject terrain copy…", self.reproject_terrain)
        edit = self.menuBar().addMenu("Edit")
        for text, shortcut, fn in [("Undo", "Ctrl+Z", self.undo), ("Redo", "Ctrl+Y", self.redo), ("Delete selected line", "Ctrl+Delete", self.delete_feature)]:
            action = QAction(text, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(fn)
            edit.addAction(action)
        edit.addSeparator()
        edit.addAction("Retrace selected line…", self.begin_retrace)
        edit.addAction("Correct a segment…", self.begin_segment)
        edit.addAction("Insert a vertex", self.begin_insert)
        edit.addAction("Remove selected vertex", self.delete_vertex)
        edit.addAction("Split at selected vertex", self.split_line)
        edit.addAction("Join two selected lines", self.join_lines)
        edit.addAction("Reverse selected line", self.reverse_line)
        self.menuBar().addAction("Help", self.show_help)

    @property
    def busy(self):
        return self.job is not None

    def start_job(self, message, fn, callback, *, quiet=False):
        if self.busy:
            return
        self._callback = callback
        self._cancel_event = threading.Event()
        self.job = Worker(fn, self)
        self.job.result.connect(self.job_result)
        self.job.failure.connect(self.job_error)
        self.job.finished.connect(self.job_finished)
        self.statusBar().showMessage(message)
        # A viewport color refresh must not resize its own viewport by adding
        # progress widgets. That otherwise schedules another refresh forever.
        if not quiet:
            self.progress.show()
            self.cancel_button.show()
        self.canvas.locked = True
        for w in (self.left_panel, self.right_panel, self.view_controls, self.palette_controls):
            w.setEnabled(False)
        self.update_buttons()
        self.job.start()

    def job_result(self, result):
        try:
            if self._callback and not self._cancel_event.is_set():
                self._callback(result)
        except Exception as exc:
            self.error(str(exc))

    def job_error(self, message):
        self.sync_display_controls()
        if not self._cancel_event.is_set():
            self.error(message)

    def cancel_job(self):
        if self.busy:
            self._preview_pending = False
            self.preview_debounce.stop()
            self._cancel_event.set()
            self.statusBar().showMessage("Cancelling · waiting for the current calculation to return safely…")

    def job_finished(self):
        job, self.job = self.job, None
        self._callback = None
        if job:
            job.deleteLater()
        self.progress.hide()
        self.cancel_button.hide()
        self.canvas.locked = False
        for w in (self.left_panel, self.right_panel, self.canvas, self.view_controls, self.palette_controls):
            w.setEnabled(True)
        self.update_buttons()
        if self._cancel_event.is_set():
            self.statusBar().showMessage("Operation cancelled · previous work preserved")
        elif self.statusBar().currentMessage() == "Updating terrain display…":
            self.statusBar().showMessage("Display updated")
        if self._close_when_idle:
            QTimer.singleShot(0, self.close)
        else:
            if self._preview_pending:
                self.preview_debounce.start(50)
            if self._view_stretch_pending:
                self.view_debounce.start(150)

    def error(self, message):
        self.statusBar().showMessage(message)
        QMessageBox.warning(self, "TracerTool", message)

    def update_title(self):
        name = Path(self.project_path).name if self.project_path else "Untitled project"
        self.setWindowTitle(f"{'• ' if self.dirty else ''}{name} — TracerTool {__version__}")

    def mark_dirty(self):
        self.dirty = True
        self.update_title()
        self.schedule_recovery()

    def update_buttons(self):
        loaded = self.terrain is not None
        busy = self.busy
        if not self.anchors and self.guide_edit_button.isChecked():
            self.guide_edit_button.setChecked(False)
        self.open_button.setEnabled(not busy)
        self.project_button.setEnabled(not busy)
        self.save_button.setEnabled(loaded and not busy)
        self.export_button.setEnabled(bool(self.features) and not busy)
        self.preferences_button.setEnabled(not busy)
        self.trace_button.setEnabled(loaded and len(self.anchors) >= 2 and not busy)
        self.accept_button.setEnabled(self.preview is not None and not busy)
        self.clear_button.setEnabled(bool(self.anchors or self.edit_target or self.segment_first is not None) and not busy)
        self.delete_button.setEnabled(self.selected is not None and not busy)
        has_draft = bool(self.anchors or self.edit_target or self.segment_first is not None)
        editing_draft = has_draft or bool(self.draft_history or self.draft_future)
        self.undo_button.setEnabled(bool(self.draft_history if editing_draft else self.history) and not busy)
        self.redo_button.setEnabled(bool(self.draft_future if editing_draft else self.future) and not busy)
        self.guide_edit_button.setEnabled(bool(self.anchors) and not busy)
        self.guide_delete_button.setEnabled(self.selected_anchor is not None and bool(self.anchors) and not busy)
        self.delete_button.setEnabled(self.selected is not None and not busy and not has_draft)
        self.feature_list.setEnabled(not busy and not has_draft)
        self.break_mode.setEnabled(not busy and self._draft_kind is None)
        auto = self.kind() == 'stream' and self.stream_engine.currentData() == 'stream_auto'
        self.stream_engine.setVisible(self.canvas.mode == 'stream' or self._draft_kind == 'stream')
        for name, widget in self.param_widgets.items():
            widget.setEnabled(not auto or name in {'spacing', 'simplify'})
        self.preset.setEnabled(not auto)
        self.relax_guides.setEnabled(not auto)
        self.advanced_button.setEnabled(not auto)
        self.accept_button.setText("Apply correction" if self.edit_target else "Accept line")
        self.clear_button.setText("Cancel edit" if self.edit_target else "Clear draft")
        if hasattr(self, "edit_buttons"):
            for key, button in self.edit_buttons.items():
                enabled = self.selected is not None and not busy and not has_draft
                if key in {"remove", "split"}:
                    enabled = enabled and self.selected_vertex is not None
                if key == "join":
                    enabled = not busy and len(self.feature_list.selectedItems()) == 2 and not has_draft
                button.setEnabled(enabled)

    def check_discard(self):
        if self.busy:
            return False
        if self.dirty or self.anchors:
            answer = QMessageBox.question(self, "Save your work?", "Save the current project, including any unfinished draft, before continuing?", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
            if answer == QMessageBox.StandardButton.Cancel:
                return False
            if answer == QMessageBox.StandardButton.Save:
                return self.save()
        return True

    def open_terrain_dialog(self):
        if not self.check_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open elevation terrain", "", "GeoTIFF (*.tif *.tiff);;All files (*)")
        if path:
            self.open_terrain(path)

    def open_terrain(self, path, project=None):
        try:
            preferences = normalize_preferences(project.get("settings", {}).get("preferences")) if project else self.preferences
            dimension = int(preferences["session"]["working_dimension"])
        except ValueError as exc:
            self.error(str(exc))
            return
        self.start_job("Reading elevation and preparing shaded terrain…", lambda: self.load_terrain_image(path, dimension), lambda pair: self.install_terrain(pair, project))

    @staticmethod
    def load_terrain_image(path, max_dimension=2400):
        terrain = Terrain.load(path, max_dimension=max_dimension, compute_fingerprint=True)
        return terrain, terrain.rgb()

    def install_terrain(self, pair, project=None):
        incoming, _ = pair
        if project:
            settings = project.get("settings", {})
            self.validate_settings(settings)
            normalize_preferences(settings.get("preferences"))
            reference = settings.get("terrain_reference")
            if reference:
                from rasterio.crs import CRS
                same_crs = CRS.from_wkt(reference["crs_wkt"]) == incoming.crs if reference.get("crs_wkt") else incoming.crs is None
                same_bounds = np.allclose(reference["bounds"], incoming.bounds, rtol=0, atol=1e-5)
                same_shape = reference["original_width"] == incoming.metadata["original_width"] and reference["original_height"] == incoming.metadata["original_height"]
                same_res = np.allclose(reference["original_resolution_xy"], incoming.metadata["original_resolution_xy"], rtol=1e-9, atol=1e-9)
                if not (same_crs and same_bounds and same_shape and same_res):
                    raise ValueError("The terrain does not match this project's CRS, extent, or source grid. Locate the original terrain; existing line coordinates will not be relabeled.")
                if reference.get("source_sha256") and reference["source_sha256"] != incoming.metadata.get("source_sha256"):
                    raise ValueError("The terrain file contents have changed since this project was saved. Locate the original TIFF to preserve the meaning of saved elevations.")
            elif project.get("_relinked"):
                raise ValueError("This older project has no terrain reference metadata. Restore its original terrain before opening it; automatic relinking cannot verify its coordinates.")
        incoming_preferences = normalize_preferences(project.get("settings", {}).get("preferences")) if project else copy.deepcopy(self.default_preferences)
        incoming_settings = project.get("settings", {}) if project else {}
        # Prepare every fallible display operation before replacing live work.
        incoming.rgb(incoming_settings.get("style", "Terrain"), azimuth=incoming_settings.get("azimuth", 315), z_factor=incoming_settings.get("z_factor", 1), **display_kwargs(incoming_preferences))
        self.make_contours(incoming, incoming_preferences["display"]["contour_interval"])
        self.recovery_debounce.stop()
        self.discard_recovery()
        self._restoring = True
        self.terrain, rgb = pair
        self.features = copy.deepcopy(project.get("features", [])) if project else []
        self.project_path = project.get("_project_path") if project else None
        self.anchors = []
        self.preview = None
        self.selected = None
        self.selected_vertex = None
        self.edit_target = None
        self.segment_range = None
        self.segment_first = None
        self._draft_kind = None
        self._anchor_exact = {}
        self._fixed_anchor_indices = set()
        self.preferences = incoming_preferences
        self.stream_engine.blockSignals(True)
        self.stream_engine.setCurrentIndex(0)
        self.stream_engine.blockSignals(False)
        self.sync_display_controls()
        self.history.clear()
        self.future.clear()
        self.view_style.blockSignals(True)
        self.view_style.setCurrentText("Terrain")
        self.view_style.blockSignals(False)
        self.azimuth.setValue(315)
        self.exaggeration.setValue(1)
        self.canvas.set_terrain(self.terrain, rgb)
        self.source_label.setText(Path(self.terrain.path).name)
        t = self.terrain
        finite = t.data[t.valid]
        self.source_detail.setText(f"{t.width:,} × {t.height:,} working cells\n{t.resolution:g} {t.units} / cell\n{t.crs.to_string() if t.crs else 'No coordinate system'}\nElevation {np.min(finite):,.2f} to {np.max(finite):,.2f}\nZ units: {t.metadata.get('vertical_units', t.metadata.get('band_units', 'source units'))}")
        self.source_detail.setToolTip(json.dumps(t.metadata, indent=2, default=str))
        self.reset_parameters()
        self.dirty = False
        self.set_tool("pan")
        self.refresh_features()
        self.clear_draft()
        self.update_title()
        if project:
            self.restore_settings(project.get("settings", {}))
        else:
            self.canvas.set_image(self.terrain.rgb(**display_kwargs(self.preferences)))
            self.canvas.set_contours(self.make_contours(self.terrain, self.preferences["display"]["contour_interval"]))
        self._restoring = False
        self.schedule_view_stretch()
        if project and (project.get("_relinked") or project.get("_recovered")):
            self.mark_dirty()
        if self.anchors:
            self.schedule_recovery()
        self.statusBar().showMessage(f"Loaded {Path(t.path).name} · choose a tracing tool")
        if t.crs is None or not t.crs.is_projected:
            self.qa_label.setText("View only: tracing requires a projected CRS. Use File → Reproject terrain copy, then open the new TIFF.")
        if t.metadata.get("resampled", False):
            self.qa_label.setText("This raster uses a reduced working grid. Review working resolution before tracing; exported elevations come from the source.")

    def open_project_dialog(self):
        if not self.check_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open TracerTool project", "", "TracerTool project (*.tracer.json *.json)")
        if path:
            self.open_project(path)

    def open_project(self, path):
        try:
            project = load_project(path, allow_missing_terrain=True)
            terrain_path = project["terrain_path"]
            if not Path(terrain_path).exists():
                replacement, _ = QFileDialog.getOpenFileName(self, "Locate missing terrain: " + Path(terrain_path).name, "", "GeoTIFF (*.tif *.tiff)")
                if not replacement:
                    return
                terrain_path = replacement
                project["_relinked"] = True
            project["_project_path"] = str(path)
            self.open_terrain(terrain_path, project)
        except Exception as exc:
            self.error(str(exc))

    def settings(self):
        center = self.canvas.mapToScene(self.canvas.viewport().rect().center())
        t = self.terrain
        reference = {"crs_wkt": t.crs.to_wkt() if t.crs else None, "bounds": list(t.bounds), "original_width": t.metadata["original_width"], "original_height": t.metadata["original_height"], "original_resolution_xy": t.metadata["original_resolution_xy"], "source_sha256": t.metadata.get("source_sha256")} if t else None
        values = {"parameters": vars(self.params()).copy(), "style": self.view_style.currentText(), "azimuth": self.azimuth.value(), "z_factor": self.exaggeration.value(), "view": {"center": [center.x(), center.y()], "scale": self.canvas.transform().m11()}, "terrain_reference": reference, "preferences": copy.deepcopy(self.preferences)}
        values['stream_engine'] = self.stream_engine.currentData()
        if self.anchors and t:
            values["draft"] = {"kind": self.kind(), "coordinate_space": "native", "anchors": [list(t.xy(*anchor)) for anchor in self.anchors], "parameters": values["parameters"], "edit_target": self.edit_target, "segment_range": list(self.segment_range) if self.segment_range else None}
            values['draft']['fixed_anchor_indices'] = sorted(self._fixed_anchor_indices)
            values['draft']['engine'] = self.trace_engine()
            values['draft']['engine_version'] = 1
        return values

    @staticmethod
    def validate_settings(settings):
        """Reject malformed project UI state before replacing the active project."""
        def number(value):
            return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        if not isinstance(settings, dict) or not isinstance(settings.get("parameters", {}), dict):
            raise ValueError("Project trace settings must be an object of numeric parameters.")
        if settings.get('stream_engine', 'legacy') not in ('legacy', 'stream_auto'):
            raise ValueError('Unsupported stream engine; no fallback is permitted.')
        draft = settings.get('draft')
        if draft is not None:
            if not isinstance(draft, dict) or draft.get('engine', 'legacy') not in ('legacy', 'stream_auto'):
                raise ValueError('Unsupported draft engine; no fallback is permitted.')
            project.require_supported_engine(draft)
            if draft.get('engine') == 'stream_auto' and draft.get('kind') != 'stream':
                raise ValueError('Auto engine is supported only for stream drafts.')
        bounds = {"corridor": (1, math.inf), "smoothing": (0, 50), "line_smoothing": (0, 50), "terrain_weight": (0, 1000), "spacing": (.25, 2000), "simplify": (0, 200)}
        for key, value in settings.get("parameters", {}).items():
            if key == 'relax_anchors' and not isinstance(value, bool):
                raise ValueError("Project setting 'relax_anchors' must be true or false.")
            if key in bounds and (not number(value) or not bounds[key][0] <= value <= bounds[key][1]):
                raise ValueError(f"Project setting '{key}' is outside the supported range.")
        if settings.get("style", "Terrain") not in ("Terrain", "Hillshade", "Slope", "Elevation"):
            raise ValueError("Project terrain display style is invalid.")
        for key, low, high, default in (("azimuth", 0, 359, 315), ("z_factor", .1, 10, 1)):
            value = settings.get(key, default)
            if not number(value) or not low <= value <= high:
                raise ValueError(f"Project setting '{key}' is invalid.")
        view = settings.get("view", {})
        if not isinstance(view, dict):
            raise ValueError("Project map view must be an object.")
        if view:
            center = view.get("center")
            if not number(view.get("scale")) or not 1e-9 <= view["scale"] <= 1e9 or not isinstance(center, list) or len(center) != 2 or not all(number(v) for v in center):
                raise ValueError("Project map view has invalid scale or center coordinates.")
        reference = settings.get("terrain_reference")
        if reference is not None:
            if not isinstance(reference, dict) or not isinstance(reference.get("bounds"), list) or len(reference["bounds"]) != 4 or not all(number(v) for v in reference["bounds"]):
                raise ValueError("Project terrain reference has invalid extent metadata.")
            if not all(type(reference.get(k)) is int and reference[k] >= 2 for k in ("original_width", "original_height")):
                raise ValueError("Project terrain reference has invalid grid dimensions.")
            resolution = reference.get("original_resolution_xy")
            if not isinstance(resolution, list) or len(resolution) != 2 or not all(number(v) and v > 0 for v in resolution):
                raise ValueError("Project terrain reference has invalid pixel dimensions.")
            if reference.get("crs_wkt") is not None:
                from rasterio.crs import CRS
                try:
                    CRS.from_wkt(reference["crs_wkt"])
                except Exception as exc:
                    raise ValueError("Project terrain reference has an invalid coordinate system.") from exc

    def restore_settings(self, settings):
        self.stream_engine.setCurrentIndex(self.stream_engine.findData(settings.get('stream_engine', 'legacy')))
        self.relax_guides.setChecked(settings.get('parameters', {}).get('relax_anchors', False))
        self.param_widgets['line_smoothing'].setValue(settings.get('parameters', {}).get('line_smoothing', 0))
        for k, value in settings.get("parameters", {}).items():
            if k in self.param_widgets:
                self.param_widgets[k].setValue(value)
        self.view_style.blockSignals(True)
        self.view_style.setCurrentText(settings.get("style", "Terrain"))
        self.view_style.blockSignals(False)
        self.azimuth.setValue(settings.get("azimuth", 315))
        self.exaggeration.setValue(settings.get("z_factor", 1))
        self.canvas.set_image(self.terrain.rgb(self.view_style.currentText(), azimuth=self.azimuth.value(), z_factor=self.exaggeration.value(), **display_kwargs(self.preferences)))
        self.canvas.set_contours(self.make_contours(self.terrain, self.preferences["display"]["contour_interval"]))
        view = settings.get("view", {})
        if self.preferences["session"]["remember_view"] and view.get("scale", 0) > 0 and len(view.get("center", [])) == 2:
            self.canvas.resetTransform()
            self.canvas.scale(view["scale"], view["scale"])
            self.canvas.centerOn(QPointF(*view["center"]))
        draft = settings.get("draft")
        if draft and draft.get("anchors"):
            self.stream_engine.setCurrentIndex(self.stream_engine.findData(draft.get('engine', 'legacy')) if draft['kind'] == 'stream' else self.stream_engine.currentIndex())
            self._activate_draft_kind(draft["kind"])
            self.anchors = [tuple(self.terrain.rc(*p)) for p in draft["anchors"]]
            self._anchor_exact = {i: list(p) for i, p in enumerate(draft["anchors"])}
            self._fixed_anchor_indices = set(draft.get('fixed_anchor_indices', []))
            if draft.get('parameters'):
                self.load_feature_parameters({'parameters': draft['parameters']})
            self.edit_target = draft.get("edit_target")
            self.segment_range = tuple(draft["segment_range"]) if draft.get("segment_range") else None
            if self.segment_range:
                self._fixed_anchor_indices.update((0, len(self.anchors) - 1))
            if self.edit_target:
                self.select_feature(self.edit_target)
            self.anchor_label.setText(f"Restored draft · {len(self.anchors)} anchors")
            self.draw_overlays()
        self.autosave_timer.setInterval(int(self.preferences["session"]["autosave_seconds"] * 1000))

    def save(self, save_as=False):
        if self.busy or not self.terrain:
            return False
        path = self.project_path
        if save_as or not path:
            path, _ = QFileDialog.getSaveFileName(self, "Save TracerTool project", path or "Terrain lines.tracer.json", "TracerTool project (*.tracer.json)")
            if not path:
                return False
            if not path.endswith(".tracer.json"):
                path += ".tracer.json"
        try:
            save_project(path, self.terrain.path, self.features, self.settings())
            self.project_path = path
            self.dirty = False
            self.discard_recovery()
            self.update_title()
            self.statusBar().showMessage(f"Saved {Path(path).name}")
            return True
        except Exception as exc:
            self.error(str(exc))
            return False

    def export(self):
        if self.busy or not self.features:
            return
        export_settings = self.preferences['export']
        scope = export_settings['scope']
        selected_ids = {item.data(Qt.ItemDataRole.UserRole) for item in self.feature_list.selectedItems()}
        visible = [f for f in self.features if scope == 'all' or (scope == 'selected' and f['id'] in selected_ids) or (scope == 'checked' and f.get('visible', True))]
        if not visible:
            self.error('No lines match the export scope. Select/check lines or change Export settings.')
            return
        path, fmt = QFileDialog.getSaveFileName(self, 'Export ' + scope + ' lines', 'Terrain lines.shp', 'ESRI Shapefile with Z (*.shp);;Shapefile archive (*.zip);;GeoJSON in output CRS (*.geojson)')
        if not path:
            return
        try:
            crs = self.terrain.crs
            if export_settings['target_crs'] or export_settings['z_scale'] != 1:
                from .raster_ops import transform_features
                from rasterio.crs import CRS
                target = CRS.from_user_input(export_settings['target_crs']) if export_settings['target_crs'] else crs
                question = f"Export {len(visible)} lines with XY in {target.to_string()} and Z multiplied by {export_settings['z_scale']:g}?\n\nThis changes only the export. No vertical datum transformation is performed."
                if QMessageBox.question(self, 'Confirm export coordinates', question, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Yes) != QMessageBox.StandardButton.Yes:
                    return
                visible = transform_features(visible, crs, target, z_scale=export_settings['z_scale'])
                crs = target
            if 'archive' in fmt:
                import zipfile
                if not path.lower().endswith('.zip'):
                    path += '.zip'
                with tempfile.TemporaryDirectory(dir=Path(path).parent) as folder:
                    files = export_shapefile(Path(folder) / (Path(path).stem + '.shp'), visible, crs)
                    archive = Path(folder) / 'output.zip'
                    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as handle:
                        for item in files:
                            handle.write(item, Path(item).name)
                    os.replace(archive, path)
                QMessageBox.information(self, 'Export complete', f'Exported {len(visible)} lines with all shapefile companion files in {path}')
            elif 'Shapefile' in fmt:
                if not path.lower().endswith('.shp'):
                    path += '.shp'
                files = export_shapefile(path, visible, crs)
                QMessageBox.information(self, 'Export complete', f'Exported {len(visible)} lines.\n\nKeep these companion files together:\n' + '\n'.join(Path(p).name for p in files))
            else:
                if not path.lower().endswith('.geojson'):
                    path += '.geojson'
                export_geojson(path, visible, crs)
            self.statusBar().showMessage(f'Exported {len(visible)} lines to {Path(path).name}')
        except Exception as exc:
            self.error(str(exc))

    def set_tool(self, tool):
        if self.busy and not self._restoring:
            return
        if not self._restoring and not self.confirm_draft_discard():
            current = self.canvas.mode if self.canvas.mode in self.tool_buttons else 'edit'
            self.tool_buttons[current].setChecked(True)
            return
        self.clear_draft()
        self.tool_buttons[tool].setChecked(True)
        self.canvas.set_mode(tool)
        self.break_mode.setVisible(tool == 'breakline')
        self.show_tool_instructions(tool)
        self.draw_overlays()

    def show_tool_instructions(self, tool):
        instructions = {
            'pan': 'Drag to pan. Scroll to zoom. Click a saved line to inspect it. F fits the terrain.',
            'stream': 'Click a rough guide upstream to downstream. Drag points to adjust; Shift-click an edge to insert. Select a point and Delete to remove. Ctrl+Z/Y undo/redo.',
            'breakline': 'Click a rough guide along the crest or bank. Drag points; Shift-click an edge to insert. Select a point and Delete to remove. Ctrl+Z/Y undo/redo.',
            'manual': 'Click vertices for a hand-drawn line. Snapping helps connect existing lines; Alt bypasses it.',
            'edit': 'Select a line. Click or drag a white vertex; Delete removes it. Double-click an edge to insert. Use Correct segment for a local retrace.',
        }
        self.instructions.setText(instructions[tool])

    def kind(self):
        if self._draft_kind:
            return self._draft_kind
        if self.canvas.mode == 'breakline':
            return self.break_mode.currentData()
        return self.canvas.mode if self.canvas.mode in ('stream', 'manual') else 'stream'

    def params(self):
        return TraceParams(**{k: w.value() for k, w in self.param_widgets.items()}, relax_anchors=self.relax_guides.isChecked())

    def trace_engine(self):
        return self.stream_engine.currentData() if self.kind() == 'stream' else 'legacy'

    def change_stream_engine(self, *_):
        self.invalidate_preview()

    def reset_parameters(self):
        for name, value in vars(default_params(self.terrain, self.kind()) if self.terrain else TraceParams()).items():
            if name in self.param_widgets:
                self.param_widgets[name].setValue(value)
        self.relax_guides.setChecked(True)
        self.preset.setCurrentText('Balanced')
        self.update_distance_guidance()

    def update_distance_guidance(self):
        if not self.terrain:
            return
        t = self.terrain
        if self.trace_engine() == 'stream_auto':
            self.units_label.setText(f"Auto (experimental): source-native analysis; effective resolution is reported with the preview.\nOutput spacing: {self.params().spacing * t.resolution:g} {t.units}. Legacy search, attraction and smoothing controls are not Auto settings. Dense vertices do not add DEM accuracy.")
            return
        radius = self.param_widgets['corridor'].value() * t.resolution
        spacing = self.param_widgets['spacing'].value() * t.resolution
        self.units_label.setText(f"1 working cell = {t.resolution:g} {t.units}.\nSearch radius: {radius:g} {t.units}\nTarget spacing: {spacing:g} {t.units}\nStart with 12 cells search / 3 cells spacing. Widen search only if the guide misses the feature; keep spacing small to retain editable detail.")

    def toggle_guide_edit(self, checked):
        if not hasattr(self, 'canvas'):
            return
        self.canvas.guide_edit = checked
        if checked:
            self.instructions.setText('Drag a numbered guide to move it. Click a guide edge to insert a point. Select a point and Delete to remove it. Ctrl+Z/Y undo and redo. Turn off Edit guide points to extend the line.')
        else:
            self.show_tool_instructions(self.canvas.mode if self.canvas.mode in self.tool_buttons else 'stream')
        self.canvas.setFocus()

    def choose_anchor(self, index):
        if self.busy:
            return
        self.selected_anchor = index
        self.draw_overlays()
        self.update_buttons()

    def draft_state(self):
        return copy.deepcopy((self.anchors, self._anchor_exact, self._fixed_anchor_indices, self.selected_anchor))

    def snapshot_draft(self):
        self.draft_history.append(self.draft_state())
        self.draft_history = self.draft_history[-int(self.preferences['editing']['history_limit']):]
        self.draft_future.clear()

    def restore_draft_state(self, state):
        self.anchors, self._anchor_exact, self._fixed_anchor_indices, self.selected_anchor = copy.deepcopy(state)
        self.invalidate_preview()
        self.anchor_label.setText(f'{len(self.anchors)} guide points · Ctrl+Z/Y undo/redo')
        self.schedule_recovery()

    def insert_anchor(self, after_index, row, col):
        self.add_anchor(row, col, after_index + 1)

    def delete_anchor(self):
        if self.selected_anchor is not None:
            self.remove_anchor(self.selected_anchor)

    def invalidate_preview(self, *_):
        self._draft_revision += 1
        self.preview = None
        if hasattr(self, "canvas"):
            self.draw_overlays()
            self.update_buttons()
        if self.terrain:
            self.update_distance_guidance()
            if not self._restoring and not self.busy:
                self.mark_dirty()
        if self.preferences['editing']['auto_preview'] and len(self.anchors) >= 2 and not self._restoring:
            self.preview_debounce.start(450)

    def add_anchor(self, row, col, insertion=None):
        if self.busy or not self.terrain:
            return
        xy = self.point_for_edit(row, col)
        r, c = self.terrain.rc(*xy)
        if self.terrain.sample(*xy) is None:
            self.statusBar().showMessage('Place anchors inside valid elevation data.')
            return
        point = (r, c)
        if insertion is None:
            insertion = len(self.anchors) - 1 if self.segment_range else len(self.anchors)
        if not 0 <= insertion <= len(self.anchors):
            return
        if any(math.dist(p, point) < 1e-7 for p in self.anchors[max(0, insertion - 1):insertion + 1]):
            return
        self.snapshot_draft()
        self.anchors.insert(insertion, point)
        self._anchor_exact = {(i + 1 if i >= insertion else i): p for i, p in self._anchor_exact.items()}
        self._anchor_exact[insertion] = list(xy)
        self._fixed_anchor_indices = {i + 1 if i >= insertion else i for i in self._fixed_anchor_indices}
        if self._last_point_snapped:
            self._fixed_anchor_indices.add(insertion)
        self.selected_anchor = insertion
        self.preview = None
        self.draw_overlays()
        self.update_buttons()
        self.anchor_label.setText(f'{len(self.anchors)} guide points · drag to adjust · Ctrl+Z/Y undo/redo')
        self.statusBar().showMessage('Add another guide point or Trace preview. Enter previews; Enter again applies.')
        self.schedule_recovery()
        if self.preferences['editing']['auto_preview'] and len(self.anchors) >= 2:
            self.preview_debounce.start(450)

    def remove_anchor(self, index=None):
        if self.busy or not self.anchors:
            return
        if index is None:
            index = len(self.anchors) - (2 if self.segment_range else 1)
        if self.segment_range and (len(self.anchors) <= 2 or index in (0, len(self.anchors) - 1)):
            self.statusBar().showMessage('Correction boundaries are fixed; Cancel edit to choose new boundaries.')
            return
        if not 0 <= index < len(self.anchors):
            return
        self.snapshot_draft()
        self.anchors.pop(index)
        self._anchor_exact = {(i - 1 if i > index else i): p for i, p in self._anchor_exact.items() if i != index}
        self._fixed_anchor_indices = {i - 1 if i > index else i for i in self._fixed_anchor_indices if i != index}
        self.selected_anchor = min(index, len(self.anchors) - 1) if self.anchors else None
        self.invalidate_preview()
        self.anchor_label.setText(f'{len(self.anchors)} anchors')
        self.schedule_recovery()

    def clear_draft(self):
        if self.busy and not self._restoring:
            self.cancel_job()
            return
        self.preview_debounce.stop()
        self._preview_pending = False
        self.anchors = []
        self.preview = None
        self.edit_target = None
        self.segment_range = None
        self.segment_first = None
        self._draft_kind = None
        self._anchor_exact = {}
        self._fixed_anchor_indices = set()
        self.selected_anchor = None
        self.draft_history.clear()
        self.draft_future.clear()
        self.guide_edit_button.setChecked(False)
        if self.canvas.mode == 'segment':
            self.canvas.set_mode('edit')
        if self.canvas.mode in self.tool_buttons:
            self.show_tool_instructions(self.canvas.mode)
        self.anchor_label.setText('No anchors placed')
        self.draw_overlays()
        self.update_buttons()
        self.show_selected_details()
        self.schedule_recovery()

    def draw_overlays(self):
        self.canvas.selected_anchor = self.selected_anchor
        self.canvas.set_overlays(self.features, self.selected, self.anchors, self.preview, self.kind(), self.selected_vertex, self.segment_range)

    def enter_action(self):
        if self.preview:
            self.accept_preview()
        else:
            self.trace_preview()

    def trace_preview(self):
        if not self.terrain or len(self.anchors) < 2:
            self._preview_pending = False
            return
        if self.busy:
            if self.preferences['editing']['auto_preview']:
                self._preview_pending = True
            return
        self._preview_pending = False
        self.preview_debounce.stop()
        try:
            project.require_supported_engine({'engine': self.trace_engine(), 'engine_version': 1})
            if self.edit_target:
                target = next((f for f in self.features if f['id'] == self.edit_target), None)
                if target is None:
                    raise ValueError('The line being edited no longer exists.')
                project.require_supported_engine(target)
        except ValueError as exc:
            self.error(str(exc))
            return
        anchors, params, kind = list(self.anchors), self.params(), self.kind()
        cells = [(math.floor(r + .5), math.floor(c + .5)) for r, c in anchors]
        if kind != 'manual' and self.trace_engine() == 'legacy' and any(a == b for a, b in zip(cells, cells[1:])):
            self.error('Adjacent guide points occupy the same working cell. Move one farther apart or use Manual line for subcell geometry.')
            return
        fixed = sorted(self._fixed_anchor_indices)
        terrain, engine = self.terrain, self.trace_engine()
        revision = self._draft_revision
        exact = copy.deepcopy(self._anchor_exact)
        def install(result):
            if (self.terrain is terrain and self._draft_revision == revision
                    and self.anchors == anchors and self._anchor_exact == exact
                    and self.trace_engine() == engine and self.params() == params
                    and sorted(self._fixed_anchor_indices) == fixed):
                self.install_preview(result)
        def calculate():
            if engine == 'stream_auto':
                terrain.check_source_unchanged()
                from .stream_auto import trace_auto
                return trace_auto(terrain, anchors, params, cancel=self._cancel_event.is_set, fixed_anchor_indices=fixed)
            if engine != 'legacy':
                raise ValueError(f"Unsupported trace engine: {engine!r}. No fallback was attempted.")
            return trace(terrain, anchors, kind, params, cancel=self._cancel_event.is_set, fixed_anchor_indices=fixed)
        self.start_job('Analysing source terrain · Auto (experimental)…' if engine == 'stream_auto' else 'Following terrain inside the guide corridor…', calculate, install)

    def check_preview_source(self, result):
        """Validate solver identity before any preview or accepted-state changes."""
        if result.metrics.get('engine') == 'stream_auto':
            self.terrain.check_source_unchanged()
            from .analysis_grid import check_source_identity
            identity = result.metrics.get('effective_config', {}).get('source_identity')
            if identity is not None:
                check_source_identity(identity)

    def install_preview(self, result):
        self.check_preview_source(result)
        # Preserve exact snapped guide coordinates, including subcell endpoints
        # from previous vector work. The routing grid itself uses cell centers.
        last_match = -1
        for anchor_index, xy in sorted(self._anchor_exact.items()):
            if self.kind() == 'manual':
                break
            if anchor_index >= len(self.anchors):
                continue
            if (result.metrics.get('engine') == 'stream_auto' or self.relax_guides.isChecked()) and anchor_index not in self._fixed_anchor_indices:
                continue
            r, c = self.anchors[anchor_index]
            cell = (math.floor(r + .5), math.floor(c + .5))
            candidates = [i for i, rc in enumerate(result.cells) if i > last_match and math.dist(rc, cell) < 1e-7]
            if anchor_index in self._fixed_anchor_indices:
                if anchor_index == 0:
                    candidates = [0]
                elif anchor_index == len(self.anchors) - 1:
                    candidates = [len(result.coordinates) - 1]
                elif not candidates:
                    # Auto cells are fractional working coordinates converted
                    # from native analysis; a rounded cell match is not required.
                    candidates = [i for i, coordinate in enumerate(result.coordinates)
                                  if i > last_match and math.dist(coordinate[:2], xy) < 1e-7]
                    if not candidates:
                        raise ValueError('The trace omitted a protected connection. Adjust guides and preview again; no geometry was accepted.')
            if candidates:
                i = candidates[0]
                last_match = i
                z = self.terrain.sample(*xy)
                if z is None:
                    raise ValueError('A snapped guide point touches source NoData.')
                result.coordinates[i] = [*xy, z]
        if result.metrics.get('engine') == 'stream_auto':
            self.validate_source_segments(result.coordinates)
        else:
            validate_segments(self.terrain, result.coordinates)
        arr = np.asarray(result.coordinates)
        dz = np.diff(arr[:, 2])
        gain = float(np.maximum(dz, 0).sum())
        result.metrics.update(length=float(np.linalg.norm(np.diff(arr[:, :2], axis=0), axis=1).sum()), vertices=len(arr), elevation_min=float(arr[:, 2].min()), elevation_max=float(arr[:, 2].max()), elevation_start=float(arr[0, 2]), elevation_end=float(arr[-1, 2]), elevation_gain=gain, elevation_loss=float(-np.minimum(dz, 0).sum()))
        edges = np.linalg.norm(np.diff(arr[:, :2], axis=0), axis=1)
        pixels = np.asarray([self.terrain.rc(*point[:2]) for point in arr])
        pixel_edges = np.linalg.norm(np.diff(pixels, axis=0), axis=1)
        result.metrics.update(spacing_min=float(edges.min()), spacing_median=float(np.median(edges)), spacing_max=float(edges.max()), spacing_min_pixels=float(pixel_edges.min()), spacing_median_pixels=float(np.median(pixel_edges)), spacing_max_pixels=float(pixel_edges.max()), spacing_exception_count=int(np.count_nonzero(pixel_edges < self.params().spacing * .625)))
        if result.metrics.get('engine') != 'stream_auto':
            result.warnings = [w for w in result.warnings if not w.startswith('This line contains uphill')]
        if self.kind() == 'stream' and result.metrics.get('engine') != 'stream_auto' and gain > max(.001, float(np.ptp(arr[:, 2])) * .02):
            result.warnings.append('This line contains uphill segments. Check direction, pits, bridges, and anchor placement; no depression filling is applied.')
        result.anchors = [list(self.terrain.xy(*a)) for a in self.anchors]
        result.fixed_anchor_indices = sorted(self._fixed_anchor_indices)
        self.preview = result
        self.draw_overlays()
        self.show_details(result.coordinates, result.warnings, result.metrics)
        self.statusBar().showMessage('Preview ready · inspect the line, then Apply/Accept or Enter')

    def snapshot(self):
        self.history.append(copy.deepcopy(self.features))
        self.history = self.history[-int(self.preferences['editing']['history_limit']):]
        self.future.clear()

    def validate_source_segments(self, coordinates):
        """Recheck native supercover after restoring exact vector connections."""
        import rasterio
        from .tracing import _segment_cells
        if len(coordinates) < 2:
            raise ValueError('A line needs at least two vertices.')
        for point in coordinates:
            if len(point) != 3 or not all(math.isfinite(v) for v in point):
                raise ValueError('Line coordinates must contain finite XYZ values.')
        with rasterio.open(self.terrain.path) as source:
            transform = source.transform
        pixels = [((p[1] - transform.f) / transform.e - .5,
                   (p[0] - transform.c) / transform.a - .5) for p in coordinates]
        for a, b in zip(pixels, pixels[1:]):
            cells = _segment_cells(a, b)
            points = [(transform.c + (col + .5) * transform.a,
                       transform.f + (row + .5) * transform.e) for row, col in cells]
            if any(z is None for z in self.terrain.sample_many(points)):
                raise ValueError('A trace segment crosses source NoData. Adjust guides; no geometry was accepted.')

    def accept_preview(self):
        if self.busy or self.preview is None:
            return
        try:
            self.check_preview_source(self.preview)
        except ValueError as exc:
            self.error(str(exc))
            return
        kind = self.kind()
        if self.edit_target:
            original = next((f for f in self.features if f['id'] == self.edit_target), None)
            if original is None:
                self.error('The line being edited no longer exists. Cancel the draft and select another line.')
                return
            try:
                project.require_supported_engine(original)
                if self.segment_range:
                    feature = editing.replace_segment(self.terrain, original, *self.segment_range, self.preview, self.params())
                else:
                    feature = editing.refresh_feature(self.terrain, original, self.preview.coordinates, 'retrace')
                    from dataclasses import asdict
                    feature['parameters'] = asdict(self.params())
                    feature['anchors'] = copy.deepcopy(self.preview.anchors)
                    feature['metrics'] = copy.deepcopy(self.preview.metrics)
                    feature['warnings'] = copy.deepcopy(self.preview.warnings)
                    feature['engine'] = self.preview.metrics.get('engine', 'legacy')
                    feature['engine_version'] = self.preview.metrics.get('engine_version', 1)
                    feature['engine_evidence'] = {'engine': feature['engine'],
                        'engine_version': feature['engine_version'], 'stale': False,
                        'metrics': copy.deepcopy(self.preview.metrics),
                        'warnings': copy.deepcopy(self.preview.warnings)}
                editing.validate_shared_junction_edit(original, [feature], self.features)
                self.snapshot()
                self.features[self.features.index(original)] = feature
            except ValueError as exc:
                self.error(str(exc))
                return
        else:
            title = {'stream': 'Stream', 'ridge': 'Ridge', 'slope_break': 'Slope break', 'manual': 'Manual'}[kind]
            count = 1
            names = {f['name'] for f in self.features}
            while f'{title} {count}' in names:
                count += 1
            feature = new_feature(f'{title} {count}', kind, self.preview, self.params())
            self.snapshot()
            self.features.append(feature)
        self.selected = feature['id']
        if feature.get('anchors'):
            feature['fixed_anchor_indices'] = sorted(self._fixed_anchor_indices)
        self.selected_vertex = None
        self.clear_draft()
        self.refresh_features()
        self.mark_dirty()
        self.statusBar().showMessage(f"Saved line edit: {feature['name']} · Undo restores the previous geometry")

    def refresh_features(self):
        self._refreshing = True
        self.feature_list.clear()
        for feature in self.features:
            item = QListWidgetItem(feature["name"])
            item.setData(Qt.ItemDataRole.UserRole, feature["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if feature.get("visible", True) else Qt.CheckState.Unchecked)
            item.setForeground(QColor(COLORS.get(feature["kind"], "#ffffff")))
            item.setToolTip(f"{feature['kind']} · {len(feature['coordinates'])} vertices")
            self.feature_list.addItem(item)
            if feature["id"] == self.selected:
                self.feature_list.setCurrentItem(item)
        self.count_label.setText(str(len(self.features)))
        self._refreshing = False
        self.draw_overlays()
        self.show_selected_details()
        self.update_buttons()

    def list_selection(self, current, previous):
        if self._refreshing:
            return
        self.selected = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.selected_vertex = None
        self.draw_overlays()
        self.show_selected_details()
        self.update_buttons()

    def select_feature(self, feature_id):
        if self.anchors or self.edit_target or self.segment_first is not None:
            return
        self.selected = feature_id
        for i in range(self.feature_list.count()):
            item = self.feature_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == feature_id:
                self.feature_list.setCurrentItem(item)
                break
        self.draw_overlays()

    def item_changed(self, item):
        if self._refreshing or self.busy:
            return
        feature = next(f for f in self.features if f["id"] == item.data(Qt.ItemDataRole.UserRole))
        name = item.text().strip() or feature["name"]
        visible = item.checkState() == Qt.CheckState.Checked
        if feature["name"] == name and feature.get("visible", True) == visible:
            return
        self.snapshot()
        feature["name"], feature["visible"] = name, visible
        self.mark_dirty()
        self.draw_overlays()
        self.update_buttons()

    def delete_feature(self):
        if self.busy or self.anchors or self.edit_target or self.segment_first is not None or self.selected is None or self.feature_list.state() == QAbstractItemView.State.EditingState:
            return
        try:
            editing.validate_shared_junction_edit(self.current_feature(), [], self.features)
        except ValueError as exc:
            self.error(str(exc))
            return
        self.snapshot()
        self.features = [f for f in self.features if f["id"] != self.selected]
        self.selected = None
        self.selected_vertex = None
        self.mark_dirty()
        self.refresh_features()

    def undo(self):
        if not self.busy and (self.anchors or self.edit_target or self.draft_history or self.draft_future):
            if self.draft_history:
                self.draft_future.append(self.draft_state())
                self.restore_draft_state(self.draft_history.pop())
            return
        if self.busy or self.anchors or self.edit_target or self.segment_first is not None or not self.history:
            return
        self.future.append(copy.deepcopy(self.features))
        self.features = self.history.pop()
        self.selected = None
        self.selected_vertex = None
        self.mark_dirty()
        self.refresh_features()

    def redo(self):
        if not self.busy and (self.anchors or self.edit_target or self.draft_history or self.draft_future):
            if self.draft_future:
                self.draft_history.append(self.draft_state())
                self.restore_draft_state(self.draft_future.pop())
            return
        if self.busy or self.anchors or self.edit_target or self.segment_first is not None or not self.future:
            return
        self.history.append(copy.deepcopy(self.features))
        self.features = self.future.pop()
        self.selected = None
        self.selected_vertex = None
        self.mark_dirty()
        self.refresh_features()

    def move_vertex(self, index, row, col):
        if self.busy or not self.terrain:
            return
        feature = self.current_feature()
        if feature is None:
            return
        xy = self.point_for_edit(row, col, (feature['id'], {index, index - 1, index + 1}))
        if self.terrain.sample(*xy) is None:
            self.statusBar().showMessage('Vertex must stay inside valid terrain.')
            return
        try:
            updated = editing.move_vertex(self.terrain, feature, index, xy)
            self.selected_vertex = index
            self.commit_feature_edit(updated)
        except ValueError as exc:
            self.error(str(exc))

    @staticmethod
    def basic_metrics(coords):
        arr = np.asarray(coords)
        return {"length": float(np.linalg.norm(np.diff(arr[:, :2], axis=0), axis=1).sum()), "vertices": len(coords), "elevation_change": float(arr[-1, 2] - arr[0, 2]), "uphill_total": float(np.maximum(np.diff(arr[:, 2]), 0).sum())}

    def show_details(self, coords, warnings, metrics=None):
        self.profile.set_coordinates(coords)
        m = self.basic_metrics(coords)
        z_units = self.terrain.metadata.get('vertical_units', 'source Z units')
        distances = np.linalg.norm(np.diff(np.asarray(coords)[:, :2], axis=0), axis=1)
        spacing = f"Spacing: {np.median(distances):.1f} median ({distances.min():.1f}–{distances.max():.1f} {self.terrain.units})"
        self.metrics_label.setText(f"{m['length']:,.1f} {self.terrain.units}  ·  {m['vertices']} vertices\n{spacing}\nΔ elevation {m['elevation_change']:+.2f} {z_units}\nProfile: distance in {self.terrain.units}; elevation in {z_units}")
        self.qa_label.setText("\n\n".join(warnings) if warnings else "Review against the hillshade. Strong terrain alignment does not establish a surveyed breakline.")
        metrics = metrics or {}
        if metrics.get('engine') == 'stream_auto':
            self.metrics_label.setText(self.metrics_label.text() + f"\nAuto (experimental) · {metrics.get('status', 'unknown')}\nAnalysis resolution: {metrics.get('analysis_resolution', 'unknown')} {self.terrain.units}")
            diagnostics = []
            for diagnostic in metrics.get('diagnostics', []):
                text = f"{diagnostic.get('code', 'diagnostic')}: {diagnostic.get('message', '')}"
                location = diagnostic.get('location')
                if location:
                    text += f" · X {location[0]:g}, Y {location[1]:g}"
                diagnostics.append(text)
            self.qa_label.setText('\n\n'.join([self.qa_label.text(), *diagnostics]))

    def show_selected_details(self):
        if self.preview:
            self.show_details(self.preview.coordinates, self.preview.warnings, self.preview.metrics)
            return
        feature = next((f for f in self.features if f["id"] == self.selected), None)
        if feature:
            self.show_details(feature["coordinates"], feature.get("warnings", []), feature.get('metrics', {}))
        else:
            self.profile.set_coordinates([])
            self.metrics_label.setText("Select or preview a line.")
            self.qa_label.setText("Every trace is a draft for review.")

    def show_position(self, row, col):
        if not self.terrain:
            return
        r, c = int(round(row)), int(round(col))
        if 0 <= r < self.terrain.height and 0 <= c < self.terrain.width:
            x, y = self.terrain.xy(row, col)
            z = self.terrain.data[r, c]
            self.coord_label.setText(f"X {x:,.2f}  Y {y:,.2f}  ·  Z {z:,.2f}" if np.isfinite(z) else "NoData")
        else:
            self.coord_label.setText("")

    def sync_display_controls(self):
        for widget, key in ((self.palette_choice, 'palette'), (self.range_choice, 'stretch')):
            widget.setCurrentIndex(widget.findData(self.preferences['display'][key]))

    def change_display_controls(self, *_):
        if self.busy:
            return
        proposed = copy.deepcopy(self.preferences)
        proposed['display']['palette'] = self.palette_choice.currentData()
        proposed['display']['stretch'] = self.range_choice.currentData()
        try:
            self.apply_preferences(normalize_preferences(proposed))
        except ValueError as exc:
            self.sync_display_controls()
            self.error(str(exc))

    def schedule_view_stretch(self):
        if not self.terrain or self.preferences['display']['stretch'] != 'view':
            return
        self._view_stretch_pending = True
        self.view_debounce.start(180)

    def refresh_view_stretch(self):
        if not self.terrain or self.preferences['display']['stretch'] != 'view':
            self._view_stretch_pending = False
            return
        if self.busy or self._restoring:
            return  # job_finished schedules the latest viewport, without a queue.
        self._view_stretch_pending = False
        self.render_terrain(view_only=True)

    def render_terrain(self, *_, view_only=False):
        if not self.terrain or self.busy:
            return
        style, azimuth, z_factor = self.view_style.currentText(), self.azimuth.value(), self.exaggeration.value()
        options = display_kwargs(self.preferences)
        bounds = self.canvas.visible_bounds()
        interval = self.preferences['display']['contour_interval']
        if not self._restoring and not view_only:
            self.mark_dirty()
        def calculate():
            rgb = self.terrain.rgb(style, azimuth=azimuth, z_factor=z_factor, view_bounds=bounds, **options)
            contours = None if view_only else self.make_contours(self.terrain, interval)
            return rgb, contours
        def complete(pair):
            self.canvas.set_image(pair[0])
            if pair[1] is not None:
                self.canvas.set_contours(pair[1])
        self.start_job('Updating terrain display…', calculate, complete, quiet=view_only)

    def show_help(self):
        QMessageBox.information(self, "TracerTool workflow", (
            "1. Open an elevation GeoTIFF. Terrain & CRS settings show units and resolution.\n"
            "2. Choose Stream line, Breakline (crest or bank), or Manual line.\n"
            "3. Click guide points, preview with Enter, inspect the profile, then Enter to accept.\n"
            "4. Retrace line restores guides and settings. Correct segment replaces only the portion between two selected vertices.\n"
            "5. Edit vertices: drag a point, double-click an edge to insert, Delete a selected point, or use Split/Reverse. Ctrl-select two lines to Join.\n"
            "6. Save a project, then export checked/selected/all lines as PolyLineZ shapefile, ZIP, or native-CRS GeoJSON.\n\n"
            "Settings: palettes, stretch, hillshade, contours, snapping, undo, recovery, working grid and export CRS/Z multiplier. File → Reproject terrain copy creates a separate projected DEM.\n\n"
            "Scroll: zoom · Right/middle drag: pan · F: fit · Alt: bypass feature snapping\n"
            "Backspace: last guide · Escape: cancel draft/operation · Ctrl+Z/Y: undo/redo\n"
            "Ctrl+S: save · Ctrl+Shift+S: save as · Ctrl+E: export\n\n"
            "Projects reference the source TIFF; keep it with your project. Saves retain the previous .bak; recovery snapshots also retain unfinished drafts.\n"
            "Trace distances are working pixels. Source Z is preserved. Stream routes may climb; inspect the warnings and profile. No vertical datum conversion is performed.\n\n"
            "Version " + __version__ + " · MIT license · Local processing"))

    def closeEvent(self, event):
        if self.busy:
            answer = QMessageBox.question(self, 'Operation in progress', 'Cancel the current operation and close after it finishes safely?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                self._close_when_idle = True
                self.cancel_job()
            event.ignore()
        elif self.check_discard():
            self.autosave_timer.stop()
            self.recovery_debounce.stop()
            self.preview_debounce.stop()
            self.discard_recovery()
            event.accept()
        else:
            self._close_when_idle = False
            event.ignore()


def smoke_test(app):
    """Exercise Qt and GDAL resources in both source and frozen distributions."""
    import rasterio
    from rasterio.transform import from_origin
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "smoke.tif"
        rr, cc = np.mgrid[:64, :64]
        data = (100 + (cc - 32) ** 2 * 0.01 - rr * 0.1).astype("float32")
        with rasterio.open(path, "w", driver="GTiff", height=64, width=64, count=1, dtype="float32", crs="EPSG:32615", transform=from_origin(500000, 4500000, 1, 1), nodata=-9999) as dst:
            dst.write(data, 1)
        window = MainWindow()
        window.install_terrain(window.load_terrain_image(path))
        result = trace(window.terrain, [(5, 32), (58, 32)], "stream", TraceParams())
        window.features = [new_feature("Smoke stream", "stream", result, TraceParams())]
        # Import through the production lazy boundary so frozen builds exercise
        # the actual Auto engine and its native analysis dependencies as well.
        from .stream_auto import trace_auto
        auto = trace_auto(window.terrain, [(5, 32), (58, 32)], TraceParams(),
                          fixed_anchor_indices=[0, 1])
        assert auto.metrics['engine'] == 'stream_auto'
        assert auto.metrics['engine_version'] == 1
        window.set_tool('stream')
        window.stream_engine.setCurrentIndex(window.stream_engine.findData('stream_auto'))
        window.anchors = [(5, 32), (58, 32)]
        window._fixed_anchor_indices = {0, 1}
        window._anchor_exact = {i: list(window.terrain.xy(*p)) for i, p in enumerate(window.anchors)}
        window.install_preview(auto)
        window.accept_preview()
        assert len(window.features) == 2
        assert auto.coordinates[0][:2] == list(window.terrain.xy(5, 32))
        assert auto.coordinates[-1][:2] == list(window.terrain.xy(58, 32))
        assert [p[2] for p in auto.coordinates] == window.terrain.sample_many([p[:2] for p in auto.coordinates])
        project_path = Path(folder) / "smoke.tracer.json"
        save_project(project_path, path, window.features, window.settings())
        assert json.loads(project_path.read_text(encoding='utf-8'))['version'] == 2
        restored = load_project(project_path)
        assert restored['features'] == window.features
        assert restored['settings']['stream_engine'] == 'stream_auto'
        shape_path = Path(folder) / "smoke.shp"
        export_shapefile(shape_path, restored['features'], window.terrain.crs)
        import shapefile
        with shapefile.Reader(str(shape_path)) as reader:
            shapes = reader.shapes()
            assert len(shapes) == 2
            for shape, feature in zip(shapes, window.features):
                assert [list(p) for p in shape.points] == [p[:2] for p in feature['coordinates']]
                assert list(shape.z) == [p[2] for p in feature['coordinates']]
        geojson_path = Path(folder) / 'smoke.geojson'
        export_geojson(geojson_path, restored['features'], window.terrain.crs)
        exported = json.loads(geojson_path.read_text(encoding='utf-8'))
        assert exported['features'][1]['geometry']['coordinates'] == auto.coordinates
        with rasterio.open(path) as source:
            np.testing.assert_array_equal(source.read(1), data)
        window.dirty = False
        window.show()
        app.processEvents()
        assert not window.grab().isNull()
        window.close()
    print("TracerTool smoke test passed", flush=True)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="TracerTool terrain line workbench")
    parser.add_argument("terrain", nargs="?", help="GeoTIFF or .tracer.json project to open")
    parser.add_argument("--demo", action="store_true", help="Open the first local reference tile")
    parser.add_argument("--smoke-test", action="store_true", help="Check bundled dependencies and exit")
    parser.add_argument("--screenshot", help="Save an application screenshot after loading")
    args = parser.parse_args(argv)
    if args.smoke_test and not os.environ.get("QT_QPA_PLATFORM") and sys.platform != "win32":
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("TracerTool")
    app.setOrganizationName("TracerTool")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    if args.smoke_test:
        return smoke_test(app)
    window = MainWindow()
    window.show()
    path = args.terrain
    if args.demo and not path:
        root = Path(__file__).resolve().parents[2]
        tiles = sorted((root / "referenceTiles").glob("*.tif"))
        if tiles:
            path = str(tiles[0])
    if path:
        QTimer.singleShot(0, lambda: window.open_project(path) if path.endswith(".json") else window.open_terrain(path))
    if args.screenshot:
        def capture():
            if window.busy:
                QTimer.singleShot(200, capture)
                return
            window.canvas.fit()
            app.processEvents()
            window.grab().save(args.screenshot)
            app.quit()
        QTimer.singleShot(1500, capture)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
