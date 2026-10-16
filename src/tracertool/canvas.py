"""Qt scene for raster inspection and lightweight geographic line editing."""
from __future__ import annotations

import math
import numpy as np
from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPixmap, QPainterPath, QPen, QPainter, QFont
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsItem


COLORS = {"stream": "#5cc9ed", "ridge": "#ffcd70", "slope_break": "#ef9b6d", "manual": "#c4a8f0"}


class TerrainCanvas(QGraphicsView):
    anchorAdded = Signal(float, float)
    positionChanged = Signal(float, float)
    featureSelected = Signal(str)
    vertexMoved = Signal(int, float, float)
    vertexSelected = Signal(int)
    vertexInsertRequested = Signal(int, float, float)
    anchorMoved = Signal(int, float, float)
    anchorSelected = Signal(int)
    anchorInsertRequested = Signal(int, float, float)
    viewChanged = Signal()
    segmentPointSelected = Signal(int)
    deleteRequested = Signal()
    finishRequested = Signal()
    removeAnchorRequested = Signal()
    cancelRequested = Signal()

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor("#101e26"))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setMouseTracking(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.terrain = None
        self.raster_item = None
        self.mode = "pan"
        self.overlays = []
        self.anchors = []
        self.selected_anchor = None
        self.guide_edit = False
        self.features = []
        self.selected = None
        self.preview = None
        self.preview_kind = "stream"
        self.dragging_vertex = None
        self.dragging_anchor = None
        self.drag_position = None
        self.selected_vertex = None
        self.correction_range = None
        self.locked = False
        self.contours = []
        self.pan_origin = None
        self.pan_last = None
        self.press_pos = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.horizontalScrollBar().valueChanged.connect(self.viewChanged)
        self.verticalScrollBar().valueChanged.connect(self.viewChanged)

    def visible_bounds(self):
        """Half-open raster window covering the viewport, in row/column order."""
        if self.terrain is None:
            return None
        rect = self.mapToScene(self.viewport().rect()).boundingRect()
        return (max(0, math.floor(rect.top())), min(self.terrain.height, math.ceil(rect.bottom())),
                max(0, math.floor(rect.left())), min(self.terrain.width, math.ceil(rect.right())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.viewChanged.emit()

    def set_terrain(self, terrain, rgb):
        self.scene().clear()
        self.overlays.clear()
        self.terrain = terrain
        self.contours = []
        self.raster_item = None
        self.set_image(rgb)
        self.setSceneRect(QRectF(0, 0, terrain.width, terrain.height))
        self.fit()

    def set_image(self, rgb):
        rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
        image = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(image)
        if self.raster_item is None:
            self.raster_item = self.scene().addPixmap(pixmap)
            self.raster_item.setZValue(-100)
        else:
            self.raster_item.setPixmap(pixmap)

    def fit(self):
        if self.terrain:
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self.viewChanged.emit()

    def set_mode(self, mode):
        self.mode = mode
        self.setCursor(Qt.CursorShape.OpenHandCursor if mode == "pan" else Qt.CursorShape.CrossCursor)
        self.render_overlays()

    def set_overlays(self, features, selected=None, anchors=None, preview=None, kind="stream", selected_vertex=None, correction_range=None):
        self.features = features
        self.selected = selected
        self.anchors = anchors or []
        self.preview = preview
        self.preview_kind = kind
        self.selected_vertex = selected_vertex
        self.correction_range = correction_range
        self.render_overlays()

    def set_contours(self, contours):
        self.contours = contours
        self.render_overlays()

    def nearest_vertex(self, point):
        feature = next((f for f in self.features if f["id"] == self.selected and f.get("visible", True)), None)
        if not feature:
            return None
        candidates = []
        for i, coordinate in enumerate(feature["coordinates"]):
            r, c = self.terrain.rc(*coordinate[:2])
            p = self.mapFromScene(QPointF(c + .5, r + .5))
            distance = math.hypot(p.x() - point.x(), p.y() - point.y())
            if distance <= 12:
                candidates.append((distance, i))
        return min(candidates)[1] if candidates else None

    def nearest_edge(self, point):
        feature = next((f for f in self.features if f["id"] == self.selected and f.get("visible", True)), None)
        if not feature:
            return None
        positions = []
        for coordinate in feature["coordinates"]:
            r, c = self.terrain.rc(*coordinate[:2])
            p = self.mapFromScene(QPointF(c + .5, r + .5))
            positions.append((p.x(), p.y()))
        a = np.asarray(positions[:-1], float)
        delta = np.diff(positions, axis=0)
        cursor = np.array([point.x(), point.y()])
        fraction = np.clip(np.sum((cursor - a) * delta, axis=1) / np.maximum(np.sum(delta * delta, axis=1), 1e-10), 0, 1)
        distance = np.linalg.norm(a + fraction[:, None] * delta - cursor, axis=1)
        i = int(np.argmin(distance))
        return i if distance[i] <= 16 else None

    def nearest_guide_edge(self, point):
        if len(self.anchors) < 2:
            return None
        positions = [self.mapFromScene(QPointF(c + .5, r + .5)) for r, c in self.anchors]
        points = np.array([[p.x(), p.y()] for p in positions], dtype=float)
        delta = np.diff(points, axis=0)
        cursor = np.array([point.x(), point.y()])
        fractions = np.clip(np.sum((cursor - points[:-1]) * delta, axis=1) /
                            np.maximum(np.sum(delta * delta, axis=1), 1e-10), 0, 1)
        distances = np.linalg.norm(points[:-1] + fractions[:, None] * delta - cursor, axis=1)
        index = int(np.argmin(distances))
        return index if distances[index] <= 16 else None

    def _path(self, coordinates, color, width=2, dashed=False, feature_id=None):
        if not coordinates or not self.terrain:
            return
        path = QPainterPath()
        for i, c in enumerate(coordinates):
            row, col = self.terrain.rc(c[0], c[1])
            p = QPointF(col + 0.5, row + 0.5)
            path.moveTo(p) if i == 0 else path.lineTo(p)
        pen = QPen(QColor(color), width)
        pen.setCosmetic(True)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        item = self.scene().addPath(path, pen)
        item.setZValue(10)
        if feature_id:
            item.setData(0, feature_id)
        self.overlays.append(item)

    def _point(self, row, col, color, radius=4):
        pen = QPen(QColor("#0b1920"), 1.5)
        item = self.scene().addEllipse(-radius, -radius, radius * 2, radius * 2, pen, QColor(color))
        item.setPos(col + 0.5, row + 0.5)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        item.setZValue(30)
        self.overlays.append(item)

    def render_overlays(self):
        for item in self.overlays:
            self.scene().removeItem(item)
        self.overlays.clear()
        if not self.terrain:
            self.viewport().update()
            return
        for contour in self.contours:
            path = QPainterPath()
            for i, (row, col) in enumerate(contour):
                p = QPointF(col + .5, row + .5)
                path.moveTo(p) if i == 0 else path.lineTo(p)
            pen = QPen(QColor(220, 228, 211, 95), .8)
            pen.setCosmetic(True)
            item = self.scene().addPath(path, pen)
            item.setZValue(0)
            self.overlays.append(item)
        for feature in self.features:
            if not feature.get("visible", True):
                continue
            coords = feature["coordinates"]
            active = feature["id"] == self.selected
            if active and self.dragging_vertex is not None and self.drag_position is not None:
                coords = [list(c) for c in coords]
                coords[self.dragging_vertex][:2] = self.terrain.xy(*self.drag_position)
            if active:
                self._path(coords, "#102027", 6)
            self._path(coords, COLORS.get(feature["kind"], "#ffffff"), 3 if active else 2, feature_id=feature["id"])
            if active and self.correction_range:
                start, end = sorted(self.correction_range)
                self._path(coords[start:end + 1], "#f49ac1", 4, True)
            if active and self.mode in {"edit", "insert", "segment"}:
                for i, c in enumerate(coords):
                    r, col = self.terrain.rc(c[0], c[1])
                    self._point(r, col, "#ff70b7" if i == self.selected_vertex else "#ffffff", 5 if i == self.selected_vertex else 3)
        if self.preview:
            self._path(self.preview.coordinates, "#142229", 6)
            self._path(self.preview.coordinates, COLORS.get(self.preview_kind, "#ffffff"), 3, True)
        if len(self.anchors) > 1:
            xy = [self.terrain.xy(*(self.drag_position if i == self.dragging_anchor and self.drag_position is not None else a)) for i, a in enumerate(self.anchors)]
            self._path(xy, "#eff6f4", 1, True)
        for i, (r, c) in enumerate(self.anchors):
            if self.dragging_anchor == i and self.drag_position is not None:
                r, c = self.drag_position
            self._point(r, c, "#ff70b7" if i == self.selected_anchor else "#ffffff", 6 if i == self.selected_anchor else 5)
            label = self.scene().addSimpleText(str(i + 1), QFont("Sans Serif", 9))
            label.setBrush(QColor("white"))
            label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            label.setPos(c + 1, r + 1)
            label.setZValue(40)
            self.overlays.append(label)
        self.viewport().update()

    def wheelEvent(self, event):
        if not self.terrain:
            return
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        scale = self.transform().m11() * factor
        minimum = min(self.viewport().width() / self.terrain.width, self.viewport().height() / self.terrain.height) * .1
        if minimum < scale < max(80, minimum * 1000):
            self.scale(factor, factor)
            self.viewChanged.emit()
        event.accept()

    def mousePressEvent(self, event):
        self.setFocus()
        self.press_pos = event.position().toPoint()
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton) or ((self.mode == "pan" or self.locked) and event.button() == Qt.MouseButton.LeftButton):
            self.pan_origin = self.press_pos
            self.pan_last = self.press_pos
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if self.mode == "edit" and self.terrain:
            index = self.nearest_vertex(self.press_pos)
            if index is not None:
                self.selected_vertex = index
                self.vertexSelected.emit(index)
                self.dragging_vertex = index
                event.accept()
                return
        if self.mode not in {"pan", "edit", "insert", "segment"}:
            nearby = []
            for i, (r, c) in enumerate(self.anchors):
                p = self.mapFromScene(QPointF(c + .5, r + .5))
                distance = (p - self.press_pos).manhattanLength()
                if distance <= 10:
                    nearby.append((distance, i))
            if nearby:
                self.dragging_anchor = min(nearby)[1]
                self.selected_anchor = self.dragging_anchor
                self.anchorSelected.emit(self.selected_anchor)
                self.render_overlays()
        event.accept()

    def mouseMoveEvent(self, event):
        point = event.position().toPoint()
        if self.pan_last is not None:
            delta = point - self.pan_last
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            self.pan_last = point
        p = self.mapToScene(point)
        if self.terrain:
            self.positionChanged.emit(p.y() - 0.5, p.x() - 0.5)
        if self.dragging_vertex is not None or self.dragging_anchor is not None:
            self.drag_position = (p.y() - .5, p.x() - .5)
            self.render_overlays()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        point = event.position().toPoint()
        p = self.mapToScene(point)
        if self.pan_last is not None:
            moved = (point - self.pan_origin).manhattanLength() > 5
            self.pan_last = self.pan_origin = None
            self.setCursor(Qt.CursorShape.OpenHandCursor if self.mode == "pan" else Qt.CursorShape.CrossCursor)
            if not moved and event.button() == Qt.MouseButton.LeftButton and not self.locked:
                self._select(point)
            event.accept()
            return
        if self.dragging_vertex is not None:
            index, self.dragging_vertex = self.dragging_vertex, None
            self.drag_position = None
            if (point - self.press_pos).manhattanLength() > 2:
                self.vertexMoved.emit(index, p.y() - 0.5, p.x() - 0.5)
            self.render_overlays()
        elif self.dragging_anchor is not None:
            index, self.dragging_anchor = self.dragging_anchor, None
            self.drag_position = None
            if (point - self.press_pos).manhattanLength() > 2:
                self.anchorMoved.emit(index, p.y() - .5, p.x() - .5)
            self.render_overlays()
        elif event.button() == Qt.MouseButton.LeftButton and self.terrain:
            if self.mode == "segment":
                index = self.nearest_vertex(point)
                if index is not None:
                    self.segmentPointSelected.emit(index)
            elif self.mode == "insert":
                index = self.nearest_edge(point)
                if index is not None:
                    self.vertexInsertRequested.emit(index, p.y() - .5, p.x() - .5)
            elif self.mode == "edit":
                self._select(point)
            elif self.mode != "pan":
                if self.guide_edit or event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    index = self.nearest_guide_edge(point)
                    if index is not None:
                        self.anchorInsertRequested.emit(index, p.y() - .5, p.x() - .5)
                else:
                    self.anchorAdded.emit(p.y() - 0.5, p.x() - 0.5)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if self.mode == "edit" and not self.locked and self.terrain:
            point = event.position().toPoint()
            index = self.nearest_edge(point)
            if index is not None:
                p = self.mapToScene(point)
                self.dragging_vertex = None
                self.vertexInsertRequested.emit(index, p.y() - .5, p.x() - .5)
        elif self.mode not in {'pan', 'edit', 'insert', 'segment'} and not self.locked and self.terrain:
            # The second press of a quick click-then-drag is delivered as a
            # double-click. Pick up the guide just inserted/selected on the
            # first click instead of adding another point on release.
            self.mousePressEvent(event)
        event.accept()

    def _select(self, point):
        for item in self.items(QRectF(point.x() - 5, point.y() - 5, 10, 10).toRect()):
            if item.data(0):
                self.featureSelected.emit(item.data(0))
                break

    def keyPressEvent(self, event):
        if self.locked:
            if event.key() == Qt.Key.Key_Escape:
                self.cancelRequested.emit()
            elif event.key() == Qt.Key.Key_F:
                self.fit()
            return
        if event.key() in (Qt.Key.Key_Delete,):
            self.deleteRequested.emit()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.finishRequested.emit()
        elif event.key() == Qt.Key.Key_Escape:
            self.cancelRequested.emit()
        elif event.key() == Qt.Key.Key_Backspace:
            self.removeAnchorRequested.emit()
        elif event.key() == Qt.Key.Key_F:
            self.fit()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.terrain:
            painter.setPen(QColor("#b9d0da"))
            painter.setFont(QFont("Sans Serif", 22, QFont.Weight.Medium))
            rect = self.viewport().rect()
            painter.drawText(rect.adjusted(0, -50, 0, -50), Qt.AlignmentFlag.AlignCenter, "Follow the shape of the land.")
            painter.setFont(QFont("Sans Serif", 11))
            painter.setPen(QColor("#7b9aa9"))
            painter.drawText(rect.adjusted(0, 30, 0, 30), Qt.AlignmentFlag.AlignCenter, "Open a terrain GeoTIFF to start tracing ridges and streams.")
        else:
            scale = self.transform().m11()
            horizontal_resolution = abs(self.terrain.transform.a)
            target = 140 * horizontal_resolution / scale
            exponent = 10 ** math.floor(math.log10(max(target, 1e-8)))
            length = max(v for v in (1, 2, 5, 10) if v * exponent <= target) * exponent
            pixels = length / horizontal_resolution * scale
            y = self.viewport().height() - 28
            painter.fillRect(QRectF(15, y - 26, pixels + 30, 45), QColor(13, 28, 36, 215))
            painter.setPen(QPen(QColor("#e5eee9"), 2))
            painter.drawLine(QPointF(28, y), QPointF(28 + pixels, y))
            painter.drawLine(QPointF(28, y - 5), QPointF(28, y + 2))
            painter.drawLine(QPointF(28 + pixels, y - 5), QPointF(28 + pixels, y + 2))
            painter.setFont(QFont("Sans Serif", 9))
            painter.drawText(QPointF(28, y - 10), f"{length:g} {self.terrain.units}")
            painter.drawText(self.viewport().width() - 40, 30, "N ↑")
        painter.end()


class ProfileWidget(QGraphicsView):
    """Small elevation chart; no external plotting dependency."""
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(120)
        self.setMaximumHeight(160)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.coordinates = []

    def set_coordinates(self, coordinates):
        self.coordinates = coordinates or []
        self.viewport().update()

    def paintEvent(self, event):
        painter = QPainter(self.viewport())
        painter.fillRect(self.viewport().rect(), QColor("#101f28"))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(QFont("Sans Serif", 9))
        painter.setPen(QColor("#8eacb9"))
        if len(self.coordinates) < 2:
            painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter, "Select a line to inspect its elevation")
            painter.end()
            return
        c = np.asarray(self.coordinates)
        d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(c[:, :2], axis=0), axis=1))]
        z = c[:, 2]
        low, high = float(np.min(z)), float(np.max(z))
        rect = QRectF(42, 20, self.viewport().width() - 56, self.viewport().height() - 45)
        path = QPainterPath()
        for i in range(len(c)):
            p = QPointF(rect.left() + d[i] / max(d[-1], 1e-9) * rect.width(), rect.bottom() - (z[i] - low) / max(high - low, 1e-9) * rect.height())
            path.moveTo(p) if i == 0 else path.lineTo(p)
        painter.setPen(QPen(QColor("#34515f"), 1))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.setPen(QPen(QColor("#5cc9ed"), 2))
        painter.drawPath(path)
        painter.setPen(QColor("#9bb6c1"))
        painter.drawText(3, 24, f"{high:.1f}")
        painter.drawText(3, int(rect.bottom()), f"{low:.1f}")
        painter.drawText(int(rect.left()), self.viewport().height() - 7, "0")
        painter.drawText(int(rect.right()) - 65, self.viewport().height() - 7, f"{d[-1]:,.1f}")
        painter.end()
