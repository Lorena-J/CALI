"""Qt dialog for timestamp-based tracking alignment and its exports."""
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QDialog,
    QSpinBox, QVBoxLayout, QWidget, QProgressDialog, QTabWidget,
)

from .video_exports import write_aligned_video, write_aligned_mapping, VideoExportOpenError
from .timing import median_period
from .tracking import (load_tracking_table, tracking_indices,
                       build_video_times, align_coordinate)

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
        else:
            for original, replacement in (
                ("#F3F7F9", "#102131"), ("#FFFFFF", "#14283A"),
                ("background: white", "background: #193347"),
                ("#13263A", "#EAF5FA"), ("#102A43", "#EAF5FA"),
                ("#15364D", "#EAF5FA"), ("#10344D", "#F3E79B"),
                ("#6A8193", "#91A6B7"), ("#557084", "#B7C7D4"),
                ("#D9E7EE", "#315067"), ("#C9DCE6", "#315067"),
                ("#EAF3F7", "#193347"), ("#EDF8FB", "#393448"),
                ("#8FDDE5", "#73647E"), ("#12BFC0", "#443443"),
                ("#1479E8", "#393448"),
            ):
                stylesheet = stylesheet.replace(original, replacement)
            stylesheet += """
                QLabel { color: #EAF5FA; }
                QComboBox QAbstractItemView {
                    background: #193347; color: #EAF5FA;
                    selection-background-color: #393448; selection-color: #F3E79B;
                }
                QPushButton[variant="primary"] { color: #FAC484; }
                QPushButton[variant="blue"] { color: #F3E79B; }
                QPushButton:disabled { background: #14283A; color: #728596; border-color: #27485D; }
            """
        self.setStyleSheet(stylesheet)
        text = "#455D6D" if day_mode else "#C8D7E3"
        for plot in (self.time_plot, self.frame_plot):
            plot.setBackground("#FAF7F0" if day_mode else "#14283A")
            for name in ("bottom", "left"):
                axis = plot.getAxis(name)
                axis.setTextPen(pg.mkPen(text))
                axis.setPen(pg.mkPen("#A9BAC5" if day_mode else "#315067"))
                axis.setLabel(axis.labelText, units=axis.labelUnits, color=text)
            legend = plot.plotItem.legend
            if legend is not None:
                for _, label in legend.items:
                    label.setText(label.text, color=text)
        accent = self.viewer.accent_palette()["mini"]
        self.aligned_curve.setPen(pg.mkPen(accent, width=2.2))
        self.frame_curve.setPen(pg.mkPen(accent, width=2.2))

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

    def tracking_indices(self, n_video=None):
        return tracking_indices(self.tracking_df, n_video)

    def load_tracking(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load tracking CSV", "", "CSV files (*.csv);;All files (*)")
        if not path:
            return
        try:
            df, numeric = load_tracking_table(path)
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
        camera_times = v.visible_timeline_times()[1]
        mapped = [v.video_index(i) for i in range(len(camera_times))]
        return build_video_times(n_frames, camera_times, mapped)

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
        mini_end = float(v.mini_t[-1])
        if v.trim_idx is not None:
            mini_end = min(mini_end, float(v.camera_t[v.trim_idx]))
        camera_times = v.visible_timeline_times()[1]
        result, video_indices, raw_window, usable, has_frame, mode_name = align_coordinate(
            x, indices, video_times, camera_times=camera_times,
            camera_frames=np.asarray([v.video_index(i) for i in range(len(camera_times))]),
            mini_times=v.mini_t, mini_frames=v.mini_df.frame.to_numpy(int), mini_end=mini_end,
            camera_period=median_period(v.camera_t), mode_index=self.mode_combo.currentIndex(),
            max_missing_frames=self.max_missing_frames.value())
        target_times = result.target_time_ms.to_numpy()
        target_frame = result.target_frame.to_numpy()
        target_x = result.x_aligned.to_numpy()
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

        crop = v.normalized_spatial_crop()
        progress = QProgressDialog("Exporting aligned behavior video…", "Cancel", 0, len(target_video_indices), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        def advance(written):
            progress.setValue(written)
            QApplication.processEvents()
            return progress.wasCanceled()

        cancelled = False
        try:
            cancelled = write_aligned_video(
                v.video_path, path, target_times, target_video_indices,
                source_fps=v.video.fps, crop=crop, progress=advance)
        except VideoExportOpenError as exc:
            QMessageBox.critical(self, "Aligned video", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Aligned video", f"{type(exc).__name__}: {exc}")
            cancelled = True
        finally:
            progress.close()
        if cancelled:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass
            return

        # Sidecar mapping for provenance.
        mapping_path = write_aligned_mapping(path, result_df)
        QMessageBox.information(
            self,
            "Aligned video",
            "Aligned video exported.\n\n"
            "Tracking positions use linear interpolation within the allowed gaps. "
            "Covered times use the nearest real behavior frame. Times without video coverage "
            "use blank images to preserve frame correspondence.\n\n"
            f"Video: {path}\nMapping: {mapping_path}"
        )
