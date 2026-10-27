#!/usr/bin/env python3
import sys
import json
import csv
from datetime import datetime
from pathlib import Path
from collections import OrderedDict

import cv2
import numpy as np
import pandas as pd
import pyqtgraph as pg
import tifffile
from caiman_results import CaImAnResults
from movement_dialog import MovementAnalysisDialog
from PySide6.QtCore import Qt, QTimer, Signal, QRect, QPoint, QPointF, QSize, QRectF
from PySide6.QtGui import QImage, QPixmap, QIcon, QPainter, QPainterPath, QPen, QColor
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QDialog,
    QSpinBox, QSplitter, QVBoxLayout, QWidget, QToolTip, QProgressDialog,
    QSizePolicy, QTabWidget, QCheckBox, QSlider
)


def load_csv(path, label):
    df = pd.read_csv(path).copy()
    for col in ("frame", "timestamp_ms"):
        if col not in df.columns:
            raise ValueError(f"{label}: missing column '{col}'")
    df["frame"] = pd.to_numeric(df["frame"], errors="raise").astype(int)
    df["timestamp_ms"] = pd.to_numeric(df["timestamp_ms"], errors="raise").astype(float)
    if len(df) == 0:
        raise ValueError(f"{label}: empty CSV")
    if np.any(np.diff(df["timestamp_ms"].to_numpy()) < 0):
        raise ValueError(f"{label}: timestamps are not ordered")
    return df


def median_period(times):
    if times is None or len(times) < 2:
        return np.nan
    d = np.diff(times)
    d = d[d > 0]
    return float(np.median(d)) if len(d) else np.nan


def virtual_camera_indices(times):
    n = len(times)
    out = np.arange(n, dtype=int)
    if n < 2:
        return out
    p = median_period(times)
    if not np.isfinite(p) or p <= 0:
        return out
    steps = np.maximum(1, np.rint(np.diff(times) / p).astype(int))
    out = np.zeros(n, dtype=int)
    for i, step in enumerate(steps, start=1):
        out[i] = out[i - 1] + int(step)
    return out


def fill_camera_timestamps(df):
    """Fill missing camera periods between recorded TTLs, in Arduino time."""
    times = df.timestamp_ms.to_numpy(float)
    indices = virtual_camera_indices(times)
    if len(indices) < 2 or indices[-1] == len(indices) - 1:
        return df.copy()

    frame_indices = np.arange(indices[-1] + 1)
    filled = df.set_axis(indices).reindex(frame_indices).copy()
    # Keep measured endpoints and distribute missing frames evenly between them.
    filled["timestamp_ms"] = np.interp(frame_indices, indices, times)
    filled["frame"] = int(df.frame.iloc[0]) + frame_indices
    if "elapsed_ms" in filled.columns:
        filled["elapsed_ms"] = filled.timestamp_ms - times[0]
    return filled.reset_index(drop=True)


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


class Cache:
    def __init__(self, n=50):
        self.n = n
        self.d = OrderedDict()

    def get(self, k):
        if k not in self.d:
            return None
        v = self.d.pop(k)
        self.d[k] = v
        return v

    def put(self, k, v):
        if k in self.d:
            self.d.pop(k)
        self.d[k] = v
        while len(self.d) > self.n:
            self.d.popitem(last=False)

    def clear(self):
        self.d.clear()


class VideoReader:
    def __init__(self):
        self.cap = None
        self.count = 0
        self.fps = np.nan
        self.cache = Cache(80)
        self.path = None
        self.width = 0
        self.height = 0

    def open(self, path):
        self.close()
        self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open video: {path}")
        self.path = Path(path)
        self.count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = float(self.cap.get(cv2.CAP_PROP_FPS))
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    def read(self, idx):
        if self.cap is None or idx < 0 or idx >= self.count:
            return None
        c = self.cache.get(idx)
        if c is not None:
            return c
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, frame = self.cap.read()
        if not ok:
            return None
        self.cache.put(idx, frame)
        return frame

    def close(self):
        if self.cap is not None:
            self.cap.release()
        self.cap = None
        self.count = 0
        self.fps = np.nan
        self.cache.clear()
        self.path = None
        self.width = 0
        self.height = 0


class TiffReader:
    def __init__(self):
        self.tif = None
        self.count = 0
        self.cache = Cache(40)

    def open(self, path):
        self.close()
        self.tif = tifffile.TiffFile(str(path))
        self.count = len(self.tif.pages)
        if self.count == 0:
            raise RuntimeError("TIFF contains no pages")

    def read(self, idx):
        if self.tif is None or idx < 0 or idx >= self.count:
            return None
        c = self.cache.get(idx)
        if c is not None:
            return c
        frame = self.tif.pages[idx].asarray()
        self.cache.put(idx, frame)
        return frame

    def close(self):
        if self.tif is not None:
            self.tif.close()
        self.tif = None
        self.count = 0
        self.cache.clear()


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

        title_label = QLabel(title)
        title_label.setObjectName("panelTitle")
        self.title_label = title_label

        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(dot)
        header.addWidget(title_label)
        header.addStretch()

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

        self.image.setObjectName("imageCanvas")
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumHeight(240)
        self.image.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(15, 14, 15, 13)
        lay.setSpacing(9)
        lay.addLayout(header)
        lay.addWidget(self.image, 1)
        self.pm = None
        self.roi_path = None
        self.roi_shape = None

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
                    self.image.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
            if self.croppable:
                self.image.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()


class TrackingAlignmentDialog(QDialog):
    """Timestamp-based tracking and behavior-frame alignment.

    Tracking frame indices refer to the loaded behavior video. Camera times
    use Arduino STROBE timestamps within the selected trim and TTL coverage.
    """

    def __init__(self, viewer):
        super().__init__(viewer)
        self.viewer = viewer
        self.tracking_path = None
        self.tracking_df = None
        self.numeric_data = {}
        self.video_times = None
        self.result_df = None
        self.target_times = None
        self.target_x = None
        self.target_video_indices = None

        self.setWindowTitle("Tracking alignment")
        self.resize(1120, 720)
        self.setMinimumSize(900, 620)
        self.setModal(False)
        self.build_ui()
        viewer.alignment_changed.connect(self.invalidate_alignment)
        viewer.theme_changed.connect(self.apply_theme)
        self.base_stylesheet = self.styleSheet()
        self.apply_theme(viewer.day_mode)

    def apply_theme(self, day_mode):
        stylesheet = self.base_stylesheet
        if day_mode:
            for original, replacement in (
                ("#F3F7F9", "#F2EEE5"), ("#FFFFFF", "#FAF7F0"),
                ("background: white", "background: #F8F5EE"),
                ("#D9E7EE", "#DED8CC"), ("#C9DCE6", "#D2CCBF"),
                ("#EAF3F7", "#E8E2D6"), ("#6A8193", "#686B61"),
            ):
                stylesheet = stylesheet.replace(original, replacement)
            stylesheet += """
                QLabel { color: #454D46; }
                QComboBox QAbstractItemView {
                    background: #F8F5EE; color: #454D46;
                    selection-background-color: #DDEAE1;
                    selection-color: #25675C;
                }
            """
        self.setStyleSheet(stylesheet)
        for plot in (self.time_plot, self.frame_plot):
            plot.setBackground("#FAF7F0" if day_mode else "#FFFFFF")

    def build_ui(self):
        self.setStyleSheet("""
            QDialog { background: #F3F7F9; color: #13263A; }
            QLabel#title { font-size: 22px; font-weight: 700; color: #102A43; }
            QLabel#subtitle { color: #6A8193; font-size: 12px; }
            QLabel#small { color: #6A8193; font-size: 11px; }
            QFrame#toolbar, QFrame#statusCard {
                background: #FFFFFF;
                border: 1px solid #D9E7EE;
                border-radius: 14px;
            }
            QPushButton {
                min-height: 32px;
                border-radius: 10px;
                border: 1px solid #C9DCE6;
                background: #FFFFFF;
                color: #15364D;
                padding: 6px 12px;
                font-weight: 600;
            }
            QPushButton:hover { background: #EDF8FB; border-color: #8FDDE5; }
            QPushButton[variant="primary"] {
                background: #12BFC0;
                color: white;
                border-color: #12BFC0;
            }
            QPushButton[variant="blue"] {
                background: #1479E8;
                color: white;
                border-color: #1479E8;
            }
            QComboBox, QSpinBox {
                min-height: 32px;
                border-radius: 10px;
                border: 1px solid #C9DCE6;
                background: white;
                color: #15364D;
                padding: 4px 9px;
            }
            QTabWidget::pane {
                border: 1px solid #D9E7EE;
                border-radius: 12px;
                background: #FFFFFF;
                top: -1px;
            }
            QTabBar::tab {
                background: #EAF3F7;
                color: #557084;
                padding: 8px 14px;
                margin-right: 4px;
                border-top-left-radius: 9px;
                border-top-right-radius: 9px;
                font-weight: 600;
            }
            QTabBar::tab:selected {
                background: #FFFFFF;
                color: #10344D;
            }
            QToolTip { background:#102131; color:#EAF6FB; border:1px solid #1B4964; }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        head = QVBoxLayout()
        head.setSpacing(2)
        title = QLabel("Tracking alignment")
        title.setObjectName("title")
        subtitle = QLabel(
            "Align tracking using Arduino timestamps within the selected trim. "
            "Keep camera timestamps or interpolate position onto Mini2P frames."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        head.addWidget(title)
        head.addWidget(subtitle)
        root.addLayout(head)

        toolbar = QFrame()
        toolbar.setObjectName("toolbar")
        bar = QHBoxLayout(toolbar)
        bar.setContentsMargins(12, 10, 12, 10)
        bar.setSpacing(8)

        self.load_btn = QPushButton("Load tracking CSV")
        self.load_btn.setToolTip(
            "One row per video frame, or use frame_index (starting at 0) / frame (starting at 1)."
        )
        self.load_btn.clicked.connect(self.load_tracking)
        bar.addWidget(self.load_btn)

        bar.addWidget(QLabel("X column"))
        self.x_combo = QComboBox()
        self.x_combo.setMinimumWidth(190)
        self.x_combo.currentIndexChanged.connect(self.invalidate_alignment)
        bar.addWidget(self.x_combo)

        bar.addWidget(QLabel("Target"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "Camera timestamps",
            "Mini2P frames (1:1)",
        ])
        self.mode_combo.setCurrentIndex(1)
        self.mode_combo.setMinimumWidth(210)
        self.mode_combo.currentIndexChanged.connect(self.invalidate_alignment)
        bar.addWidget(self.mode_combo)

        self.align_btn = QPushButton("Align")
        self.align_btn.setProperty("variant", "primary")
        self.align_btn.clicked.connect(self.align_tracking)
        bar.addWidget(self.align_btn)
        bar.addStretch()

        self.export_csv_btn = QPushButton("Export CSV")
        self.export_csv_btn.clicked.connect(self.export_csv)
        bar.addWidget(self.export_csv_btn)

        self.export_video_btn = QPushButton("Export aligned video")
        self.export_video_btn.setProperty("variant", "blue")
        self.export_video_btn.clicked.connect(self.export_video)
        bar.addWidget(self.export_video_btn)
        root.addWidget(toolbar)

        gap_row = QHBoxLayout()
        gap_row.addWidget(QLabel("Max missing tracking frames to interpolate"))
        self.max_missing_frames = QSpinBox()
        self.max_missing_frames.setRange(0, 1000)
        self.max_missing_frames.setValue(2)
        self.max_missing_frames.setToolTip("Longer gaps remain empty. Set 0 to keep every missing position empty.")
        self.max_missing_frames.valueChanged.connect(self.invalidate_alignment)
        gap_row.addWidget(self.max_missing_frames)
        gap_row.addStretch()
        root.addLayout(gap_row)

        # Two deliberately different views:
        # 1) real time for validating synchronization,
        # 2) aligned-frame index for inspecting the exported series.
        self.plot_tabs = QTabWidget()

        self.time_plot = pg.PlotWidget()
        self.time_plot.setBackground("#FFFFFF")
        self.time_plot.showGrid(x=True, y=True, alpha=0.08)
        self.time_plot.setLabel("bottom", "time (s)")
        self.time_plot.setLabel("left", "X position")
        for axis_name in ("bottom", "left"):
            axis = self.time_plot.getAxis(axis_name)
            axis.setPen(pg.mkPen("#A9BAC5"))
            axis.setTextPen(pg.mkPen("#455D6D"))
        self.raw_curve = self.time_plot.plot([], [], pen=pg.mkPen("#B7BCC0", width=2), name="raw tracking")
        self.aligned_curve = self.time_plot.plot([], [], pen=pg.mkPen("#10BFC3", width=2.2), name="timestamp-aligned")
        time_legend = self.time_plot.addLegend(offset=(-10, 10))
        try:
            time_legend.addItem(self.raw_curve, "raw tracking")
            time_legend.addItem(self.aligned_curve, "timestamp-aligned")
        except Exception:
            pass

        self.frame_plot = pg.PlotWidget()
        self.frame_plot.setBackground("#FFFFFF")
        self.frame_plot.showGrid(x=True, y=True, alpha=0.08)
        self.frame_plot.setLabel("bottom", "aligned frame")
        self.frame_plot.setLabel("left", "X position")
        for axis_name in ("bottom", "left"):
            axis = self.frame_plot.getAxis(axis_name)
            axis.setPen(pg.mkPen("#A9BAC5"))
            axis.setTextPen(pg.mkPen("#455D6D"))
        self.frame_curve = self.frame_plot.plot([], [], pen=pg.mkPen("#10BFC3", width=2.2), name="timestamp-aligned")
        frame_legend = self.frame_plot.addLegend(offset=(-10, 10))
        try:
            frame_legend.addItem(self.frame_curve, "timestamp-aligned")
        except Exception:
            pass

        self.plot_tabs.addTab(self.time_plot, "Time comparison")
        self.plot_tabs.addTab(self.frame_plot, "Aligned frames")
        root.addWidget(self.plot_tabs, 1)

        status_card = QFrame()
        status_card.setObjectName("statusCard")
        status_lay = QHBoxLayout(status_card)
        status_lay.setContentsMargins(12, 9, 12, 9)
        self.status = QLabel("Load a tracking CSV. One row should correspond to one behavior-video frame.")
        self.status.setObjectName("small")
        self.status.setWordWrap(True)
        status_lay.addWidget(self.status, 1)
        root.addWidget(status_card)

    def invalidate_alignment(self):
        self.result_df = None
        self.target_times = None
        self.target_x = None
        self.target_video_indices = None
        self.video_times = None
        if hasattr(self, "raw_curve"):
            self.raw_curve.setData([], [])
            self.aligned_curve.setData([], [])
            self.frame_curve.setData([], [])
            self.status.setText("Settings changed. Press Align to update the result.")

    def load_tracking_table(self, path):
        # Detect DLC headers before looking for numeric columns: its coordinate
        # rows otherwise pass the flat-CSV heuristic and shift frames by two.
        with open(path, newline="", encoding="utf-8-sig") as handle:
            header = [next(csv.reader(handle), []) for _ in range(3)]
        is_dlc = (len(header[2]) > 1 and len(header[1]) > 0 and header[2][0].strip().lower() == "coords"
                  and header[1][0].strip().lower() == "bodyparts")
        if is_dlc:
            table = pd.read_csv(path, header=[0, 1, 2], index_col=0)
            table.columns = [".".join(str(part) for part in col[1:]) for col in table.columns]
            table = table.reset_index(names="frame_index")
        else:
            table = pd.read_csv(path)
        numeric = {}
        for col in table.columns:
            if self.is_frame_column(col):
                continue
            vals = pd.to_numeric(table[col], errors="coerce")
            if vals.notna().sum() >= 2:
                numeric[str(col)] = vals.to_numpy(float)
        return table, numeric

    @staticmethod
    def is_frame_column(name):
        key = str(name).lower().strip().replace(" ", "_")
        return key in {"frame", "frame_index", "frame_idx", "frame_number", "frame_id", "index", "unnamed:_0"}

    def tracking_indices(self, n_video=None):
        columns = [col for col in self.tracking_df.columns if self.is_frame_column(col)]
        if columns:
            col = columns[0]
            values = pd.to_numeric(self.tracking_df[col], errors="raise").to_numpy(float)
            if not np.all(np.isfinite(values)) or not np.all(values == np.floor(values)):
                raise ValueError("Tracking frame indices must be finite integers.")
            key = str(col).lower().strip().replace(" ", "_")
            # Index columns (including DLC) are zero-based; frame numbers start
            # at one unless an explicit zero identifies a zero-based export.
            zero_based = key in {"frame_index", "frame_idx", "index", "unnamed:_0"} or np.any(values == 0)
            indices = values.astype(int) - (0 if zero_based else 1)
            if np.any(indices < 0) or np.any(np.diff(indices) <= 0):
                raise ValueError("Tracking frame indices must be non-negative, unique and increasing.")
            if n_video is not None and np.any(indices >= n_video):
                raise ValueError("Tracking frame indices exceed the loaded MP4. Load the video used for tracking.")
            return indices
        if n_video is not None and len(self.tracking_df) != n_video:
            raise ValueError(
                f"Tracking has {len(self.tracking_df)} rows but the MP4 has {n_video} frames. "
                "Load the matching video or include a frame_index (zero-based) or frame (one-based) column."
            )
        return np.arange(len(self.tracking_df))

    def load_tracking(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load tracking CSV", "", "CSV files (*.csv);;All files (*)")
        if not path:
            return
        try:
            df, numeric = self.load_tracking_table(path)
            if not numeric:
                raise ValueError("No numeric tracking columns were detected.")
            self.tracking_path = Path(path)
            self.tracking_df = df
            self.numeric_data = numeric
            self.x_combo.clear()
            self.x_combo.addItems(list(numeric.keys()))
            # Prefer an x-coordinate-looking column.
            names = list(numeric.keys())
            preferred = None
            for i, name in enumerate(names):
                low = name.lower().strip()
                if low == "x" or low.endswith(".x") or low.endswith("_x") or "x-position" in low:
                    preferred = i
                    break
            if preferred is not None:
                self.x_combo.setCurrentIndex(preferred)
            self.invalidate_alignment()
            n = len(next(iter(numeric.values())))
            self.status.setText(f"Loaded {self.tracking_path.name} · {n} tracking rows · choose the X column and press Align.")
        except Exception as exc:
            QMessageBox.critical(self, "Tracking CSV", f"{type(exc).__name__}: {exc}")

    def build_video_times(self, n_frames):
        v = self.viewer
        if v.camera_t is None or v.camera_virtual is None:
            raise RuntimeError("Load camera and Mini2P TTL CSV files in the main window first.")
        if n_frames <= 0:
            raise RuntimeError("No behavior frames are available.")

        _, camera_t = v.visible_timeline_times()
        known_idx = np.asarray([v.video_index(i) for i in range(len(camera_t))], dtype=int)
        valid = (known_idx >= 0) & (known_idx < n_frames) & np.isfinite(camera_t)
        known_idx, known_t = known_idx[valid], camera_t[valid]
        if len(known_idx) < 2:
            raise ValueError("Not enough camera timestamps map onto behavior frames within the trim.")
        if np.any(np.diff(known_idx) <= 0) or np.any(np.diff(known_t) <= 0):
            raise ValueError("Camera frame indices and timestamps must be strictly increasing.")
        # No video times are invented before the first or after the last TTL.
        return np.interp(np.arange(n_frames), known_idx, known_t, left=np.nan, right=np.nan)

    @staticmethod
    def interpolation_map(source_times, target_times):
        source_times = np.asarray(source_times, dtype=float)
        target_times = np.asarray(target_times, dtype=float)
        left = np.full(len(target_times), -1, dtype=int)
        right = left.copy()
        nearest = left.copy()
        alpha = np.full(len(target_times), np.nan)
        if not len(source_times):
            return left, right, alpha, nearest
        if not np.all(np.isfinite(source_times)) or np.any(np.diff(source_times) <= 0):
            raise ValueError("Interpolation timestamps must be finite and strictly increasing.")
        covered = (target_times >= source_times[0]) & (target_times <= source_times[-1])
        times = target_times[covered]
        r = np.searchsorted(source_times, times, side="left")
        l = np.maximum(r - 1, 0)
        exact = source_times[r] == times
        l[exact] = r[exact]
        denom = source_times[r] - source_times[l]
        weights = np.divide(times - source_times[l], denom,
                            out=np.zeros(len(times)), where=denom > 0)
        left[covered], right[covered], alpha[covered] = l, r, weights
        nearest[covered] = np.where(weights <= .5, l, r)
        return left, right, alpha, nearest

    def align_tracking(self):
        self.invalidate_alignment()
        try:
            self._align_tracking()
        except (ValueError, RuntimeError, IndexError) as exc:
            self.invalidate_alignment()
            QMessageBox.warning(self, "Tracking alignment", str(exc))

    def _align_tracking(self):
        if self.tracking_df is None or not self.numeric_data:
            raise ValueError("Load a tracking CSV first.")
        v = self.viewer
        if v.mini_t is None or v.camera_t is None:
            raise ValueError("Load both TTL CSV files in the main window first.")
        name = self.x_combo.currentText()
        if name not in self.numeric_data:
            raise ValueError("Choose a tracking coordinate column.")
        x = np.asarray(self.numeric_data[name], dtype=float)
        has_video = v.video.cap is not None and v.video.count > 0
        indices = self.tracking_indices(v.video.count if has_video else None)
        if len(x) != len(indices) or len(indices) < 2:
            raise ValueError("Not enough matching tracking rows and frame indices.")
        n_video = v.video.count if has_video else int(indices[-1]) + 1
        video_times = self.build_video_times(n_video)
        source_times = video_times[indices]
        finite = np.isfinite(x) & np.isfinite(source_times)
        if finite.sum() < 2:
            raise ValueError("Not enough valid tracking positions within camera timestamp coverage and trim.")
        interp_times, interp_x = source_times[finite], x[finite]
        interp_frames = indices[finite]

        mini_end = float(v.mini_t[-1])
        if v.trim_idx is not None:
            mini_end = min(mini_end, float(v.camera_t[v.trim_idx]))
        raw_window = (source_times >= 0.0) & (source_times <= mini_end)
        if self.mode_combo.currentIndex() == 0:
            # Preserve actual camera times, including reconstructed missing TTLs.
            camera_t = v.visible_timeline_times()[1]
            mask = (camera_t >= 0.0) & (camera_t <= mini_end)
            camera_frames = np.asarray([v.video_index(i) for i in range(len(camera_t))])
            mask &= (camera_frames >= 0) & (camera_frames < n_video)
            target_times = camera_t[mask].copy()
            target_frame = camera_frames[mask] + 1
            mode_name = "camera_timestamps"
        else:
            # Keep one row per calcium frame; unavailable positions stay empty.
            target_times = np.asarray(v.mini_t, dtype=float).copy()
            target_frame = v.mini_df.frame.to_numpy(int).copy()
            mode_name = "mini2p_1to1"
        if not len(target_times):
            raise ValueError("No camera frames overlap the Mini2P recording and trim.")

        left, right, alpha, _ = self.interpolation_map(interp_times, target_times)
        target_x = np.full(len(target_times), np.nan)
        usable = left >= 0
        covered = np.flatnonzero(usable)
        period = median_period(v.camera_t)
        max_span = (self.max_missing_frames.value() + 1) * period * 1.05
        spans = interp_times[right[covered]] - interp_times[left[covered]]
        missing = interp_frames[right[covered]] - interp_frames[left[covered]] - 1
        usable[covered] &= (spans <= max_span) & (missing <= self.max_missing_frames.value())
        usable &= target_times <= mini_end
        positions = np.flatnonzero(usable)
        target_x[positions] = ((1 - alpha[positions]) * interp_x[left[positions]]
                               + alpha[positions] * interp_x[right[positions]])
        source_left = np.full(len(target_times), np.nan)
        source_right = source_left.copy()
        source_left[usable] = interp_frames[left[usable]] + 1
        source_right[usable] = interp_frames[right[usable]] + 1
        alpha[~usable] = np.nan

        # Video correspondence is independent of missing tracking coordinates.
        available = np.flatnonzero(np.isfinite(video_times))
        _, _, _, near = self.interpolation_map(video_times[available], target_times)
        near[target_times > mini_end] = -1
        video_indices = np.full(len(target_times), -1, dtype=int)
        has_frame = near >= 0
        video_indices[has_frame] = available[near[has_frame]]
        nearest_frames = np.full(len(target_times), np.nan)
        nearest_times = nearest_frames.copy()
        nearest_frames[has_frame] = video_indices[has_frame] + 1
        nearest_times[has_frame] = video_times[video_indices[has_frame]]

        result = pd.DataFrame({
            "target_frame": target_frame,
            "target_time_ms": target_times,
            "x_aligned": target_x,
            "source_left_frame": source_left,
            "source_right_frame": source_right,
            "interpolation_alpha": alpha,
            "nearest_behavior_frame": nearest_frames,
            "nearest_behavior_time_ms": nearest_times,
            "delta_to_nearest_behavior_ms": target_times - nearest_times,
        })
        if mode_name == "mini2p_1to1":
            result.insert(0, "mini2p_frame", target_frame)
        self.video_times = video_times
        self.result_df = result
        self.target_times = target_times
        self.target_x = target_x
        self.target_video_indices = video_indices
        self.raw_curve.setData(source_times[raw_window] / 1000., x[raw_window], connect="finite")
        self.aligned_curve.setData(target_times / 1000., target_x, connect="finite")
        self.time_plot.enableAutoRange()
        self.frame_curve.setData(target_frame, target_x, connect="finite")
        self.frame_plot.setLabel("bottom", "Mini2P frame" if mode_name == "mini2p_1to1" else "camera frame")
        self.frame_plot.enableAutoRange()
        self.status.setText(
            f"Aligned to {'Mini2P frames' if mode_name == 'mini2p_1to1' else 'camera timestamps'} · "
            f"{len(target_times)} rows · {int(usable.sum())} positions available · "
            f"{int((~usable).sum())} empty positions · {int((~has_frame).sum())} times without video coverage. "
            "Unavailable positions export as empty cells; unavailable video frames export as blank images."
        )

    def export_csv(self):
        if self.result_df is None:
            self.align_tracking()
        if self.result_df is None:
            return
        suggested = "tracking_aligned_camera.csv" if self.mode_combo.currentIndex() == 0 else "tracking_aligned_mini2p.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export aligned tracking", suggested, "CSV files (*.csv)")
        if not path:
            return
        if not str(path).lower().endswith(".csv"):
            path += ".csv"
        self.result_df.to_csv(path, index=False)
        QMessageBox.information(self, "Tracking alignment", f"Saved aligned tracking:\n{path}")

    def export_video(self):
        if self.result_df is None or self.target_video_indices is None:
            self.align_tracking()
        if self.result_df is None or self.target_video_indices is None:
            return
        result_df = self.result_df.copy()
        target_times = self.target_times.copy()
        target_video_indices = self.target_video_indices.copy()
        v = self.viewer
        if v.video.cap is None or v.video_path is None:
            QMessageBox.warning(self, "Aligned video", "Load the behavior MP4 in the main window first.")
            return

        suggested = "behavior_aligned_camera.mp4" if self.mode_combo.currentIndex() == 0 else "behavior_aligned_mini2p.mp4"
        path, _ = QFileDialog.getSaveFileName(self, "Export aligned behavior video", suggested, "MP4 video (*.mp4)")
        if not path:
            return
        if not str(path).lower().endswith(".mp4"):
            path += ".mp4"

        cap = cv2.VideoCapture(str(v.video_path))
        if not cap.isOpened():
            QMessageBox.critical(self, "Aligned video", "Could not open source behavior video.")
            return
        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        crop = v.normalized_spatial_crop()
        if crop is not None:
            cx, cy, cw, ch = crop
            out_w, out_h = cw, ch
        else:
            out_w, out_h = src_w, src_h

        if len(target_times) >= 2:
            dt = np.median(np.diff(target_times))
            fps = 1000.0 / dt if dt > 0 else float(v.video.fps)
        else:
            fps = float(v.video.fps)
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), float(fps), (int(out_w), int(out_h)))
        if not writer.isOpened():
            cap.release()
            QMessageBox.critical(self, "Aligned video", "Could not create output MP4.")
            return

        progress = QProgressDialog("Exporting aligned behavior video…", "Cancel", 0, len(target_video_indices), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        cache = {}
        cancelled = False
        try:
            for out_i, src_i in enumerate(target_video_indices):
                src_i = int(src_i)
                if src_i < 0:
                    frame = np.zeros((int(out_h), int(out_w), 3), dtype=np.uint8)
                    cv2.putText(frame, "No behavior frame", (20, max(30, int(out_h) // 2)),
                                cv2.FONT_HERSHEY_SIMPLEX, .7, (220, 220, 220), 1)
                    writer.write(frame)
                    progress.setValue(out_i + 1)
                    QApplication.processEvents()
                    if progress.wasCanceled():
                        cancelled = True
                        break
                    continue
                frame = cache.get(src_i)
                if frame is None:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, src_i)
                    ok, frame = cap.read()
                    if not ok:
                        raise RuntimeError(f"Could not read source frame {src_i + 1}.")
                    cache[src_i] = frame.copy()
                    if len(cache) > 24:
                        cache.pop(next(iter(cache)))
                else:
                    frame = frame.copy()
                if crop is not None:
                    cx, cy, cw, ch = crop
                    frame = frame[cy:cy + ch, cx:cx + cw]
                writer.write(frame)
                if out_i % 10 == 0 or out_i == len(target_video_indices) - 1:
                    progress.setValue(out_i + 1)
                    QApplication.processEvents()
                if progress.wasCanceled():
                    cancelled = True
                    break
        except Exception as exc:
            QMessageBox.critical(self, "Aligned video", f"{type(exc).__name__}: {exc}")
            cancelled = True
        finally:
            cap.release()
            writer.release()
            progress.close()
        if cancelled:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass
            return

        # Sidecar mapping for provenance.
        mapping_path = str(Path(path).with_suffix(".mapping.csv"))
        result_df.to_csv(mapping_path, index=False)
        QMessageBox.information(
            self,
            "Aligned video",
            "Aligned video exported.\n\n"
            "Tracking positions use linear interpolation within the allowed gaps. "
            "Covered times use the nearest real behavior frame. Times without video coverage "
            "use blank images to preserve frame correspondence.\n\n"
            f"Video: {path}\nMapping: {mapping_path}"
        )


class Viewer(QMainWindow):
    alignment_changed = Signal()
    theme_changed = Signal(bool)
    calcium_source_changed = Signal()
    time_changed = Signal(float)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("CALI")
        self.resize(1440, 860)
        self.setMinimumSize(1180, 760)
        self.day_mode = True
        self.caiman = None
        self.processing_manifest = None
        self.processing_results = []
        self.calcium_movie_mode = False
        self.calcium_sample_index = 0
        self.calcium_playback_rate = 20.0
        self.playback_timer = QTimer(self)
        self.playback_timer.timeout.connect(self.advance_calcium_movie)
        self.calcium_trace = self.calcium_footprint = self.calcium_reference = None
        self.camera_df = self.mini_df = None
        self.camera_source_columns = None
        self.camera_source_row_count = None
        self.camera_csv_path = None
        self.mini_csv_path = None
        self.video_path = None
        self.trim_idx = None
        self.spatial_crop_rect = None
        self.camera_t = self.mini_t = None
        self.camera_dt = self.mini_dt = None
        self.camera_gap = self.mini_gap = None
        self.camera_virtual = None
        self.t0 = None
        self.current_t = 0.0
        self.video = VideoReader()
        self.tiff = TiffReader()
        self.tiff_first_frame = 1
        self.hover_pos = None
        self.hover_timer = QTimer(self)
        self.hover_timer.setSingleShot(True)
        self.hover_timer.setInterval(500)
        self.hover_timer.timeout.connect(self.show_hover)
        self.build_ui()

    def build_ui(self):
        self.setStyleSheet(self.app_stylesheet())

        logo_path = Path(__file__).with_name("mini2p_logo_mark.png")
        if logo_path.exists():
            self.setWindowIcon(QIcon(str(logo_path)))

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)

        outer = QHBoxLayout(root)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(14)

        # ----------------------------------------------------------
        # Sidebar
        # ----------------------------------------------------------
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(336)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 16, 16, 16)
        side.setSpacing(12)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(12)

        logo = QLabel()
        logo.setObjectName("brandLogo")
        logo.setFixedSize(78, 52)
        logo.setAlignment(Qt.AlignCenter)
        if logo_path.exists():
            pm = QPixmap(str(logo_path))
            logo.setPixmap(pm.scaled(76, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        title = QLabel("CALI")
        title.setObjectName("appTitle")
        brand_row.addWidget(logo)
        brand_row.addWidget(title)
        brand_row.addStretch()
        side.addLayout(brand_row)

        # Files -----------------------------------------------------
        src_card = self.card("sideCard")
        src_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        src_lay = QVBoxLayout(src_card)
        src_lay.setContentsMargins(13, 12, 13, 12)
        src_lay.setSpacing(9)

        src_title = QLabel("Files")
        src_title.setObjectName("sectionTitle")
        src_lay.addWidget(src_title)

        src_grid = QGridLayout()
        src_grid.setHorizontalSpacing(7)
        src_grid.setVerticalSpacing(7)
        buttons = [
            ("Camera CSV", self.load_camera),
            ("Mini2P CSV", self.load_mini),
            ("Behavior MP4", self.load_video),
            ("ScanImage TIFF", self.load_tiff),
            ("CaImAn HDF5", self.load_caiman),
        ]
        self.source_buttons = {}
        for idx, (label, fn) in enumerate(buttons):
            btn = QPushButton(label)
            btn.setProperty("variant", "source")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(fn)
            src_grid.addWidget(btn, idx // 2, idx % 2, 1, 2 if idx == 4 else 1)
            self.source_buttons[label] = btn
        src_lay.addLayout(src_grid)
        side.addWidget(src_card)

        # Navigate --------------------------------------------------
        controls_card = self.card("sideCard")
        controls_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        controls_lay = QVBoxLayout(controls_card)
        controls_lay.setContentsMargins(13, 12, 13, 12)
        controls_lay.setSpacing(10)

        controls_title = QLabel("Navigate")
        controls_title.setObjectName("sectionTitle")
        controls_lay.addWidget(controls_title)

        for label_text, back_fn, forward_fn in (
            ("Frame", lambda: self.step_mini(-1), lambda: self.step_mini(1)),
            ("Gap", lambda: self.jump_gap(-1), lambda: self.jump_gap(1)),
        ):
            row = QHBoxLayout()
            row.setSpacing(6)
            row_label = QLabel(label_text)
            row_label.setObjectName("navRowLabel")
            row.addWidget(row_label)
            row.addStretch()
            back = QPushButton("‹")
            forward = QPushButton("›")
            for button, fn in ((back, back_fn), (forward, forward_fn)):
                button.setProperty("variant", "navStep")
                button.setFixedSize(38, 34)
                button.setCursor(Qt.PointingHandCursor)
                button.clicked.connect(fn)
                row.addWidget(button)
            controls_lay.addLayout(row)

        nav_sep = QFrame()
        nav_sep.setObjectName("sideSeparator")
        nav_sep.setFixedHeight(1)
        controls_lay.addWidget(nav_sep)

        mapping_header = QLabel("Video mapping")
        mapping_header.setObjectName("navSubhead")
        controls_lay.addWidget(mapping_header)

        self.mode = QComboBox()
        self.mode.setObjectName("videoMapping")
        self.mode.addItems(["Timing reconstruction", "TTL index"])
        self.mode.currentIndexChanged.connect(self.mapping_changed)
        controls_lay.addWidget(self.mode)

        offset_row = QHBoxLayout()
        offset_row.setSpacing(10)
        offset_label = QLabel("MP4 offset")
        offset_label.setObjectName("navRowLabel")
        self.offset = QSpinBox()
        self.offset.setObjectName("mp4Offset")
        self.offset.setRange(-1000000, 1000000)
        self.offset.setValue(0)
        self.offset.valueChanged.connect(self.mapping_changed)
        self.offset.setFixedWidth(92)
        offset_row.addWidget(offset_label)
        offset_row.addStretch()
        offset_row.addWidget(self.offset)
        controls_lay.addLayout(offset_row)
        side.addWidget(controls_card)

        side.addStretch(1)

        outer.addWidget(sidebar)

        # ----------------------------------------------------------
        # Main workspace
        # ----------------------------------------------------------
        main = QVBoxLayout()
        main.setSpacing(13)

        top_bar = QHBoxLayout()
        top_bar.addStretch()
        self.theme_btn = QPushButton()
        self.theme_btn.setObjectName("themeToggle")
        self.theme_btn.setFixedSize(36, 36)
        self.theme_btn.setIconSize(QSize(22, 22))
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.clicked.connect(lambda: self.set_day_mode(not self.day_mode))
        top_bar.addWidget(self.theme_btn)
        main.addLayout(top_bar)

        split = QSplitter(Qt.Horizontal)
        split.setObjectName("viewerSplitter")
        self.cam_panel = ImagePanel("Behavior camera", "#17B9DC", croppable=True)
        self.cam_panel.cropChanged.connect(self.set_spatial_crop)
        self.cam_panel.exportCropRequested.connect(self.export_spatial_crop)
        self.mini_panel = ImagePanel("Mini2P", "#12C4BE")
        split.addWidget(self.cam_panel)
        split.addWidget(self.mini_panel)
        split.setSizes([720, 720])
        main.addWidget(split, 1)

        timeline_card = self.card("timelineCard")
        timeline_lay = QVBoxLayout(timeline_card)
        timeline_lay.setContentsMargins(15, 13, 15, 12)
        timeline_lay.setSpacing(8)

        tl_top = QHBoxLayout()
        tl_title = QLabel("Timeline")
        tl_title.setObjectName("mainSectionTitle")
        tl_top.addWidget(tl_title)
        self.align_tracking_btn = QPushButton("Align tracking")
        self.align_tracking_btn.setProperty("variant", "mainGhost")
        self.align_tracking_btn.setCursor(Qt.PointingHandCursor)
        self.align_tracking_btn.clicked.connect(self.open_tracking_alignment)
        tl_top.addWidget(self.align_tracking_btn)
        self.movement_btn = QPushButton("Movement analysis")
        self.movement_btn.setProperty("variant", "mainGhost")
        self.movement_btn.setCursor(Qt.PointingHandCursor)
        self.movement_btn.clicked.connect(self.open_movement_analysis)
        tl_top.addWidget(self.movement_btn)
        self.processing_button = QPushButton("Calcium analysis")
        self.processing_button.setProperty("variant", "mainGhost")
        self.processing_button.setCursor(Qt.PointingHandCursor)
        self.processing_button.clicked.connect(self.open_calcium_processing)
        tl_top.addWidget(self.processing_button)
        tl_top.addStretch()
        for txt, obj in [("Camera", "legendCyan"), ("Mini2P", "legendTeal"), ("Gap", "legendRed")]:
            lbl = QLabel(txt)
            lbl.setObjectName(obj)
            tl_top.addWidget(lbl)
        timeline_lay.addLayout(tl_top)

        self.plot = pg.PlotWidget()
        self.plot.setObjectName("timelinePlot")
        self.plot.setMinimumHeight(208)
        self.plot.setBackground("#0C1927")
        self.plot.setLabel("bottom", "Common Arduino time", units="ms")
        self.plot.getAxis("bottom").enableAutoSIPrefix(False)
        self.plot.setYRange(-0.6, 1.6)
        self.plot.setMouseEnabled(x=True, y=False)
        self.plot.showGrid(x=True, y=False, alpha=.10)
        self.plot.getAxis("left").setTicks([[(0, "Mini2P"), (1, "Camera")]])
        for axis_name in ("bottom", "left"):
            axis = self.plot.getAxis(axis_name)
            axis.setPen(pg.mkPen("#315067"))
            axis.setTextPen(pg.mkPen("#C8D7E3"))

        self.cam_pts = pg.ScatterPlotItem(
            size=5,
            pen=None,
            brush=pg.mkBrush(23, 185, 220, 225),
        )
        self.mini_pts = pg.ScatterPlotItem(
            size=6,
            pen=None,
            brush=pg.mkBrush(18, 196, 190, 235),
        )
        self.gap_pts = pg.ScatterPlotItem(
            size=10,
            symbol="x",
            pen=pg.mkPen(255, 107, 107, width=1.8),
        )
        self.plot.addItem(self.cam_pts)
        self.plot.addItem(self.mini_pts)
        self.plot.addItem(self.gap_pts)

        self.cursor_line = pg.InfiniteLine(
            angle=90,
            movable=True,
            pen=pg.mkPen(240, 247, 252, width=1.4),
        )
        self.plot.addItem(self.cursor_line)
        self.cursor_line.sigPositionChanged.connect(
            lambda: self.set_time(float(self.cursor_line.value()))
        )

        self.trim_line = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen(20, 121, 232, width=2),
        )
        self.trim_line.hide()
        self.plot.addItem(self.trim_line)
        self.trim_region = pg.LinearRegionItem(
            values=[0, 0],
            movable=False,
            brush=pg.mkBrush(20, 121, 232, 26),
            pen=pg.mkPen(None),
        )
        self.trim_region.setZValue(-10)
        self.trim_region.hide()
        self.plot.addItem(self.trim_region)
        self.plot.scene().sigMouseClicked.connect(self.plot_clicked)
        self.plot.scene().sigMouseMoved.connect(self.mouse_moved)
        self.timeline_tabs = QTabWidget()
        self.timeline_tabs.addTab(self.plot, "Timing")
        self.build_calcium_tab()
        self.timeline_tabs.currentChanged.connect(self.calcium_tab_changed)
        timeline_lay.addWidget(self.timeline_tabs)

        # Trim toolbar ----------------------------------------------
        trim_sep = QFrame()
        trim_sep.setObjectName("trimSeparator")
        trim_sep.setFixedHeight(1)
        timeline_lay.addWidget(trim_sep)

        trim_row = QHBoxLayout()
        trim_row.setSpacing(7)

        trim_title = QLabel("TRIM")
        trim_title.setObjectName("trimTitle")
        trim_row.addWidget(trim_title)

        self.trim_preview = QLabel("Not set")
        self.trim_preview.setObjectName("trimStatusPill")
        self.trim_preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        trim_row.addWidget(self.trim_preview)
        trim_row.addStretch()

        self.auto_trim_btn = QPushButton("Auto")
        self.auto_trim_btn.setProperty("variant", "teal")
        self.auto_trim_btn.clicked.connect(self.auto_trim)
        self.set_trim_btn = QPushButton("Cursor")
        self.set_trim_btn.setProperty("variant", "mainGhost")
        self.set_trim_btn.clicked.connect(self.set_trim_current)
        self.clear_trim_btn = QPushButton("Reset")
        self.clear_trim_btn.setProperty("variant", "mainGhost")
        self.clear_trim_btn.clicked.connect(self.clear_trim)
        self.export_trim_btn = QPushButton("Export")
        self.export_trim_btn.setProperty("variant", "blue")
        self.export_trim_btn.clicked.connect(self.export_trim)

        for b in (
            self.auto_trim_btn,
            self.set_trim_btn,
            self.clear_trim_btn,
            self.export_trim_btn,
        ):
            b.setCursor(Qt.PointingHandCursor)
            trim_row.addWidget(b)
        timeline_lay.addLayout(trim_row)

        main.addWidget(timeline_card)
        outer.addLayout(main, 1)
        self.set_day_mode(self.day_mode)

    def build_calcium_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(6)
        row = QHBoxLayout()
        self.calcium_channel = QComboBox()
        self.calcium_channel.setToolTip("Processed channel")
        self.calcium_channel.hide()
        self.calcium_channel.currentIndexChanged.connect(self.select_processing_channel)
        row.addWidget(self.calcium_channel)
        self.calcium_filter = QComboBox()
        for text, value in (("All components", "all"), ("Accepted", "accepted"), ("Rejected", "rejected")):
            self.calcium_filter.addItem(text, value)
        self.calcium_filter.setToolTip("Quality classifications saved by CaImAn")
        self.calcium_filter.currentIndexChanged.connect(self.populate_calcium_components)
        self.calcium_component = QComboBox()
        self.calcium_component.setMinimumWidth(155)
        self.calcium_component.setToolTip("Original CaImAn component ID (zero-based)")
        self.calcium_component.currentIndexChanged.connect(self.select_calcium_component)
        self.calcium_signal = QComboBox()
        self.calcium_signal.currentIndexChanged.connect(self.select_calcium_component)
        self.calcium_roi = QCheckBox("Show ROI")
        self.calcium_roi.setChecked(True)
        self.calcium_roi.setToolTip("Contour at 20% of the selected footprint's maximum; image dimensions must match.")
        self.calcium_roi.toggled.connect(self.update_calcium_roi)
        for widget in (self.calcium_filter, self.calcium_component, self.calcium_signal, self.calcium_roi):
            row.addWidget(widget)
        row.addStretch()
        layout.addLayout(row)
        mapping = QHBoxLayout()
        mapping.addWidget(QLabel("First Mini2P frame"))
        self.calcium_first_frame = QSpinBox()
        self.calcium_first_frame.setRange(1, 1000000000)
        self.calcium_first_frame.setFixedWidth(110)
        self.calcium_first_frame.setToolTip("Mini2P frame number corresponding to CaImAn sample 0. For an untrimmed movie, use 1.")
        self.calcium_first_frame.valueChanged.connect(self.calcium_mapping_changed)
        mapping.addWidget(self.calcium_first_frame)
        mapping.addStretch()
        self.calcium_export = QPushButton("Export trace")
        self.calcium_export.setProperty("variant", "mainGhost")
        self.calcium_export.clicked.connect(self.export_calcium_trace)
        mapping.addWidget(self.calcium_export)
        layout.addLayout(mapping)
        self.calcium_movie_controls = QWidget()
        movie = QHBoxLayout(self.calcium_movie_controls)
        movie.setContentsMargins(0, 0, 0, 0)
        self.calcium_play = QPushButton("Play")
        self.calcium_play.setCheckable(True)
        self.calcium_play.setProperty("variant", "mainGhost")
        self.calcium_play.toggled.connect(self.toggle_calcium_playback)
        movie.addWidget(self.calcium_play)
        movie.addWidget(QLabel("Movie frame"))
        self.calcium_frame = QSpinBox()
        self.calcium_frame.setRange(1, 1)
        self.calcium_frame.valueChanged.connect(lambda frame: self.set_calcium_sample(frame - 1))
        movie.addWidget(self.calcium_frame)
        self.calcium_slider = QSlider(Qt.Horizontal)
        self.calcium_slider.setRange(0, 0)
        self.calcium_slider.valueChanged.connect(self.set_calcium_sample)
        movie.addWidget(self.calcium_slider, 1)
        layout.addWidget(self.calcium_movie_controls)
        self.calcium_status = QLabel("Load a CaImAn CNMF HDF5 file and Mini2P TTL CSV to inspect synchronized traces.")
        self.calcium_status.setObjectName("calciumStatus")
        self.calcium_status.setWordWrap(True)
        layout.addWidget(self.calcium_status)
        self.calcium_plot = pg.PlotWidget()
        self.calcium_plot.setMinimumHeight(150)
        self.calcium_plot.setLabel("bottom", "Common Arduino time", units="ms")
        self.calcium_plot.getAxis("bottom").enableAutoSIPrefix(False)
        self.calcium_plot.getAxis("left").enableAutoSIPrefix(False)
        self.calcium_plot.showGrid(x=True, y=False, alpha=.1)
        self.plot.sigXRangeChanged.connect(lambda _, bounds: self.sync_calcium_range(self.calcium_plot, bounds))
        self.calcium_plot.sigXRangeChanged.connect(lambda _, bounds: self.sync_calcium_range(self.plot, bounds))
        self.calcium_curve = self.calcium_plot.plot([], [], pen=pg.mkPen("#087D78", width=1.5), connect="finite")
        self.calcium_curve.setClipToView(True)
        self.calcium_curve.setDownsampling(auto=True, method="peak")
        self.calcium_cursor = pg.InfiniteLine(angle=90, movable=True)
        self.calcium_plot.addItem(self.calcium_cursor)
        self.calcium_cursor.sigPositionChanged.connect(self.calcium_cursor_moved)
        self.calcium_plot.scene().sigMouseClicked.connect(self.calcium_clicked)
        layout.addWidget(self.calcium_plot, 1)
        self.timeline_tabs.addTab(tab, "Calcium")
        self.set_calcium_controls_enabled(False)

    def calcium_tab_changed(self, index):
        # Leave room for trace controls and axes at the minimum window size.
        for panel in (self.cam_panel, self.mini_panel):
            panel.image.setMinimumHeight(160 if index == 1 else 240)
        if index != 1:
            self.calcium_play.setChecked(False)
        self.update_views()

    def sync_calcium_range(self, target, bounds):
        if self.calcium_movie_mode:
            return
        if not np.allclose(target.viewRange()[0], bounds, rtol=1e-10, atol=1e-10):
            target.setXRange(*bounds, padding=0)

    def set_calcium_controls_enabled(self, enabled):
        for widget in (self.calcium_filter, self.calcium_component, self.calcium_signal,
                       self.calcium_roi, self.calcium_first_frame, self.calcium_play,
                       self.calcium_frame, self.calcium_slider):
            widget.setEnabled(enabled)
        self.calcium_export.setEnabled(False)

    def load_caiman(self):
        path = self.choose("Calcium results", "Calcium results (*.hdf5 *.h5 *.json)")
        if path:
            try:
                selected = Path(path)
                manifest = selected if selected.suffix.lower() == ".json" else selected.parent / "processing.json"
                if manifest.exists():
                    data = json.loads(manifest.read_text())
                    if "completed_results" in data:
                        if data.get("status") != "complete":
                            raise ValueError("This analysis did not finish successfully.")
                        results = [json.loads((Path(file).parent / "processing.json").read_text())
                                   for file in data["completed_results"]]
                    else:
                        if selected.suffix.lower() != ".json" and Path(data["outputs"]["results"]).resolve() != selected.resolve():
                            self.set_caiman_results(path)
                            return
                        results = [data]
                    self.show_processing_results(results)
                else:
                    self.set_caiman_results(path)
            except Exception as exc:
                self.err(exc)

    def open_calcium_processing(self):
        from processing_dialog import CalciumProcessingDialog
        dialog = getattr(self, "_calcium_processing_dialog", None)
        if dialog is None:
            dialog = CalciumProcessingDialog(self)
            self._calcium_processing_dialog = dialog
        else:
            dialog.sync_source_from_viewer()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def open_processing_result(self, manifest):
        """Load the exact corrected movie used for CNMF, with its sample origin."""
        if manifest.get("status") != "complete":
            raise ValueError("Only completed processing runs can be loaded.")
        first = int(manifest["settings"]["first_mini_frame"])
        # Validate both outputs before replacing the current TIFF.
        CaImAnResults(manifest["outputs"]["results"])
        reader = TiffReader()
        reader.open(manifest["outputs"]["corrected_tiff"])
        self.tiff.close()
        self.tiff = reader
        self.tiff_first_frame = first
        self.set_caiman_results(manifest["outputs"]["results"], processing_manifest=manifest)
        self.calcium_first_frame.setValue(first)
        self.mark_loaded("ScanImage TIFF", True)
        self.source_buttons["ScanImage TIFF"].setToolTip(manifest["outputs"]["corrected_tiff"])
        self.calcium_plot.setXRange(1, self.caiman.n_frames, padding=.01)
        self.set_calcium_sample(0)
        for index, result in enumerate(self.processing_results):
            if result["outputs"]["results"] == manifest["outputs"]["results"]:
                self.calcium_channel.blockSignals(True)
                self.calcium_channel.setCurrentIndex(index)
                self.calcium_channel.blockSignals(False)
                break

    def show_processing_results(self, results):
        if not results:
            raise ValueError("No completed calcium results are available.")
        self.processing_results = list(results)
        self.calcium_channel.blockSignals(True)
        self.calcium_channel.clear()
        for number, manifest in enumerate(results):
            index = manifest["settings"].get("channel_index", number)
            ids = manifest.get("sources", [{}])[0].get("channel_ids")
            self.calcium_channel.addItem(f"Channel {ids[index] if ids else index + 1}", number)
        self.calcium_channel.setCurrentIndex(0)
        self.calcium_channel.blockSignals(False)
        self.calcium_channel.setVisible(len(results) > 1)
        self.open_processing_result(results[0])
        self.timeline_tabs.setCurrentIndex(1)
        self.raise_()
        self.activateWindow()

    def select_processing_channel(self, index):
        if 0 <= index < len(self.processing_results):
            self.open_processing_result(self.processing_results[index])

    def set_caiman_results(self, path, *, processing_manifest=None):
        results = CaImAnResults(path)
        reference = results.reference_image()
        self.calcium_play.setChecked(False)
        self.processing_manifest = processing_manifest
        if processing_manifest is None:
            self.processing_results = []
            self.calcium_channel.hide()
        rate = (processing_manifest or {}).get("settings", {}).get("frame_rate", 20)
        self.calcium_playback_rate = min(60.0, max(1.0, float(rate)))
        self.calcium_sample_index = 0
        self.caiman = results
        self.calcium_reference = reference
        self.calcium_first_frame.blockSignals(True)
        self.calcium_first_frame.setValue(1)
        self.calcium_first_frame.blockSignals(False)
        self.set_calcium_controls_enabled(True)
        for control, low, high in ((self.calcium_frame, 1, results.n_frames),
                                   (self.calcium_slider, 0, results.n_frames - 1)):
            control.blockSignals(True)
            control.setRange(low, high)
            control.blockSignals(False)
        self.sync_calcium_movie_controls()
        self.calcium_signal.blockSignals(True)
        self.calcium_signal.clear()
        for kind in results.trace_types:
            self.calcium_signal.addItem(results.TRACE_LABELS[kind], kind)
        if "F_dff" in results.trace_types:
            self.calcium_signal.setCurrentIndex(self.calcium_signal.findData("F_dff"))
        self.calcium_signal.blockSignals(False)
        self.calcium_filter.blockSignals(True)
        self.calcium_filter.setCurrentIndex(1 if results.accepted is not None and len(results.accepted) else 0)
        self.calcium_filter.blockSignals(False)
        self.populate_calcium_components()
        self.mark_loaded("CaImAn HDF5", True)
        self.source_buttons["CaImAn HDF5"].setToolTip(str(results.path))
        self.timeline_tabs.setCurrentIndex(1)
        self.calcium_source_changed.emit()

    def calcium_sample_times(self):
        """Measured TTL times only; missing movie samples never invent a clock."""
        if self.caiman is None:
            return np.array([])
        times = np.full(self.caiman.n_frames, np.nan)
        if self.mini_t is not None and self.mini_df is not None:
            samples = self.mini_df.frame.to_numpy(int) - self.calcium_first_frame.value()
            valid = (samples >= 0) & (samples < len(times)) & np.isfinite(self.mini_t)
            times[samples[valid]] = self.mini_t[valid]
        return times

    def calcium_mapping_changed(self):
        self.refresh_calcium_trace()
        if self.calcium_movie_mode and self.caiman is not None:
            self.set_calcium_sample(self.calcium_sample_index or 0)
        else:
            self.update_views()

    def sync_calcium_movie_controls(self):
        if self.caiman is None or self.calcium_sample_index is None:
            return
        index = self.calcium_sample_index
        for widget, value in ((self.calcium_slider, index), (self.calcium_frame, index + 1)):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)

    def set_calcium_sample(self, index):
        if self.caiman is None:
            return
        index = int(np.clip(index, 0, self.caiman.n_frames - 1))
        self.calcium_sample_index = index
        times = self.calcium_sample_times()
        if np.isfinite(times[index]):
            self.set_time(float(times[index]))
        else:
            self.sync_calcium_movie_controls()
            self.calcium_cursor.blockSignals(True)
            self.calcium_cursor.setValue(index + 1)
            self.calcium_cursor.blockSignals(False)
            self.update_views()

    def toggle_calcium_playback(self, playing):
        self.calcium_play.setText("Pause" if playing else "Play")
        if playing and self.caiman is not None:
            self.playback_timer.start(max(1, round(1000 / self.calcium_playback_rate)))
        else:
            self.playback_timer.stop()

    def advance_calcium_movie(self):
        if self.caiman is None:
            self.calcium_play.setChecked(False)
            return
        index = (self.calcium_sample_index or 0) + 1
        if index >= self.caiman.n_frames:
            self.calcium_play.setChecked(False)
            return
        self.set_calcium_sample(index)

    def calcium_cursor_moved(self):
        value = float(self.calcium_cursor.value())
        if self.calcium_movie_mode:
            self.set_calcium_sample(round(value) - 1)
        else:
            self.set_time(value)

    def populate_calcium_components(self):
        if self.caiman is None:
            return
        previous = self.calcium_component.currentData()
        self.calcium_component.blockSignals(True)
        self.calcium_component.clear()
        for component in self.caiman.component_ids(self.calcium_filter.currentData()):
            component = int(component)
            self.calcium_component.addItem(f"ROI {component} · {self.caiman.quality(component)}", component)
        selected = self.calcium_component.findData(previous)
        self.calcium_component.setCurrentIndex(max(0, selected) if self.calcium_component.count() else -1)
        self.calcium_component.blockSignals(False)
        self.select_calcium_component()

    def select_calcium_component(self):
        self.calcium_trace = self.calcium_footprint = None
        component = self.calcium_component.currentData()
        if self.caiman is not None and component is not None:
            try:
                self.calcium_trace = self.caiman.trace(component, self.calcium_signal.currentData())
                self.calcium_footprint = self.caiman.footprint(component)
            except Exception as exc:
                self.calcium_trace = self.calcium_footprint = None
                self.update_calcium_roi()
                self.refresh_calcium_trace()
                self.err(exc)
                return
        self.update_calcium_roi()
        self.refresh_calcium_trace()

    def update_calcium_roi(self):
        footprint = self.calcium_footprint if self.calcium_roi.isChecked() else None
        self.mini_panel.set_roi(footprint)
        self.update_views()

    def calcium_trace_table(self):
        if self.caiman is None or self.calcium_trace is None:
            return None
        if self.processing_manifest is not None or self.mini_t is None:
            samples = np.arange(self.caiman.n_frames)
            frames = samples + self.calcium_first_frame.value()
            times = self.calcium_sample_times()
            visible = np.ones(len(samples), dtype=bool)
            if self.trim_idx is not None and self.camera_t is not None and self.mini_t is not None:
                kept_frames = self.mini_df.frame.to_numpy()[self.mini_t <= self.camera_t[self.trim_idx]]
                visible &= frames <= kept_frames[-1] if len(kept_frames) else False
            return pd.DataFrame({
                "mini2p_frame": frames[visible],
                "time_ms": times[visible],
                "caiman_sample_zero_based": samples[visible],
                "roi_id_zero_based": self.calcium_component.currentData(),
                "signal": self.calcium_signal.currentData(), "value": self.calcium_trace[visible],
            })
        frames = self.mini_df.frame.to_numpy()
        values, covered = self.caiman.mapped_trace(self.calcium_trace, frames, self.calcium_first_frame.value())
        visible = np.ones(len(frames), dtype=bool)
        if self.trim_idx is not None and self.camera_t is not None:
            visible &= self.mini_t <= self.camera_t[self.trim_idx]
        return pd.DataFrame({
            "mini2p_frame": frames[visible],
            "time_ms": self.mini_t[visible],
            "caiman_sample_zero_based": np.where(covered, frames - self.calcium_first_frame.value(), np.nan)[visible],
            "roi_id_zero_based": self.calcium_component.currentData(),
            "signal": self.calcium_signal.currentData(),
            "value": values[visible],
        })

    def refresh_calcium_trace(self):
        self.calcium_export.setEnabled(False)
        self.calcium_curve.setData([], [])
        if self.caiman is None:
            return
        previous_mode = self.calcium_movie_mode
        self.calcium_movie_mode = self.processing_manifest is not None or self.mini_t is None
        self.calcium_movie_controls.setVisible(self.calcium_movie_mode)
        prefix = f"{self.caiman.n_components} components · {self.caiman.n_frames} CaImAn frames. "
        if self.caiman.accepted is not None and not len(self.caiman.accepted):
            prefix += "No components passed quality criteria; inspect candidates using All components. "
        if self.calcium_trace is None:
            self.calcium_status.setText(prefix + "No components in this selection.")
            return
        try:
            table = self.calcium_trace_table()
        except ValueError as exc:
            self.calcium_status.setText(str(exc))
            return
        covered = table.caiman_sample_zero_based.notna()
        if self.calcium_movie_mode:
            frames = np.arange(1, self.caiman.n_frames + 1)
            self.calcium_curve.setData(frames, self.calcium_trace, connect="finite")
            self.calcium_plot.setLabel("bottom", "Movie frame", units=None)
            if not previous_mode:
                self.calcium_plot.setXRange(frames[0], frames[-1], padding=.01)
            observed = int(np.isfinite(self.calcium_sample_times()).sum())
            notes = f"Full movie · measured TTL coverage {observed}/{self.caiman.n_frames} frames."
            if observed < self.caiman.n_frames:
                notes += " Frames without TTL coverage have no synchronized behavior time."
            self.calcium_export.setToolTip("Exports movie samples with empty time_ms outside measured TTL coverage. The current trim limits exported samples.")
        else:
            self.calcium_curve.setData(table.time_ms.to_numpy(), table.value.to_numpy(), connect="finite")
            self.calcium_plot.setLabel("bottom", "Common Arduino time", units="ms")
            if previous_mode:
                self.calcium_plot.setXRange(*self.plot.viewRange()[0], padding=0)
            notes = f"Mapped {int(covered.sum())}/{len(table)} TTL frames by frame ID."
            if self.caiman.n_frames != len(self.mini_df) or not covered.all():
                notes += " Frame counts differ: check the source movie and first Mini2P frame. Uncovered samples stay empty."
        kind = self.calcium_signal.currentData()
        self.calcium_plot.setLabel("left", "ΔF/F" if kind == "F_dff" else self.caiman.TRACE_LABELS[kind])
        self.calcium_plot.enableAutoRange(axis="y")
        if not self.caiman.spatial:
            notes += " No 2D spatial footprints available."
        elif self.tiff.tif is not None and self.mini_panel.pm is not None:
            shape = (self.mini_panel.pm.height(), self.mini_panel.pm.width())
            if shape != self.caiman.dims:
                notes += " ROI hidden: TIFF and CaImAn image dimensions differ."
        self.calcium_status.setText(prefix + notes)
        self.calcium_export.setEnabled(bool(covered.any()))

    def export_calcium_trace(self):
        try:
            table = self.calcium_trace_table()
            if table is None or not self.calcium_export.isEnabled():
                return
            path, _ = QFileDialog.getSaveFileName(self, "Export synchronized CaImAn trace", "caiman_trace.csv", "CSV (*.csv)")
            if path:
                table.to_csv(path, index=False)
        except Exception as exc:
            self.err(exc)

    def calcium_clicked(self, event):
        if event.button() == Qt.LeftButton:
            view = self.calcium_plot.getViewBox()
            if view.sceneBoundingRect().contains(event.scenePos()):
                value = float(view.mapSceneToView(event.scenePos()).x())
                if self.calcium_movie_mode:
                    self.set_calcium_sample(round(value) - 1)
                else:
                    self.set_time(value)

    def set_day_mode(self, enabled):
        self.day_mode = enabled
        action = "Switch to night mode" if enabled else "Switch to day mode"
        self.theme_btn.setToolTip(action)
        self.theme_btn.setAccessibleName(action)
        self.theme_btn.setIcon(self.theme_icon())
        self.setStyleSheet(self.app_stylesheet())
        self.plot.setBackground("#F8F5EE" if enabled else "#0C1927")
        for axis_name in ("bottom", "left"):
            axis = self.plot.getAxis(axis_name)
            axis.setPen(pg.mkPen("#C5BEB1" if enabled else "#315067"))
            axis.setTextPen(pg.mkPen("#625E55" if enabled else "#C8D7E3"))
        self.cursor_line.setPen(pg.mkPen("#49473F" if enabled else "#F0F7FC", width=1.4))
        self.cam_pts.setBrush(pg.mkBrush("#087F9E" if enabled else "#17B9DC"))
        self.mini_pts.setBrush(pg.mkBrush("#087D78" if enabled else "#12C4BE"))
        self.gap_pts.setPen(pg.mkPen("#B54747" if enabled else "#FF6B6B", width=1.8))
        self.calcium_plot.setBackground("#F8F5EE" if enabled else "#0C1927")
        for axis_name in ("bottom", "left"):
            axis = self.calcium_plot.getAxis(axis_name)
            axis.setPen(pg.mkPen("#C5BEB1" if enabled else "#315067"))
            axis.setTextPen(pg.mkPen("#625E55" if enabled else "#C8D7E3"))
        self.calcium_curve.setPen(pg.mkPen("#087D78" if enabled else "#12C4BE", width=1.5))
        self.calcium_cursor.setPen(pg.mkPen("#49473F" if enabled else "#F0F7FC", width=1.4))
        self.theme_changed.emit(enabled)

    def theme_icon(self):
        pixmap = QPixmap(48, 48)
        pixmap.setDevicePixelRatio(2)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor("#454D46" if self.day_mode else "#365064"), 1.7)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        if self.day_mode:
            moon = QPainterPath()
            moon.moveTo(20, 14)
            moon.cubicTo(15, 16, 8, 10, 11, 3)
            moon.cubicTo(6, 3.5, 3, 7.5, 3, 12)
            moon.cubicTo(3, 17, 7, 21, 12, 21)
            moon.cubicTo(15.5, 21, 19, 18.5, 20, 14)
            painter.drawPath(moon)
        else:
            painter.drawEllipse(QRectF(7.5, 7.5, 9, 9))
            for x1, y1, x2, y2 in (
                (12, 2, 12, 4), (12, 20, 12, 22),
                (2, 12, 4, 12), (20, 12, 22, 12),
                (5, 5, 6.5, 6.5), (17.5, 17.5, 19, 19),
                (5, 19, 6.5, 17.5), (17.5, 6.5, 19, 5),
            ):
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        painter.end()
        return QIcon(pixmap)

    def card(self, obj_name="card"):
        frame = QFrame()
        frame.setObjectName(obj_name)
        return frame

    def app_stylesheet(self):
        stylesheet = """
        QWidget#root {
            background: #F3F7F9;
            color: #13263A;
            font-size: 13px;
        }
        QWidget { selection-background-color: #CDECF5; }

        QFrame#sidebar {
            background: #102131;
            border: 1px solid #173247;
            border-radius: 24px;
        }
        QFrame#sideCard {
            background: #14283A;
            border: 1px solid #213B4F;
            border-radius: 17px;
        }
        QFrame#viewerCard, QFrame#timelineCard {
            background: #FFFFFF;
            border: 1px solid #DCE7EC;
            border-radius: 20px;
        }

        QLabel#brandLogo { background: transparent; }
        QLabel#appTitle {
            color: #F4FAFD;
            font-size: 27px;
            font-weight: 700;
            background: transparent;
        }
        QLabel#sectionTitle {
            color: #F2F8FB;
            font-size: 13px;
            font-weight: 700;
            background: transparent;
        }
        QLabel#mainSectionTitle {
            color: #183249;
            font-size: 13px;
            font-weight: 700;
            background: transparent;
        }
        QLabel#controlLabel {
            color: #B7C7D4;
            font-size: 11px;
            font-weight: 650;
            background: transparent;
        }
        QLabel#navRowLabel {
            color: #D8E5EC;
            font-size: 11px;
            font-weight: 650;
            background: transparent;
        }
        QLabel#navSubhead {
            color: #7FDCE9;
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.5px;
            background: transparent;
        }
        QFrame#sideSeparator {
            background: #27485D;
            border: none;
        }
        QLabel#subtleText, QLabel#sidebarBody {
            color: #91A6B7;
            background: transparent;
        }
        QLabel#selectionInfo {
            color: #B5C5D2;
            font-size: 11px;
            background: transparent;
        }

        QLabel#panelTitle {
            color: #173148;
            font-size: 13px;
            font-weight: 700;
            background: transparent;
        }
        QLabel#accentDot {
            font-size: 11px;
            background: transparent;
        }
        QLabel#imageCanvas {
            background: #0B1825;
            color: #728596;
            border: 1px solid #11293B;
            border-radius: 14px;
        }

        QLabel#legendCyan, QLabel#legendTeal, QLabel#legendRed {
            padding: 5px 9px;
            border-radius: 12px;
            font-size: 10px;
            font-weight: 650;
        }
        QLabel#legendCyan {
            background: #E5F8FC;
            color: #087F9E;
        }
        QLabel#legendTeal {
            background: #E5F9F6;
            color: #087D78;
        }
        QLabel#legendRed {
            background: #FFE9E8;
            color: #B54747;
        }

        QFrame#trimSeparator {
            background: #E5EDF1;
            border: none;
        }
        QLabel#trimTitle {
            color: #173148;
            font-size: 12px;
            font-weight: 700;
            background: transparent;
        }
        QLabel#trimStatusPill {
            background: #EAF5F8;
            color: #4F6A79;
            border: 1px solid #D5E7EC;
            border-radius: 10px;
            padding: 4px 8px;
            font-size: 10px;
            font-weight: 600;
        }

        QPushButton {
            min-height: 32px;
            border-radius: 10px;
            border: 1px solid #CBD8DE;
            background: #FFFFFF;
            color: #183249;
            padding: 6px 10px;
            font-weight: 600;
        }
        QPushButton:hover { background: #F4F8FA; }
        QPushButton:pressed { background: #EAF1F4; }

        QPushButton[variant="source"] {
            min-height: 39px;
            background: #183146;
            color: #EAF5FA;
            border: 1px solid #27475D;
            text-align: left;
            padding: 8px 10px;
            font-size: 11px;
        }
        QPushButton[variant="source"]:hover {
            background: #1C3A51;
            border-color: #315873;
        }

        QPushButton[variant="soft"] {
            background: #193347;
            color: #D9E6ED;
            border: 1px solid #2B4A60;
            min-height: 36px;
        }
        QPushButton[variant="soft"]:hover {
            background: #1E3D54;
            border-color: #37617D;
        }

        QPushButton[variant="navStep"] {
            background: #193347;
            color: #EAF5FA;
            border: 1px solid #2B4A60;
            border-radius: 9px;
            padding: 0;
            font-size: 22px;
            font-weight: 500;
        }
        QPushButton[variant="navStep"]:hover {
            background: #20445D;
            border-color: #3C6C8A;
        }

        QPushButton[variant="teal"] {
            background: #12BEB8;
            color: #062A2A;
            border: 1px solid #12BEB8;
            min-height: 28px;
            padding: 4px 11px;
        }
        QPushButton[variant="teal"]:hover { background: #19CAC4; }

        QPushButton[variant="blue"] {
            background: #1479E8;
            color: #FFFFFF;
            border: 1px solid #1479E8;
            min-height: 28px;
            padding: 4px 12px;
        }
        QPushButton[variant="blue"]:hover { background: #0E6ED7; }

        QPushButton[variant="mainGhost"] {
            background: #F7FAFB;
            color: #365064;
            border: 1px solid #D8E3E8;
            min-height: 28px;
            padding: 4px 10px;
        }
        QPushButton[variant="mainGhost"]:hover { background: #EDF4F7; }

        QPushButton[variant="viewerTool"] {
            min-height: 26px;
            background: #F5FAFC;
            color: #3E596B;
            border: 1px solid #D6E5EB;
            border-radius: 9px;
            padding: 3px 9px;
            font-size: 10px;
        }
        QPushButton[variant="viewerTool"]:hover { background: #EAF6F9; }
        QPushButton[variant="viewerTool"]:checked {
            background: #DDF7FA;
            color: #087F9E;
            border-color: #93DCE7;
        }
        QPushButton[variant="viewerToolAccent"] {
            min-height: 26px;
            background: #1479E8;
            color: #FFFFFF;
            border: 1px solid #1479E8;
            border-radius: 9px;
            padding: 3px 10px;
            font-size: 10px;
        }
        QPushButton[variant="viewerToolAccent"]:hover { background: #0E6ED7; }
        QPushButton:disabled {
            color: #9BAAB4;
            background: #F1F5F7;
            border-color: #E1E9ED;
        }

        QComboBox, QSpinBox {
            min-height: 33px;
            border-radius: 10px;
            background: #183146;
            color: #EEF7FB;
            border: 1px solid #2C4C62;
            padding: 3px 9px;
        }
        QComboBox:hover, QSpinBox:hover { border-color: #3C6B88; }
        QComboBox:focus, QSpinBox:focus { border-color: #17B9DC; }
        QComboBox QAbstractItemView {
            background: #14283A;
            color: #EEF7FB;
            border: 1px solid #2C4C62;
            selection-background-color: #1479E8;
        }

        QLabel { background: transparent; }
        QToolTip {
            background: #0E1D2A;
            color: #F0F8FB;
            border: 1px solid #29475D;
            border-radius: 7px;
            padding: 6px;
        }
        QSplitter::handle {
            background: transparent;
            width: 9px;
        }
        """
        if self.day_mode:
            stylesheet += """
            QMainWindow, QDialog, QWidget#root {
                background: #F2EEE5;
                color: #353B38;
            }
            QFrame#sidebar {
                background: #E8E2D6;
                border-color: #D6CEBF;
            }
            QFrame#sideCard {
                background: #F3EFE6;
                border-color: #DCD5C8;
            }
            QFrame#viewerCard, QFrame#timelineCard {
                background: #FAF7F0;
                border-color: #DED8CC;
            }
            QLabel#appTitle, QLabel#sectionTitle, QLabel#mainSectionTitle,
            QLabel#panelTitle, QLabel#trimTitle {
                color: #353B38;
            }
            QLabel#controlLabel, QLabel#navRowLabel, QLabel#selectionInfo {
                color: #575C54;
            }
            QLabel#subtleText, QLabel#sidebarBody { color: #686B61; }
            QLabel#navSubhead { color: #287B77; }
            QFrame#sideSeparator, QFrame#trimSeparator { background: #DCD5C8; }
            QLabel#imageCanvas {
                background: #EDE8DE;
                color: #737469;
                border-color: #DCD5C8;
            }
            QLabel#trimStatusPill {
                background: #E8EDE5;
                color: #53675D;
                border-color: #D2DCCE;
            }
            QPushButton, QPushButton[variant="source"],
            QPushButton[variant="soft"], QPushButton[variant="navStep"],
            QPushButton[variant="mainGhost"], QPushButton[variant="viewerTool"] {
                background: #F8F5EE;
                color: #454D46;
                border-color: #D2CCBF;
            }
            QPushButton:hover, QPushButton[variant="source"]:hover,
            QPushButton[variant="soft"]:hover, QPushButton[variant="navStep"]:hover,
            QPushButton[variant="mainGhost"]:hover, QPushButton[variant="viewerTool"]:hover {
                background: #E9E5DA;
                border-color: #B9B6A8;
            }
            QPushButton:pressed { background: #DFDCCF; }
            QPushButton[variant="soft"]:checked,
            QPushButton[variant="viewerTool"]:checked {
                background: #DDEAE1;
                color: #25675C;
                border-color: #ABC9B9;
            }
            QPushButton[variant="teal"] {
                background: #287D71;
                color: #FAF7F0;
                border-color: #287D71;
            }
            QPushButton[variant="teal"]:hover { background: #216B61; }
            QPushButton:disabled {
                background: #EEEAE1;
                color: #96968B;
                border-color: #DFDACE;
            }
            QComboBox, QSpinBox, QComboBox QAbstractItemView {
                background: #F8F5EE;
                color: #454D46;
                border-color: #D2CCBF;
                selection-background-color: #DDEAE1;
                selection-color: #25675C;
            }
            QComboBox:hover, QSpinBox:hover { border-color: #AAAFA0; }
            QComboBox:focus, QSpinBox:focus { border-color: #287D71; }
            QToolTip {
                background: #F8F5EE;
                color: #454D46;
                border-color: #C6C0B3;
            }
            """
        stylesheet += """
            QPushButton#themeToggle {
                min-height: 34px;
                padding: 0;
                border-radius: 18px;
            }
        """
        icon_dir = Path(__file__).with_name("icons").as_posix()
        control_border = "#D2CCBF" if self.day_mode else "#2C4C62"
        stylesheet += f"""
            QTabWidget::pane {{ border: none; }}
            QTabBar::tab {{
                background: {"#E8E2D6" if self.day_mode else "#E5EDF1"};
                color: #53675D;
                border-radius: 8px;
                margin-right: 5px;
                padding: 6px 12px;
                font-weight: 600;
            }}
            QTabBar::tab:selected {{
                background: {"#DDEAE1" if self.day_mode else "#DDF7FA"};
                color: #25675C;
            }}
            QCheckBox, QLabel#calciumStatus {{ color: #686B61; }}
            QCheckBox {{ spacing: 6px; }}
            QCheckBox::indicator {{ width: 14px; height: 14px; }}
            QCheckBox::indicator:checked {{
                background: #287D71; border: 1px solid #287D71; border-radius: 4px;
            }}
            QCheckBox::indicator:unchecked {{
                background: {"#F8F5EE" if self.day_mode else "#FFFFFF"};
                border: 1px solid #96968B; border-radius: 4px;
            }}
            QTabWidget QComboBox, QTabWidget QSpinBox {{
                background: {"#F8F5EE" if self.day_mode else "#F1F5F7"};
                color: #454D46;
                border-color: {control_border};
                min-height: 30px;
                max-height: 30px;
                padding: 0 28px 0 8px;
                font-size: 11px;
            }}
            QComboBox#videoMapping, QSpinBox#mp4Offset {{
                min-height: 32px;
                max-height: 32px;
                padding: 0 28px 0 10px;
            }}
            QComboBox#videoMapping::drop-down, QTabWidget QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 26px;
                border: none;
                border-left: 1px solid {control_border};
            }}
            QComboBox#videoMapping::down-arrow, QTabWidget QComboBox::down-arrow {{
                image: url("{icon_dir}/chevron-down.svg");
                width: 10px;
                height: 6px;
            }}
            QSpinBox#mp4Offset::up-button, QSpinBox#mp4Offset::down-button,
            QTabWidget QSpinBox::up-button, QTabWidget QSpinBox::down-button {{
                subcontrol-origin: padding;
                width: 22px;
                height: 16px;
                border: none;
                border-left: 1px solid {control_border};
            }}
            QSpinBox#mp4Offset::up-button, QTabWidget QSpinBox::up-button {{ subcontrol-position: top right; }}
            QSpinBox#mp4Offset::down-button, QTabWidget QSpinBox::down-button {{ subcontrol-position: bottom right; }}
            QSpinBox#mp4Offset::up-arrow, QTabWidget QSpinBox::up-arrow {{
                image: url("{icon_dir}/chevron-up.svg");
                width: 8px;
                height: 5px;
            }}
            QSpinBox#mp4Offset::down-arrow, QTabWidget QSpinBox::down-arrow {{
                image: url("{icon_dir}/chevron-down.svg");
                width: 8px;
                height: 5px;
            }}
        """
        return stylesheet

    def choose(self, title, filt):
        p, _ = QFileDialog.getOpenFileName(self, title, "", filt)
        return p

    def mark_loaded(self, key, loaded):
        btn = self.source_buttons.get(key)
        if btn:
            base = btn.text().replace("  ✓", "")
            btn.setText(base + ("  ✓" if loaded else ""))

    def update_file_state(self):
        return

    def load_camera(self):
        p = self.choose("Camera TTL CSV", "CSV (*.csv)")
        if not p:
            return
        try:
            camera_df = load_csv(p, "Camera")
            self.camera_df = fill_camera_timestamps(camera_df)
            self.camera_source_columns = list(camera_df.columns)
            self.camera_source_row_count = len(camera_df)
            self.camera_csv_path = Path(p)
            self.clear_trim()
            self.rebuild()
            self.mark_loaded("Camera CSV", True)
            self.update_file_state()
        except Exception as e:
            self.err(e)

    def load_mini(self):
        p = self.choose("Mini2P TTL CSV", "CSV (*.csv)")
        if not p:
            return
        try:
            self.mini_df = load_csv(p, "Mini2P")
            self.mini_csv_path = Path(p)
            self.rebuild()
            self.mark_loaded("Mini2P CSV", True)
            self.update_file_state()
        except Exception as e:
            self.err(e)

    def load_video(self):
        p = self.choose("Behavior video", "Video (*.mp4 *.avi *.mov *.mkv)")
        if not p:
            return
        try:
            self.video.open(p)
            self.alignment_changed.emit()
            self.video_path = Path(p)
            self.spatial_crop_rect = None
            self.cam_panel.clear_crop()
            self.cam_panel.set_crop_available(True)
            self.update_trim_preview()
            self.update_views()
            self.mark_loaded("Behavior MP4", True)
            self.update_file_state()
        except Exception as e:
            self.err(e)

    def load_tiff(self):
        p = self.choose("ScanImage TIFF", "TIFF (*.tif *.tiff)")
        if not p:
            return
        try:
            self.tiff.open(p)
            self.tiff_first_frame = 1
            self.update_views()
            self.mark_loaded("ScanImage TIFF", True)
            self.refresh_calcium_trace()
            self.update_file_state()
        except Exception as e:
            self.err(e)

    def rebuild(self):
        self.alignment_changed.emit()
        if self.mini_df is None:
            return
        self.t0 = float(self.mini_df.timestamp_ms.iloc[0])
        self.mini_t = self.mini_df.timestamp_ms.to_numpy(float) - self.t0
        self.mini_df["time_ms"] = self.mini_t
        self.mini_dt = np.r_[np.nan, np.diff(self.mini_t)]
        pm = median_period(self.mini_t)
        self.mini_gap = self.mini_dt > (1.5 * pm) if np.isfinite(pm) else np.zeros(len(self.mini_t), bool)
        if self.camera_df is not None:
            self.camera_t = self.camera_df.timestamp_ms.to_numpy(float) - self.t0
            self.camera_df["time_ms"] = self.camera_t
            self.camera_dt = np.r_[np.nan, np.diff(self.camera_t)]
            pc = median_period(self.camera_t)
            self.camera_gap = self.camera_dt > (1.5 * pc) if np.isfinite(pc) else np.zeros(len(self.camera_t), bool)
            self.camera_virtual = virtual_camera_indices(self.camera_t)
        self.draw()
        self.set_time(float(self.mini_t[0]))

    def visible_timeline_times(self):
        mini_t, camera_t = self.mini_t, self.camera_t
        if self.trim_idx is not None and camera_t is not None and len(camera_t):
            cut = float(camera_t[self.trim_idx])
            camera_t = camera_t[:self.trim_idx + 1]
            if mini_t is not None:
                mini_t = mini_t[:np.searchsorted(mini_t, cut, side="right")]
        return mini_t, camera_t

    def draw(self):
        mini_t, camera_t = self.visible_timeline_times()
        self.mini_pts.setData(x=mini_t if mini_t is not None else [],
                              y=np.zeros(len(mini_t) if mini_t is not None else 0))
        self.cam_pts.setData(x=camera_t if camera_t is not None else [],
                             y=np.ones(len(camera_t) if camera_t is not None else 0))
        gaps = camera_t[self.camera_gap[:len(camera_t)]] if camera_t is not None else np.array([])
        self.gap_pts.setData(x=gaps, y=np.ones(len(gaps)))
        arr = [x for x in (mini_t, camera_t) if x is not None and len(x)]
        if arr:
            a = np.concatenate(arr)
            lo = float(a.min())
            hi = float(a.max())
            m = max(20., (hi - lo) * .02)
            self.plot.setXRange(lo - m, hi + m, padding=0)
        self.update_trim_visual()
        self.refresh_calcium_trace()

    def nearest(self, a, t):
        return None if a is None or len(a) == 0 else int(np.argmin(np.abs(a - t)))

    def set_time(self, t):
        self.current_t = float(t)
        if self.caiman is not None and self.mini_df is not None and self.mini_t is not None:
            mi = self.nearest(self.mini_t, t)
            if mi is not None:
                index = int(self.mini_df.frame.iloc[mi]) - self.calcium_first_frame.value()
                self.calcium_sample_index = index if 0 <= index < self.caiman.n_frames else None
                self.sync_calcium_movie_controls()
        self.cursor_line.blockSignals(True)
        self.cursor_line.setValue(self.current_t)
        self.cursor_line.blockSignals(False)
        self.calcium_cursor.blockSignals(True)
        position = (1 + (self.calcium_sample_index or 0)
                    if self.calcium_movie_mode else self.current_t)
        self.calcium_cursor.setValue(position)
        self.calcium_cursor.blockSignals(False)
        self.update_views()
        self.time_changed.emit(self.current_t)

    def plot_clicked(self, e):
        if e.button() != Qt.LeftButton:
            return
        p = self.plot.getViewBox().mapSceneToView(e.scenePos())
        self.set_time(float(p.x()))

    def step_mini(self, d):
        if self.calcium_movie_mode and self.caiman is not None and self.timeline_tabs.currentIndex() == 1:
            self.set_calcium_sample((self.calcium_sample_index or 0) + d)
            return
        mini_t, _ = self.visible_timeline_times()
        i = self.nearest(mini_t, self.current_t)
        if i is None:
            return
        i = int(np.clip(i + d, 0, len(mini_t) - 1))
        self.set_time(float(mini_t[i]))

    def jump_gap(self, d):
        _, camera_t = self.visible_timeline_times()
        if camera_t is None:
            return
        g = camera_t[self.camera_gap[:len(camera_t)]]
        if not len(g):
            return
        if d > 0:
            c = g[g > self.current_t + 1e-9]
            target = c[0] if len(c) else g[0]
        else:
            c = g[g < self.current_t - 1e-9]
            target = c[-1] if len(c) else g[-1]
        self.set_time(float(target))

    def video_index(self, ci):
        if ci is None:
            return None
        base = int(self.camera_virtual[ci]) if self.mode.currentText() == "Timing reconstruction" else ci
        return int(self.offset.value()) + base

    def update_views(self):
        t = self.current_t
        mi = self.nearest(self.mini_t, t)
        ci = self.nearest(self.camera_t, t)
        mf = None
        image_title = "Mini2P"
        minfo = "No Mini2P TTL loaded"
        movie_view = self.caiman is not None and self.calcium_movie_mode and self.timeline_tabs.currentIndex() == 1
        movie_time = None
        if movie_view and self.calcium_sample_index is not None:
            sample = self.calcium_sample_index
            fn = self.calcium_first_frame.value() + sample
            movie_time = self.calcium_sample_times()[sample]
            minfo = f"Movie frame {sample + 1}/{self.caiman.n_frames} · Mini2P frame {fn}"
            minfo += f" · t={movie_time:.3f} ms" if np.isfinite(movie_time) else " · No measured TTL time"
            if self.tiff.tif is not None:
                corrected = (self.processing_manifest is not None and
                             Path(self.tiff.tif.filehandle.path).resolve() == Path(self.processing_manifest["outputs"]["corrected_tiff"]).resolve())
                mf = self.tiff.read(sample if corrected else fn - self.tiff_first_frame)
                if corrected:
                    image_title = "Mini2P · motion corrected"
        elif mi is not None:
            mt = float(self.mini_t[mi])
            fn = int(self.mini_df.frame.iloc[mi])
            minfo = f"Frame {fn} · t={mt:.3f} ms · cursor Δ={t - mt:+.3f} ms"
            if self.tiff.tif is not None:
                page = fn - self.tiff_first_frame
                mf = self.tiff.read(page)
                minfo += f" · TIFF page {page + 1}"
        if mf is None and self.caiman is not None:
            mf = self.calcium_reference
            if mf is not None:
                minfo += " · CaImAn correlation image (static)"
                image_title = "Mini2P · CaImAn reference"
            elif self.calcium_footprint is not None:
                mf = self.calcium_footprint
                minfo += " · Selected CaImAn spatial footprint (static)"
                image_title = "Mini2P · CaImAn footprint"
        self.mini_panel.title_label.setText(image_title)
        self.mini_panel.set_frame(mf, minfo)

        cf = None
        if movie_view and self.calcium_sample_index is not None and not np.isfinite(movie_time):
            self.cam_panel.set_frame(None, "No synchronized behavior time for this calcium frame.")
            return
        cinfo = "No camera TTL loaded"
        if ci is None and self.video.cap is not None:
            cf = self.video.read(0)
            cinfo = "MP4 frame 1"
        if ci is not None:
            ct = float(self.camera_t[ci])
            fn = int(self.camera_df.frame.iloc[ci])
            cinfo = f"STROBE {fn} · t={ct:.3f} ms · cursor Δ={t - ct:+.3f} ms"
            if ci > 0:
                cinfo += f" · interval={self.camera_dt[ci]:.3f} ms"
            if self.camera_gap[ci]:
                cinfo += " · gap"
            if self.video.cap is not None:
                vi = self.video_index(ci)
                cf = self.video.read(vi)
                cinfo += f" · MP4 frame {vi + 1}"
        self.cam_panel.set_frame(cf, cinfo, bgr=True)


    def set_spatial_crop(self, rect):
        self.spatial_crop_rect = tuple(rect) if rect is not None else None

    def normalized_spatial_crop(self):
        if self.spatial_crop_rect is None or self.video.cap is None:
            return None
        x, y, w, h = map(int, self.spatial_crop_rect)
        x = int(np.clip(x, 0, max(0, self.video.width - 2)))
        y = int(np.clip(y, 0, max(0, self.video.height - 2)))
        w = int(np.clip(w, 2, self.video.width - x))
        h = int(np.clip(h, 2, self.video.height - y))

        # Most MP4 encoders are happier with even dimensions.
        if w % 2:
            w -= 1
        if h % 2:
            h -= 1
        if w < 2 or h < 2:
            return None
        return (x, y, w, h)

    def export_spatial_crop(self):
        if self.video.cap is None or self.video_path is None:
            QMessageBox.warning(self, "Crop video", "Load the behavior MP4 first.")
            return
        crop = self.normalized_spatial_crop()
        if crop is None:
            QMessageBox.warning(self, "Crop video", "Draw a crop on the behavior camera first.")
            return

        x, y, w, h = crop
        answer = QMessageBox.question(
            self,
            "Export cropped video",
            f"Apply the selected {w}×{h} crop to all {self.video.count} video frames?\n\nThe original MP4 will not be modified.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return

        parent = QFileDialog.getExistingDirectory(
            self,
            "Choose folder for cropped video",
            str(self.video_path.parent),
        )
        if not parent:
            return

        out = Path(parent) / ("cropped_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        out.mkdir(parents=True, exist_ok=False)
        video_out = out / "behavior_cropped.mp4"
        info_out = out / "crop_info.json"

        cap = cv2.VideoCapture(str(self.video_path))
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        writer = cv2.VideoWriter(
            str(video_out),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (w, h),
        )
        if not cap.isOpened() or not writer.isOpened():
            cap.release()
            writer.release()
            raise RuntimeError("Could not open source/output MP4 for cropping")

        progress = QProgressDialog(
            "Exporting cropped behavior video…",
            "Cancel",
            0,
            self.video.count,
            self,
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        written = 0
        cancelled = False
        try:
            while written < self.video.count:
                ok, frame = cap.read()
                if not ok:
                    break
                cropped = frame[y:y + h, x:x + w]
                writer.write(cropped)
                written += 1
                if written % 10 == 0 or written == self.video.count:
                    progress.setValue(written)
                    QApplication.processEvents()
                if progress.wasCanceled():
                    cancelled = True
                    break
        finally:
            cap.release()
            writer.release()
            progress.close()

        if cancelled:
            video_out.unlink(missing_ok=True)
            try:
                out.rmdir()
            except OSError:
                pass
            return
        if written != self.video.count:
            raise RuntimeError(f"Video ended early: wrote {written}/{self.video.count} frames")

        info = {
            "source_behavior_video": str(self.video_path),
            "source_width": int(self.video.width),
            "source_height": int(self.video.height),
            "crop": {"x": x, "y": y, "width": w, "height": h},
            "frames": int(self.video.count),
            "fps": float(self.video.fps),
        }
        info_out.write_text(json.dumps(info, indent=2), encoding="utf-8")
        QMessageBox.information(
            self,
            "Crop complete",
            f"Created:\n{video_out.name}\n{info_out.name}\n\nOriginal video was not modified.",
        )


    def open_tracking_alignment(self):
        if self.mini_t is None or self.camera_t is None:
            QMessageBox.warning(self, "Tracking alignment", "Load the Camera CSV and Mini2P CSV first.")
            return
        dlg = TrackingAlignmentDialog(self)
        dlg.show()
        # Keep a reference so the non-modal dialog is not garbage-collected.
        self._tracking_alignment_dialog = dlg

    def open_movement_analysis(self):
        if self.caiman is None or self.mini_t is None or self.camera_t is None:
            QMessageBox.warning(self, "Movement analysis", "Load CaImAn results and both TTL CSV files first.")
            return
        dialog = getattr(self, "_movement_analysis_dialog", None)
        if dialog is None:
            dialog = MovementAnalysisDialog(self, TrackingAlignmentDialog)
            self._movement_analysis_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def mapping_changed(self):
        self.alignment_changed.emit()
        self.update_trim_preview()
        self.update_trim_visual()
        self.update_views()

    def clear_trim(self):
        self.alignment_changed.emit()
        self.trim_idx = None
        if hasattr(self, "trim_line"):
            self.trim_line.hide()
            self.trim_region.hide()
        if hasattr(self, "trim_preview"):
            self.trim_preview.setText("Not set")
        self.draw()

    def auto_trim(self):
        if self.mini_t is None or self.camera_t is None or len(self.mini_t) == 0 or len(self.camera_t) == 0:
            QMessageBox.warning(self, "Trim", "Load both TTL CSV files first.")
            return
        end = float(self.mini_t[-1])
        idx = int(np.searchsorted(self.camera_t, end, side="right") - 1)
        if idx < 0:
            QMessageBox.warning(self, "Trim", "No camera STROBE occurs before the Mini2P end.")
            return
        self.trim_idx = idx
        self.alignment_changed.emit()
        self.draw()
        self.update_trim_preview()
        self.set_time(float(self.camera_t[idx]))

    def set_trim_current(self):
        i = self.nearest(self.camera_t, self.current_t)
        if i is None:
            QMessageBox.warning(self, "Trim", "Load the camera TTL CSV first.")
            return
        self.trim_idx = i
        self.alignment_changed.emit()
        self.draw()
        self.update_trim_preview()

    def update_trim_visual(self):
        if self.trim_idx is None or self.camera_t is None or len(self.camera_t) == 0:
            if hasattr(self, "trim_line"):
                self.trim_line.hide()
                self.trim_region.hide()
            return
        cut = float(self.camera_t[self.trim_idx])
        self.trim_line.setValue(cut)
        self.trim_line.show()
        self.trim_region.hide()

    def update_trim_preview(self):
        if not hasattr(self, "trim_preview"):
            return
        if self.trim_idx is None or self.camera_t is None or self.camera_df is None:
            self.trim_preview.setText("Not set")
            return
        i = int(self.trim_idx)
        ttl = int(self.camera_df.frame.iloc[i])
        if self.mini_t is not None and len(self.mini_t):
            delta = float(self.camera_t[i] - self.mini_t[-1])
            self.trim_preview.setText(f"STROBE {ttl}  ·  {delta:+.1f} ms")
        else:
            self.trim_preview.setText(f"STROBE {ttl}")

    def export_trim(self):
        if self.trim_idx is None:
            QMessageBox.warning(self, "Export trim", "Select a trim point first.")
            return
        if self.camera_df is None or self.camera_csv_path is None:
            QMessageBox.warning(self, "Export trim", "Camera CSV is not loaded.")
            return
        if self.video.cap is None or self.video_path is None:
            QMessageBox.warning(self, "Export trim", "Behavior MP4 is not loaded.")
            return
        i = int(self.trim_idx)
        vi = self.video_index(i)
        if vi is None or vi < 0 or vi >= self.video.count:
            QMessageBox.warning(self, "Export trim", "Selected trim point maps outside the MP4. Check mapping mode / offset.")
            return
        crop = self.normalized_spatial_crop()
        crop_note = ""
        if crop is not None:
            crop_note = f"\nSpatial crop: {crop[2]}×{crop[3]} px will also be applied."
        answer = QMessageBox.question(
            self,
            "Export trimmed copy",
            f"Keep camera CSV rows 1–{i + 1} and MP4 frames 1–{vi + 1}?{crop_note}\n\nOriginal files will NOT be modified.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        parent = QFileDialog.getExistingDirectory(self, "Choose folder for trimmed export", str(self.video_path.parent))
        if not parent:
            return
        out = Path(parent) / ("trimmed_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        out.mkdir(parents=True, exist_ok=False)
        csv_out = out / "camera_trimmed.csv"
        video_out = out / "behavior_trimmed.mp4"
        info_out = out / "trim_info.json"
        cols = self.camera_source_columns or [c for c in self.camera_df.columns if c != "time_ms"]
        self.camera_df.iloc[: i + 1][cols].to_csv(csv_out, index=False)

        cap = cv2.VideoCapture(str(self.video_path))
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        source_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        source_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        crop = self.normalized_spatial_crop()
        if crop is not None:
            crop_x, crop_y, out_w, out_h = crop
        else:
            crop_x, crop_y, out_w, out_h = 0, 0, source_w, source_h
        writer = cv2.VideoWriter(str(video_out), cv2.VideoWriter_fourcc(*"mp4v"), fps, (out_w, out_h))
        if not cap.isOpened() or not writer.isOpened():
            cap.release()
            writer.release()
            raise RuntimeError("Could not open source/output MP4 for trimming")
        n = vi + 1
        progress = QProgressDialog("Exporting trimmed behavior video…", "Cancel", 0, n, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        written = 0
        cancelled = False
        try:
            while written < n:
                ok, frame = cap.read()
                if not ok:
                    break
                if crop is not None:
                    frame = frame[crop_y:crop_y + out_h, crop_x:crop_x + out_w]
                writer.write(frame)
                written += 1
                if written % 10 == 0 or written == n:
                    progress.setValue(written)
                    QApplication.processEvents()
                if progress.wasCanceled():
                    cancelled = True
                    break
        finally:
            cap.release()
            writer.release()
            progress.close()
        if cancelled:
            video_out.unlink(missing_ok=True)
            csv_out.unlink(missing_ok=True)
            try:
                out.rmdir()
            except OSError:
                pass
            return
        if written != n:
            raise RuntimeError(f"Video ended early: wrote {written}/{n} frames")
        info = {
            "source_camera_csv": str(self.camera_csv_path),
            "source_behavior_video": str(self.video_path),
            "mapping_mode": self.mode.currentText(),
            "mp4_start_offset_zero_based": int(self.offset.value()),
            "selected_camera_ttl_frame": int(self.camera_df.frame.iloc[i]),
            "selected_camera_time_ms_relative_to_first_mini2p": float(self.camera_t[i]),
            "camera_csv_rows_original": int(
                self.camera_source_row_count if self.camera_source_row_count is not None else len(self.camera_df)
            ),
            "camera_csv_rows_kept": int(i + 1),
            "mp4_frames_original": int(self.video.count),
            "mp4_frames_kept": int(n),
            "spatial_crop": (
                {"x": crop[0], "y": crop[1], "width": crop[2], "height": crop[3]}
                if crop is not None else None
            ),
        }
        if self.mini_t is not None and len(self.mini_t):
            info.update({
                "last_mini2p_frame": int(self.mini_df.frame.iloc[-1]),
                "last_mini2p_time_ms": float(self.mini_t[-1]),
            })
        info_out.write_text(json.dumps(info, indent=2), encoding="utf-8")
        QMessageBox.information(self, "Trim complete", f"Created:\n{csv_out.name}\n{video_out.name}\n{info_out.name}\n\nOriginal files were not modified.")

    def mouse_moved(self, p):
        self.hover_pos = p
        self.hover_timer.start()

    def show_hover(self):
        if self.hover_pos is None:
            return
        vb = self.plot.getViewBox()
        q = vb.mapSceneToView(self.hover_pos)
        x = float(q.x())
        y = float(q.y())
        (x0, x1), _ = vb.viewRange()
        width = max(self.plot.getPlotItem().vb.sceneBoundingRect().width(), 1)
        tol = abs(x1 - x0) * 8 / width
        text = None
        mini_t, camera_t = self.visible_timeline_times()
        if y >= .5 and camera_t is not None and len(camera_t):
            i = self.nearest(camera_t, x)
            tt = float(self.camera_t[i])
            if abs(tt - x) <= tol:
                j = self.nearest(self.mini_t, tt)
                lines = [f"Camera STROBE #{int(self.camera_df.frame.iloc[i])}", f"t = {tt:.3f} ms"]
                if i > 0:
                    lines.append(f"interval = {self.camera_dt[i]:.3f} ms")
                if self.camera_gap[i]:
                    lines.append("gap detected")
                if j is not None:
                    lines += ["", f"Nearest Mini2P #{int(self.mini_df.frame.iloc[j])}", f"t = {self.mini_t[j]:.3f} ms", f"Δ = {tt - self.mini_t[j]:+.3f} ms"]
                text = "\n".join(lines)
        elif y < .5 and mini_t is not None and len(mini_t):
            i = self.nearest(mini_t, x)
            tt = float(self.mini_t[i])
            if abs(tt - x) <= tol:
                j = self.nearest(self.camera_t, tt)
                lines = [f"Mini2P frame #{int(self.mini_df.frame.iloc[i])}", f"t = {tt:.3f} ms"]
                if j is not None:
                    lines += ["", f"Nearest camera STROBE #{int(self.camera_df.frame.iloc[j])}", f"t = {self.camera_t[j]:.3f} ms", f"Δ = {self.camera_t[j] - tt:+.3f} ms"]
                text = "\n".join(lines)
        if text:
            QToolTip.showText(self.cursor().pos(), text, self.plot)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Left:
            self.step_mini(-1)
            return
        if e.key() == Qt.Key_Right:
            self.step_mini(1)
            return
        if e.key() == Qt.Key_PageUp:
            self.jump_gap(-1)
            return
        if e.key() == Qt.Key_PageDown:
            self.jump_gap(1)
            return
        super().keyPressEvent(e)

    def err(self, e):
        QMessageBox.critical(self, "Error", f"{type(e).__name__}: {e}")

    def closeEvent(self, e):
        processing = getattr(self, "_calcium_processing_dialog", None)
        if processing is not None and processing.is_running():
            QMessageBox.warning(self, "Calcium processing", "Cancel the active processing job before closing CALI.")
            e.ignore()
            return
        if processing is not None:
            processing.close()
        self.playback_timer.stop()
        self.video.close()
        self.tiff.close()
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    pg.setConfigOptions(antialias=True)
    v = Viewer()
    v.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
