"""Image rendering, ROI overlays and interactive spatial cropping."""
import cv2
import numpy as np
from PySide6.QtCore import Qt, Signal, QRect, QPoint, QRectF
from PySide6.QtGui import QImage, QPixmap, QPainter, QPainterPath, QPen, QColor
from PySide6.QtWidgets import QLabel, QFrame, QPushButton, QHBoxLayout, QVBoxLayout, QGridLayout, QSizePolicy, QWidget


CAMERA_HEADER_HEIGHT = 46
CAMERA_HEADER_GAP = 8


def gray8(frame):
    a = np.squeeze(np.asarray(frame))
    if a.ndim == 3 and a.shape[-1] in (3, 4):
        return a
    if a.ndim == 3:
        a = a[0]
    if a.ndim != 2:
        raise ValueError(f"Unsupported TIFF frame shape: {a.shape}")
    a = a.astype(np.float32)
    lo, hi = np.nanpercentile(a, [1, 99])
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        lo, hi = float(np.nanmin(a)), float(np.nanmax(a))
    if hi <= lo:
        return np.zeros(a.shape, dtype=np.uint8)
    return np.clip((a - lo) * 255.0 / (hi - lo), 0, 255).astype(np.uint8)


def pixmap_from_array(frame, bgr=False):
    a = gray8(frame)
    if a.ndim == 2:
        h, w = a.shape
        q = QImage(a.data, w, h, int(a.strides[0]), QImage.Format_Grayscale8).copy()
        return QPixmap.fromImage(q)
    if a.shape[-1] == 3:
        rgb = cv2.cvtColor(a, cv2.COLOR_BGR2RGB) if bgr else a
        h, w, _ = rgb.shape
        q = QImage(rgb.data, w, h, int(rgb.strides[0]), QImage.Format_RGB888).copy()
        return QPixmap.fromImage(q)
    rgba = cv2.cvtColor(a, cv2.COLOR_BGRA2RGBA) if bgr else a
    h, w, _ = rgba.shape
    q = QImage(rgba.data, w, h, int(rgba.strides[0]), QImage.Format_RGBA8888).copy()
    return QPixmap.fromImage(q)


class CropImageLabel(QLabel):
    cropSelected = Signal(object)

    def __init__(self, text="No file loaded"):
        super().__init__(text)
        self.crop_enabled = False
        self.crop_rect = None  # source-image coordinates: (x, y, w, h)
        self.source_width = 0
        self.source_height = 0
        self.dragging = False
        self.drag_start = QPoint()
        self.drag_current = QPoint()
        self.setMouseTracking(True)

    def set_source_size(self, width, height):
        self.source_width = int(width)
        self.source_height = int(height)
        self.update()

    def set_crop_enabled(self, enabled):
        self.crop_enabled = bool(enabled)
        self.setCursor(Qt.CrossCursor if self.crop_enabled else Qt.ArrowCursor)
        if not enabled:
            self.dragging = False
        self.update()

    def set_crop_rect(self, rect):
        self.crop_rect = tuple(rect) if rect is not None else None
        self.update()

    def clear_crop(self):
        self.crop_rect = None
        self.dragging = False
        self.update()

    def _displayed_pixmap_rect(self):
        pm = self.pixmap()
        if pm is None or pm.isNull():
            return QRect()
        w = pm.width()
        h = pm.height()
        x = (self.width() - w) // 2
        y = (self.height() - h) // 2
        return QRect(x, y, w, h)

    def _clamp_to_display(self, p):
        r = self._displayed_pixmap_rect()
        if r.isNull():
            return p
        x = min(max(p.x(), r.left()), r.right())
        y = min(max(p.y(), r.top()), r.bottom())
        return QPoint(x, y)

    def _widget_rect_to_source(self, rect):
        display = self._displayed_pixmap_rect()
        if display.isNull() or self.source_width <= 0 or self.source_height <= 0:
            return None

        rect = rect.normalized().intersected(display)
        if rect.width() < 6 or rect.height() < 6:
            return None

        sx = self.source_width / float(display.width())
        sy = self.source_height / float(display.height())

        x0 = int(np.floor((rect.left() - display.left()) * sx))
        y0 = int(np.floor((rect.top() - display.top()) * sy))
        x1 = int(np.ceil((rect.right() + 1 - display.left()) * sx))
        y1 = int(np.ceil((rect.bottom() + 1 - display.top()) * sy))

        x0 = int(np.clip(x0, 0, self.source_width - 1))
        y0 = int(np.clip(y0, 0, self.source_height - 1))
        x1 = int(np.clip(x1, x0 + 1, self.source_width))
        y1 = int(np.clip(y1, y0 + 1, self.source_height))
        return (x0, y0, x1 - x0, y1 - y0)

    def _source_rect_to_widget(self, rect):
        if rect is None:
            return QRect()
        display = self._displayed_pixmap_rect()
        if display.isNull() or self.source_width <= 0 or self.source_height <= 0:
            return QRect()
        x, y, w, h = rect
        sx = display.width() / float(self.source_width)
        sy = display.height() / float(self.source_height)
        return QRect(
            int(round(display.left() + x * sx)),
            int(round(display.top() + y * sy)),
            max(1, int(round(w * sx))),
            max(1, int(round(h * sy))),
        )

    def mousePressEvent(self, event):
        if self.crop_enabled and event.button() == Qt.LeftButton:
            display = self._displayed_pixmap_rect()
            if display.contains(event.position().toPoint()):
                self.dragging = True
                self.drag_start = self._clamp_to_display(event.position().toPoint())
                self.drag_current = self.drag_start
                self.update()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.drag_current = self._clamp_to_display(event.position().toPoint())
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.dragging and event.button() == Qt.LeftButton:
            self.drag_current = self._clamp_to_display(event.position().toPoint())
            widget_rect = QRect(self.drag_start, self.drag_current).normalized()
            source_rect = self._widget_rect_to_source(widget_rect)
            self.dragging = False
            if source_rect is not None:
                self.crop_rect = source_rect
                self.cropSelected.emit(source_rect)
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        display = self._displayed_pixmap_rect()
        if display.isNull():
            return

        selection = QRect()
        if self.dragging:
            selection = QRect(self.drag_start, self.drag_current).normalized().intersected(display)
        elif self.crop_rect is not None:
            selection = self._source_rect_to_widget(self.crop_rect).intersected(display)

        if selection.isNull():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        shade = QColor(4, 13, 22, 145)
        # Shade only the displayed image area outside the selection.
        painter.fillRect(QRect(display.left(), display.top(), display.width(), max(0, selection.top() - display.top())), shade)
        painter.fillRect(QRect(display.left(), selection.bottom() + 1, display.width(), max(0, display.bottom() - selection.bottom())), shade)
        painter.fillRect(QRect(display.left(), selection.top(), max(0, selection.left() - display.left()), selection.height()), shade)
        painter.fillRect(QRect(selection.right() + 1, selection.top(), max(0, display.right() - selection.right()), selection.height()), shade)

        painter.setPen(QPen(QColor("#17B9DC"), 2))
        painter.drawRoundedRect(selection.adjusted(1, 1, -1, -1), 3, 3)
        painter.end()


class ImagePanel(QFrame):
    cropChanged = Signal(object)
    exportCropRequested = Signal()

    def __init__(self, title, accent, croppable=False):
        super().__init__()
        self.setObjectName("viewerCard")
        self.croppable = croppable

        dot = QLabel("●")
        dot.setObjectName("accentDot")
        dot.setStyleSheet(f"color:{accent};")
        self.accent_dot = dot

        title_label = QLabel(title)
        title_label.setObjectName("panelTitle")
        self.title_label = title_label

        header = QHBoxLayout()
        self.header_layout = header
        header.setSpacing(8)
        header.addWidget(dot)
        header.addWidget(title_label)

        if croppable:
            self.crop_btn = QPushButton("Crop")
            self.crop_btn.setProperty("variant", "viewerTool")
            self.crop_btn.setCheckable(True)
            self.crop_btn.setEnabled(False)
            self.crop_btn.setCursor(Qt.PointingHandCursor)
            self.crop_btn.setToolTip("Click, then drag directly on the behavior frame to choose the crop.")

            self.crop_reset_btn = QPushButton("Reset")
            self.crop_reset_btn.setProperty("variant", "viewerTool")
            self.crop_reset_btn.setEnabled(False)
            self.crop_reset_btn.setCursor(Qt.PointingHandCursor)

            self.crop_export_btn = QPushButton("Export")
            self.crop_export_btn.setProperty("variant", "viewerToolAccent")
            self.crop_export_btn.setEnabled(False)
            self.crop_export_btn.setCursor(Qt.PointingHandCursor)
            self.crop_export_btn.setToolTip("Export the full behavior video using the selected spatial crop.")

            header.addWidget(self.crop_btn)
            header.addWidget(self.crop_reset_btn)
            header.addWidget(self.crop_export_btn)

            self.image = CropImageLabel("No file loaded")
            self.crop_btn.toggled.connect(self.image.set_crop_enabled)
            self.crop_reset_btn.clicked.connect(self.clear_crop)
            self.crop_export_btn.clicked.connect(self.exportCropRequested.emit)
            self.image.cropSelected.connect(self._crop_selected)
        else:
            self.image = QLabel("No file loaded")

        header.addStretch()
        self.image.setObjectName("imageCanvas")
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumHeight(240)
        # The displayed pixmap must not become a new minimum layout size:
        # resizing it otherwise feeds back into the next layout pass.
        self.image.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        header_widget = QWidget()
        self.header_widget = header_widget
        header_widget.setLayout(header)
        header_widget.setFixedHeight(CAMERA_HEADER_HEIGHT)
        header.setContentsMargins(0, 0, 0, 0)
        for index in range(header.count()):
            widget = header.itemAt(index).widget()
            if widget is not None:
                header.setAlignment(widget, Qt.AlignVCenter)
        lay = QGridLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.image, 0, 0)
        self.container = QWidget()
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(CAMERA_HEADER_GAP)
        container_layout.addWidget(self.header_widget)
        container_layout.addWidget(self, 1)
        self.pm = None
        self.roi_path = None
        self.roi_shape = None

    def add_header_widget(self, widget):
        self.header_layout.insertWidget(self.header_layout.count() - 1, widget)

    def set_roi(self, footprint):
        self.roi_path = None
        self.roi_shape = None
        if footprint is not None:
            finite = np.where(np.isfinite(footprint), footprint, 0)
            peak = float(np.max(finite))
            if peak > 0:
                mask = (finite >= peak * .2).astype(np.uint8)
                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                path = QPainterPath()
                for contour in contours:
                    points = contour[:, 0, :]
                    if len(points) < 3:
                        continue
                    path.moveTo(float(points[0, 0]), float(points[0, 1]))
                    for x, y in points[1:]:
                        path.lineTo(float(x), float(y))
                    path.closeSubpath()
                self.roi_path = path
                self.roi_shape = footprint.shape
        self._fit()

    def set_crop_available(self, available):
        if not self.croppable:
            return
        self.crop_btn.setEnabled(bool(available))
        if not available:
            self.clear_crop()

    def _crop_selected(self, rect):
        self.crop_reset_btn.setEnabled(True)
        self.crop_export_btn.setEnabled(True)
        self.crop_btn.setChecked(False)
        self.cropChanged.emit(rect)

    def set_crop_rect(self, rect):
        if not self.croppable:
            return
        self.image.set_crop_rect(rect)
        has_crop = rect is not None
        self.crop_reset_btn.setEnabled(has_crop)
        self.crop_export_btn.setEnabled(has_crop)

    def clear_crop(self):
        if not self.croppable:
            return
        self.image.clear_crop()
        self.crop_btn.setChecked(False)
        self.crop_reset_btn.setEnabled(False)
        self.crop_export_btn.setEnabled(False)
        self.cropChanged.emit(None)

    def set_frame(self, frame, info, bgr=False):
        self.image.setToolTip(info)
        if frame is None:
            self.pm = None
            self.image.setPixmap(QPixmap())
            self.image.setText("No frame available")
        else:
            if self.croppable:
                self.image.set_source_size(frame.shape[1], frame.shape[0])
            self.pm = pixmap_from_array(frame, bgr=bgr)
            self.image.setText("")
            self._fit()

    def _fit(self):
        if self.pm is not None and not self.pm.isNull():
            display_pm = self.pm
            if self.roi_path is not None and self.roi_shape == (self.pm.height(), self.pm.width()):
                display_pm = self.pm.copy()
                painter = QPainter(display_pm)
                painter.setRenderHint(QPainter.Antialiasing)
                painter.setPen(QPen(QColor("#12C4BE"), max(1.5, self.pm.width() / 300)))
                painter.drawPath(self.roi_path)
                painter.end()
            self.image.setPixmap(
                display_pm.scaled(
                    self.image.contentsRect().size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
            if self.croppable:
                self.image.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()
