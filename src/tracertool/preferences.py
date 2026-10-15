"""Validated project preferences and native settings dialogs."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QTabWidget, QWidget,
    QVBoxLayout, QFormLayout, QLabel, QComboBox, QDoubleSpinBox, QSpinBox,
    QCheckBox, QLineEdit, QPushButton, QPlainTextEdit, QMessageBox)


DEFAULTS = {
    "display": {"palette": "earth", "stretch": "percentile", "low": 0., "high": 100.,
                "altitude": 45., "shade_strength": .65, "gamma": 1.,
                "multidirectional": False, "vertical_units": "auto", "contour_interval": 0.},
    "editing": {"snap_enabled": True, "snap_radius": 8., "raster_snap": True,
                "auto_preview": False, "join_tolerance": 3., "history_limit": 100},
    "session": {"autosave_seconds": 30, "remember_view": True, "working_dimension": 2400},
    "export": {"scope": "checked", "target_crs": "", "z_scale": 1.},
}

_RANGES = {
    ("display", "low"): (-1e9, 1e9), ("display", "high"): (-1e9, 1e9),
    ("display", "altitude"): (1, 90), ("display", "shade_strength"): (0, 1),
    ("display", "gamma"): (.1, 5), ("display", "contour_interval"): (0, 1e6),
    ("editing", "snap_radius"): (1, 40), ("editing", "join_tolerance"): (0, 10000),
    ("editing", "history_limit"): (10, 500), ("session", "autosave_seconds"): (5, 600),
    ("export", "z_scale"): (.000001, 1e6),
    ("session", "working_dimension"): (256, 8192),
}
_CHOICES = {
    ("display", "palette"): {"earth", "viridis", "gray", "ocean"},
    ("display", "stretch"): {"percentile", "minmax", "custom"},
    ("display", "vertical_units"): {"auto", "m", "foot", "US survey foot"},
    ("export", "scope"): {"checked", "selected", "all"},
}


def normalize_preferences(value=None):
    result = copy.deepcopy(DEFAULTS)
    if value is None:
        return result
    if not isinstance(value, dict):
        raise ValueError("Project preferences must be an object.")
    for group, options in value.items():
        if group not in DEFAULTS:
            continue
        if not isinstance(options, dict):
            raise ValueError(f"{group.title()} preferences must be an object.")
        for key, item in options.items():
            if key not in DEFAULTS[group]:
                continue
            location = (group, key)
            default = DEFAULTS[group][key]
            if location in _RANGES:
                low, high = _RANGES[location]
                if isinstance(item, bool) or not isinstance(item, (int, float)) or not low <= item <= high or not math.isfinite(item):
                    raise ValueError(f"{key.replace('_', ' ').title()} must be between {low:g} and {high:g}.")
                if isinstance(default, int) and int(item) != item:
                    raise ValueError(f"{key.replace('_', ' ').title()} must be a whole number.")
            elif location in _CHOICES:
                if not isinstance(item, str) or item not in _CHOICES[location]:
                    raise ValueError(f"Invalid {key.replace('_', ' ')} preference.")
            elif isinstance(default, bool) and not isinstance(item, bool):
                raise ValueError(f"{key.replace('_', ' ').title()} must be true or false.")
            elif isinstance(default, str) and not isinstance(item, str):
                raise ValueError(f"{key.replace('_', ' ').title()} must be text.")
            result[group][key] = item
    if result["display"]["stretch"] == "custom" and result["display"]["low"] >= result["display"]["high"]:
        raise ValueError("Custom elevation maximum must be greater than the minimum.")
    crs = result["export"]["target_crs"].strip()
    result["export"]["target_crs"] = crs
    if crs:
        from rasterio.crs import CRS
        try:
            parsed = CRS.from_user_input(crs)
        except Exception as exc:
            raise ValueError("Export CRS is invalid. Enter an EPSG/ESRI code or WKT.") from exc
        if not parsed.is_projected:
            raise ValueError("Choose a projected export CRS with linear units.")
    return result


def display_kwargs(preferences):
    values = copy.deepcopy(preferences["display"])
    values.pop("contour_interval")
    if values["stretch"] != "custom":
        values["low"] = values["high"] = None
    if values["vertical_units"] == "auto":
        values["vertical_units"] = None
    return values


class PreferencesDialog(QDialog):
    def __init__(self, preferences, terrain=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Project settings")
        self.resize(630, 640)
        self.original = normalize_preferences(preferences)
        self.preferences = None
        self.widgets = {}
        layout = QVBoxLayout(self)
        intro = QLabel("Settings are saved with the project. Display controls never change exported geometry or elevations.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self._terrain_tab(terrain)
        display = self._tab("Display")
        self._combo(display, "display", "palette", "Elevation palette", [("Earth", "earth"), ("Viridis", "viridis"), ("Grayscale", "gray"), ("Ocean", "ocean")])
        self._combo(display, "display", "stretch", "Elevation range", [("Clipped 1–99 percentiles", "percentile"), ("Full minimum–maximum", "minmax"), ("Custom range", "custom")])
        self._number(display, "display", "low", "Custom minimum · source Z units")
        self._number(display, "display", "high", "Custom maximum · source Z units")
        self._number(display, "display", "altitude", "Sun altitude · degrees")
        self._number(display, "display", "shade_strength", "Hillshade strength · 0–1")
        self._number(display, "display", "gamma", "Display gamma")
        self._check(display, "display", "multidirectional", "Blend illumination from multiple directions")
        self._combo(display, "display", "vertical_units", "Z units for display slopes", [("Use source metadata", "auto"), ("Meters", "m"), ("International feet", "foot"), ("US survey feet", "US survey foot")])
        self._number(display, "display", "contour_interval", "Contour interval · source Z units (0 hides)")
        display.addRow(self._note("Azimuth and relief exaggeration remain in the map toolbar. Vertical-unit override affects slope/hillshade only. Contours use the working grid; at most 80 levels are drawn."))
        editing = self._tab("Editing")
        self._check(editing, "editing", "snap_enabled", "Snap to saved line endpoints and vertices")
        self._number(editing, "editing", "snap_radius", "Snap tolerance · screen pixels")
        self._check(editing, "editing", "raster_snap", "Place hand-edited vertices at raster cell centers")
        self._check(editing, "editing", "auto_preview", "Refresh a trace preview after settings/anchor changes")
        self._number(editing, "editing", "join_tolerance", f"Join tolerance · {terrain.units if terrain else 'map units'}")
        self._number(editing, "editing", "history_limit", "Undo history · operations")
        editing.addRow(self._note("Hold Alt while placing or moving a point to bypass feature snapping. Segment corrections retain the two chosen boundary vertices. Manual corrections are always checked against NoData."))
        session = self._tab("Recovery")
        self._number(session, "session", "autosave_seconds", "Recovery snapshot interval · seconds")
        self._check(session, "session", "remember_view", "Restore the saved map center and zoom")
        self._number(session, "session", "working_dimension", "Maximum grid side · px (next terrain load)")
        session.addRow(self._note("Recovery snapshots include unfinished drafts and are separate from explicit saves. Saving a project retains its previous good version as .bak. Recover sessions from File → Recover work."))
        export = self._tab("Export")
        self._combo(export, "export", "scope", "Lines to export", [("Checked lines", "checked"), ("Selected lines", "selected"), ("All lines", "all")])
        crs = QLineEdit(self.original["export"]["target_crs"])
        crs.setPlaceholderText("Blank = terrain CRS; e.g. EPSG:26914")
        self.widgets[("export", "target_crs")] = crs
        export.addRow("Output projected CRS", crs)
        self._number(export, "export", "z_scale", "Explicit Z multiplier")
        export.addRow(self._note("A blank CRS and multiplier 1 preserve source XYZ. XY reprojection does not transform a vertical datum. Z scaling is explicit: 0.3048 converts international feet to meters. Review the export summary before writing."))
        self.use_as_default = QCheckBox("Use these preferences as defaults for new projects")
        layout.addWidget(self.use_as_default)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.RestoreDefaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self.restore_defaults)
        layout.addWidget(buttons)

    @staticmethod
    def _note(text):
        widget = QLabel(text)
        widget.setWordWrap(True)
        widget.setStyleSheet("color:#a1bac6; padding:8px 0;")
        return widget

    def _tab(self, title):
        page = QWidget()
        form = QFormLayout(page)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setSpacing(11)
        self.tabs.addTab(page, title)
        return form

    def _terrain_tab(self, terrain):
        form = self._tab("Terrain & CRS")
        if terrain:
            form.addRow("Source", self._note(Path(terrain.path).name))
            form.addRow("Source CRS", self._note(terrain.crs.to_string() if terrain.crs else "Missing"))
            form.addRow("Horizontal units", QLabel(terrain.units))
            form.addRow("Elevation units", QLabel(terrain.metadata.get("vertical_units", "unspecified")))
            form.addRow("Source cell size", QLabel(" × ".join(f"{v:g}" for v in terrain.metadata["original_resolution_xy"])))
            form.addRow("Working cell size", QLabel(" × ".join(f"{v:g}" for v in terrain.metadata["working_resolution_xy"])))
            wkt = QPlainTextEdit(terrain.crs.to_wkt() if terrain.crs else "No CRS metadata")
            wkt.setReadOnly(True)
            wkt.setMaximumHeight(150)
            form.addRow("Projection definition", wkt)
        form.addRow(self._note("Use File → Reproject terrain copy to create a terrain file in a different projected CRS. The original TIFF is preserved. Existing project geometry is never silently assigned to another projection."))

    def _number(self, form, group, key, title):
        default = DEFAULTS[group][key]
        spin = QSpinBox() if isinstance(default, int) else QDoubleSpinBox()
        spin.setRange(*_RANGES[(group, key)])
        if isinstance(spin, QDoubleSpinBox):
            spin.setDecimals(6 if key == "z_scale" else 2)
            spin.setSingleStep(.1 if key in ("gamma", "shade_strength") else 1)
        spin.setValue(self.original[group][key])
        self.widgets[(group, key)] = spin
        form.addRow(title, spin)

    def _combo(self, form, group, key, title, choices):
        combo = QComboBox()
        for label, value in choices:
            combo.addItem(label, value)
        combo.setCurrentIndex(combo.findData(self.original[group][key]))
        self.widgets[(group, key)] = combo
        form.addRow(title, combo)

    def _check(self, form, group, key, title):
        checkbox = QCheckBox(title)
        checkbox.setChecked(self.original[group][key])
        self.widgets[(group, key)] = checkbox
        form.addRow(checkbox)

    def restore_defaults(self):
        for (group, key), widget in self.widgets.items():
            value = DEFAULTS[group][key]
            if isinstance(widget, QComboBox):
                widget.setCurrentIndex(widget.findData(value))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(value)
            elif isinstance(widget, QLineEdit):
                widget.setText(value)
            else:
                widget.setValue(value)

    def accept(self):
        values = copy.deepcopy(self.original)
        for (group, key), widget in self.widgets.items():
            if isinstance(widget, QComboBox):
                value = widget.currentData()
            elif isinstance(widget, QCheckBox):
                value = widget.isChecked()
            elif isinstance(widget, QLineEdit):
                value = widget.text().strip()
            else:
                value = widget.value()
            values[group][key] = value
        try:
            self.preferences = normalize_preferences(values)
        except ValueError as exc:
            QMessageBox.warning(self, "Check settings", str(exc))
            return
        super().accept()


class ReprojectDialog(QDialog):
    def __init__(self, terrain, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reproject a terrain copy")
        self.resize(570, 360)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.target = QLineEdit()
        self.target.setPlaceholderText("Projected CRS, e.g. EPSG:26914 or ESRI:103897")
        form.addRow("Target CRS", self.target)
        self.source = QLineEdit()
        self.source.setPlaceholderText(terrain.crs.to_string() if terrain.crs else "Required: actual source CRS")
        form.addRow("Override source CRS (optional)", self.source)
        self.resolution = QDoubleSpinBox()
        self.resolution.setRange(0, 1000000)
        self.resolution.setDecimals(4)
        self.resolution.setSpecialValueText("Automatic")
        form.addRow("Target cell size · target CRS units", self.resolution)
        self.resampling = QComboBox()
        for title, key in [("Bilinear", "bilinear"), ("Nearest neighbor", "nearest"), ("Cubic", "cubic")]:
            self.resampling.addItem(title, key)
        form.addRow("Elevation resampling", self.resampling)
        layout.addLayout(form)
        layout.addWidget(PreferencesDialog._note("Creates a new GeoTIFF and preserves source elevation units. No vertical datum conversion is performed. Only override a source CRS when its metadata is missing or incorrect and you know the correct definition."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
