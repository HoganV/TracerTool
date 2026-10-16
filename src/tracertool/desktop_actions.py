"""Editing, project preferences, and recovery actions for the desktop window."""
from __future__ import annotations

import copy
import getpass
import hashlib
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import tempfile
from uuid import uuid4

import numpy as np
from PySide6.QtCore import Qt, QTimer, QStandardPaths
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox

from . import editing
from .preferences import DEFAULTS, PreferencesDialog, ReprojectDialog, normalize_preferences, display_kwargs
from .recovery import RecoveryStore


class DesktopActions:
    def initialize_session(self):
        self.preferences = normalize_preferences()
        self.edit_target = None
        self.segment_range = None
        self.segment_first = None
        self.selected_vertex = None
        self._draft_kind = None
        self._anchor_exact = {}
        self._fixed_anchor_indices = set()
        self.selected_anchor = None
        self.draft_history = []
        self.draft_future = []
        self._last_point_snapped = False
        self._view_stretch_pending = False
        self._preview_pending = False
        self._close_when_idle = False
        self.session_id = str(uuid4())
        directory = os.environ.get("TRACERTOOL_STATE_DIR") or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
        self.state_directory = Path(directory)
        self.recovery_warning = ""
        try:
            self.recovery_store = RecoveryStore(self.state_directory / "recovery")
        except (OSError, ValueError):
            identity = hashlib.sha256((getpass.getuser() + "\n" + str(self.state_directory.absolute())).encode()).hexdigest()[:20]
            self.state_directory = Path(tempfile.gettempdir()) / f"tracertool-recovery-{identity}"
            self.recovery_store = RecoveryStore(self.state_directory / "recovery")
            self.recovery_warning = f"The normal recovery folder is not writable. Temporary recovery: {self.state_directory}. Save projects explicitly."
        try:
            default_file = self.state_directory / "defaults.json"
            if default_file.exists():
                self.preferences = normalize_preferences(json.loads(default_file.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            pass
        self.default_preferences = copy.deepcopy(self.preferences)
        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.save_recovery)
        self.autosave_timer.start(int(self.preferences["session"]["autosave_seconds"] * 1000))
        self.recovery_debounce = QTimer(self)
        self.recovery_debounce.setSingleShot(True)
        self.recovery_debounce.timeout.connect(self.save_recovery)
        self.preview_debounce = QTimer(self)
        self.preview_debounce.setSingleShot(True)
        self.preview_debounce.timeout.connect(self.trace_preview)
        self.view_debounce = QTimer(self)
        self.view_debounce.setSingleShot(True)
        self.view_debounce.timeout.connect(self.refresh_view_stretch)

    def current_feature(self):
        return next((f for f in self.features if f["id"] == self.selected), None)

    def commit_feature_edit(self, updated):
        if self.anchors or self.edit_target or self.segment_first is not None:
            return
        index = next(i for i, f in enumerate(self.features) if f["id"] == updated["id"])
        if updated == self.features[index]:
            return
        self.snapshot()
        self.features[index] = updated
        self.mark_dirty()
        self.refresh_features()

    def point_for_edit(self, row, col, excluded=None):
        self._last_point_snapped = False
        if self.preferences["editing"]["raster_snap"]:
            row, col = math.floor(row + .5), math.floor(col + .5)
        xy = self.terrain.xy(row, col)
        if self.preferences["editing"]["snap_enabled"] and not QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier:
            tolerance = self.preferences["editing"]["snap_radius"] / max(self.canvas.transform().m11(), 1e-12)
            best = None
            for feature in self.features:
                if not feature.get("visible", True):
                    continue
                for index, coordinate in enumerate(feature["coordinates"]):
                    if excluded and feature["id"] == excluded[0] and index in excluded[1]:
                        continue
                    r, c = self.terrain.rc(*coordinate[:2])
                    distance = math.hypot(row - r, col - c)
                    if distance <= tolerance and (best is None or distance < best[0]):
                        best = (distance, coordinate[:2])
            if best:
                xy = tuple(best[1])
                self._last_point_snapped = True
        return xy

    def choose_vertex(self, index):
        if self.busy:
            return
        self.selected_vertex = index
        self.draw_overlays()
        self.update_buttons()
        self.statusBar().showMessage(f"Vertex {index + 1} selected · drag to move, Delete to remove, or Split here")

    def insert_vertex(self, after_index, row, col):
        feature = self.current_feature()
        if self.busy or not feature:
            return
        try:
            xy = self.point_for_edit(row, col, (feature["id"], {after_index, after_index + 1}))
            updated = editing.insert_vertex(self.terrain, feature, after_index, xy)
            self.selected_vertex = after_index + 1
            self.commit_feature_edit(updated)
            self.statusBar().showMessage("Inserted vertex · drag it to refine the line")
        except ValueError as exc:
            self.error(str(exc))

    def begin_insert(self):
        if self.busy or not self.current_feature() or not self.confirm_draft_discard():
            return
        self.clear_draft()
        self.tool_buttons["edit"].setChecked(True)
        self.canvas.set_mode("insert")
        self.draw_overlays()
        self.instructions.setText("Click near an edge of the selected line to insert a vertex. Choose Edit vertices to drag points afterward.")

    def delete_context(self):
        if self.anchors:
            self.delete_anchor()
        elif self.canvas.mode in {"edit", "insert"} and self.selected_vertex is not None:
            self.delete_vertex()
        else:
            self.delete_feature()

    def delete_vertex(self):
        feature = self.current_feature()
        if self.busy or feature is None or self.selected_vertex is None:
            return
        try:
            updated = editing.delete_vertex(self.terrain, feature, self.selected_vertex)
            self.selected_vertex = None
            self.commit_feature_edit(updated)
            self.statusBar().showMessage("Removed vertex · Undo restores it")
        except ValueError as exc:
            self.error(str(exc))

    def reverse_line(self):
        feature = self.current_feature()
        if self.busy or not feature:
            return
        try:
            self.selected_vertex = None
            self.commit_feature_edit(editing.reverse_feature(self.terrain, feature))
            self.statusBar().showMessage("Reversed line direction and refreshed profile checks")
        except ValueError as exc:
            self.error(str(exc))

    def split_line(self):
        feature = self.current_feature()
        if self.busy or self.anchors or self.edit_target or self.segment_first is not None or not feature or self.selected_vertex is None:
            return
        try:
            first, second = editing.split_feature(self.terrain, feature, self.selected_vertex)
            self.snapshot()
            index = self.features.index(feature)
            self.features[index:index + 1] = [first, second]
            self.selected_vertex = None
            self.mark_dirty()
            self.refresh_features()
            self.statusBar().showMessage("Split into two lines sharing the original split vertex")
        except ValueError as exc:
            self.error(str(exc))

    def join_lines(self):
        if self.busy or self.anchors or self.edit_target or self.segment_first is not None:
            return
        ids = [item.data(Qt.ItemDataRole.UserRole) for item in self.feature_list.selectedItems()]
        if len(ids) != 2:
            self.statusBar().showMessage("Ctrl-click exactly two lines in the list to join them.")
            return
        first, second = [next(f for f in self.features if f["id"] == i) for i in ids]
        try:
            joined = editing.join_features(self.terrain, first, second, self.preferences["editing"]["join_tolerance"])
            self.snapshot()
            self.features = [joined if f["id"] == first["id"] else f for f in self.features if f["id"] != second["id"]]
            self.selected = joined["id"]
            self.selected_vertex = None
            self.mark_dirty()
            self.refresh_features()
            self.statusBar().showMessage("Joined the closest endpoints · review the connection")
        except ValueError as exc:
            self.error(str(exc))

    def _activate_draft_kind(self, kind):
        self._draft_kind = kind
        tool = "breakline" if kind in {"ridge", "slope_break"} else kind
        self.tool_buttons[tool].setChecked(True)
        self.canvas.set_mode(tool)
        self.show_tool_instructions(tool)
        self.break_mode.setVisible(tool == "breakline")
        self.break_mode.blockSignals(True)
        if tool == "breakline":
            self.break_mode.setCurrentIndex(self.break_mode.findData(kind))
        self.break_mode.blockSignals(False)

    def load_feature_parameters(self, feature):
        self.relax_guides.blockSignals(True)
        self.relax_guides.setChecked(feature['parameters'].get('relax_anchors', False))
        self.relax_guides.blockSignals(False)
        self.param_widgets['line_smoothing'].blockSignals(True)
        self.param_widgets['line_smoothing'].setValue(feature['parameters'].get('line_smoothing', 0))
        self.param_widgets['line_smoothing'].blockSignals(False)
        for key, value in feature["parameters"].items():
            if key in self.param_widgets:
                self.param_widgets[key].blockSignals(True)
                self.param_widgets[key].setValue(value)
                self.param_widgets[key].blockSignals(False)

    def begin_retrace(self):
        feature = self.current_feature()
        if self.busy or not feature or not self.confirm_draft_discard():
            return
        self.clear_draft()
        self.edit_target = feature["id"]
        self.load_feature_parameters(feature)
        self._activate_draft_kind(feature["kind"])
        anchors = feature.get("anchors") or editing.reconstruct_anchors(self.terrain, feature)
        self.anchors = [tuple(self.terrain.rc(*point)) for point in anchors]
        self._anchor_exact = {i: list(point) for i, point in enumerate(anchors)}
        self._fixed_anchor_indices = set(feature.get('fixed_anchor_indices', []))
        self.anchor_label.setText(f"Editing {feature['name']} · {len(self.anchors)} guide points")
        self.instructions.setText("Drag numbered guides; Shift-click a guide edge to insert. Select a guide and Delete to remove. Ctrl+Z/Y undo/redo guides. Preview, then Apply to replace this line.")
        self.draw_overlays()
        self.update_buttons()

    def begin_segment(self):
        if self.busy or not self.current_feature() or not self.confirm_draft_discard():
            return
        self.clear_draft()
        self.segment_first = None
        self.tool_buttons["edit"].setChecked(True)
        self.canvas.set_mode("segment")
        self.draw_overlays()
        self.instructions.setText("Click the first and last existing vertices of the portion to correct. Zoom in to choose boundaries precisely.")
        self.statusBar().showMessage("Choose two boundary vertices on the selected line")

    def pick_segment_boundary(self, index):
        feature = self.current_feature()
        if self.busy or not feature:
            return
        if self.segment_first is None:
            self.segment_first = index
            self.selected_vertex = index
            self.draw_overlays()
            self.update_buttons()
            self.statusBar().showMessage("First boundary selected · click the other boundary")
            return
        if self.segment_first == index:
            return
        start, end = sorted((self.segment_first, index))
        self.segment_range = (start, end)
        self.segment_first = None
        self.edit_target = feature["id"]
        self.load_feature_parameters(feature)
        self._activate_draft_kind(feature["kind"])
        xy = [feature["coordinates"][start][:2], feature["coordinates"][end][:2]]
        self.anchors = [tuple(self.terrain.rc(*p)) for p in xy]
        self._anchor_exact = {0: xy[0], 1: xy[1]}
        self._fixed_anchor_indices = {0, 1}
        self.instructions.setText("Click guide points between the two fixed boundaries, or change settings. Preview and Apply correction replace only the pink segment.")
        self.anchor_label.setText(f"Correcting vertices {start + 1}–{end + 1}")
        self.draw_overlays()
        self.update_buttons()

    def move_anchor(self, index, row, col):
        if self.busy or not self.terrain:
            return
        if self.segment_range and index in (0, len(self.anchors) - 1):
            self.statusBar().showMessage("Correction boundary vertices are fixed. Cancel and select different boundaries to change them.")
            return
        xy = self.point_for_edit(row, col)
        r, c = self.terrain.rc(*xy)
        if self.terrain.sample(*xy) is None:
            self.statusBar().showMessage("Guide points must remain on valid terrain.")
            return
        if math.dist(self.anchors[index], (r, c)) < 1e-9:
            return
        self.snapshot_draft()
        self.anchors[index] = (r, c)
        self._anchor_exact[index] = list(xy)
        self._fixed_anchor_indices.discard(index)
        if self._last_point_snapped:
            self._fixed_anchor_indices.add(index)
        self.selected_anchor = index
        self.invalidate_preview()
        self.schedule_recovery()

    def confirm_draft_discard(self):
        if self._restoring or not self.anchors:
            return True
        result = QMessageBox.question(self, "Unfinished trace", "Discard the current draft? Accepted geometry will be kept.", QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        return result == QMessageBox.StandardButton.Discard

    def schedule_recovery(self):
        if not self._restoring:
            self.recovery_debounce.start(1500)

    def discard_recovery(self):
        try:
            self.recovery_store.discard(self.session_id)
        except (OSError, ValueError) as exc:
            self.recovery_warning = f"Project work is safe; an old recovery snapshot could not be removed: {exc}"
            self.recovery_status.setText("Recovery cleanup pending")
            self.recovery_status.setToolTip(self.recovery_warning)

    def save_recovery(self):
        if not self.terrain or self._restoring:
            return
        try:
            if self.dirty or self.anchors:
                self.recovery_store.save(self.session_id, self.terrain.path, self.features, self.settings(), self.project_path)
                if hasattr(self, "recovery_status"):
                    self.recovery_status.setText("Recovery saved")
            else:
                self.recovery_store.discard(self.session_id)
        except (OSError, ValueError) as exc:
            self.statusBar().showMessage(f"Recovery could not be saved: {exc}. Save the project to a writable folder.")

    def recover_work(self):
        if self.busy or not self.check_discard():
            return
        entries = self.recovery_store.list_entries()
        if not entries:
            QMessageBox.information(self, "Recover work", "There are no recovery snapshots to restore.")
            return
        labels = [f"{entry.get('updated_at', '')}  ·  {Path(entry.get('terrain_path') or 'Terrain').name}  ·  {entry.get('feature_count', 0)} lines" for entry in entries]
        choice, ok = QInputDialog.getItem(self, "Recover work", "Choose a recovery snapshot:", labels, 0, False)
        if not ok:
            return
        entry = entries[labels.index(choice)]
        try:
            project = self.recovery_store.load(entry["path"])
            source = project["terrain_path"]
            if not Path(source).is_file():
                source, _ = QFileDialog.getOpenFileName(self, "Locate the recovered terrain", "", "GeoTIFF (*.tif *.tiff)")
                if not source:
                    return
                project["_relinked"] = True
            project["_project_path"] = project.get("project_path")
            project["_recovered"] = True
            self.open_terrain(source, project)
        except (OSError, ValueError) as exc:
            self.error(str(exc))

    def open_preferences(self):
        if self.busy:
            return
        dialog = PreferencesDialog(self.preferences, self.terrain, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.apply_preferences(dialog.preferences, dialog.use_as_default.isChecked())

    def apply_preferences(self, preferences, use_as_default=False):
        values = normalize_preferences(preferences)
        editing_changed = values["editing"] != self.preferences["editing"]

        def commit(pair=None):
            # Render and validate before changing either project or defaults.
            if use_as_default:
                self.state_directory.mkdir(parents=True, exist_ok=True)
                target = self.state_directory / "defaults.json"
                fd, temporary = tempfile.mkstemp(dir=self.state_directory, suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        json.dump(values, handle, allow_nan=False, indent=2)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, target)
                finally:
                    Path(temporary).unlink(missing_ok=True)
                self.default_preferences = copy.deepcopy(values)
            self.preferences = values
            self.sync_display_controls()
            self.autosave_timer.setInterval(int(values["session"]["autosave_seconds"] * 1000))
            if self.terrain:
                if editing_changed:
                    self.invalidate_preview()
                if pair is not None:
                    self.canvas.set_image(pair[0])
                    self.canvas.set_contours(pair[1])
                self.mark_dirty()
            self.statusBar().showMessage("Project settings applied")

        if self.terrain:
            style, azimuth, z_factor = self.view_style.currentText(), self.azimuth.value(), self.exaggeration.value()
            bounds = self.canvas.visible_bounds()
            def calculate():
                rgb = self.terrain.rgb(style, azimuth=azimuth, z_factor=z_factor, view_bounds=bounds, **display_kwargs(values))
                contours = self.make_contours(self.terrain, values["display"]["contour_interval"])
                return rgb, contours
            self.start_job("Applying project settings…", calculate, commit)
        else:
            try:
                commit()
            except OSError as exc:
                self.error(f"Could not save default settings: {exc}")

    def apply_preset(self, index):
        presets = {
            "Balanced": dict(corridor=12, smoothing=0, line_smoothing=0, terrain_weight=8, spacing=3, simplify=.75),
            "Levee / embankment": dict(corridor=12, smoothing=0, line_smoothing=0, terrain_weight=10, spacing=3, simplify=.5),
            "Fine ditch / crest": dict(corridor=6, smoothing=0, line_smoothing=0, terrain_weight=10, spacing=2, simplify=.5),
            "Broad channel": dict(corridor=24, smoothing=0, line_smoothing=0, terrain_weight=8, spacing=3, simplify=.75),
            "Noisy terrain": dict(corridor=12, smoothing=1, line_smoothing=1, terrain_weight=8, spacing=3, simplify=.75),
        }
        name = self.preset.currentText()
        if name in presets:
            for key, value in presets[name].items():
                self.param_widgets[key].setValue(value)
            if name == 'Noisy terrain':
                self.advanced_button.setChecked(True)

    def reproject_terrain(self):
        if self.busy or not self.terrain:
            return
        dialog = ReprojectDialog(self.terrain, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        destination, _ = QFileDialog.getSaveFileName(self, "Save reprojected terrain copy", str(Path(self.terrain.path).with_name(Path(self.terrain.path).stem + "_reprojected.tif")), "GeoTIFF (*.tif)")
        if not destination:
            return
        from .raster_ops import reproject_dem
        source = self.terrain.path
        target = dialog.target.text().strip()
        override = dialog.source.text().strip() or None
        resolution = dialog.resolution.value() or None
        resampling = dialog.resampling.currentData()
        def complete(path):
            self.statusBar().showMessage(f"Terrain copy saved: {path}")
            QMessageBox.information(self, "Terrain copy ready", f"Created {path}\n\nOpen this TIFF as a new terrain project when ready. Your current project remains open.")
        self.start_job("Reprojecting a new terrain copy…", lambda: reproject_dem(source, destination, target, resolution=resolution, resampling=resampling, source_crs=override, cancel=self._cancel_event.is_set), complete)

    @staticmethod
    def make_contours(terrain, interval):
        if not interval:
            return []
        from skimage.measure import find_contours
        low, high = terrain.metadata["min"], terrain.metadata["max"]
        count = int((high - low) / interval)
        if count > 80:
            raise ValueError("That contour interval would create more than 80 levels. Increase the interval in Project settings.")
        result = []
        total = 0
        for level in np.arange(math.ceil(low / interval) * interval, high, interval):
            for contour in find_contours(terrain.data, level, mask=terrain.valid):
                if len(contour) < 4:
                    continue
                # Display-only contours are reduced to avoid overwhelming Qt.
                contour = contour[::max(1, len(contour) // 1500)]
                result.append(contour)
                total += len(contour)
                if total > 200000:
                    raise ValueError("Contour display is too dense. Increase the contour interval.")
        return result
