"""Qt workflow for descriptive calcium activity versus tracked movement."""
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
    QGridLayout, QHBoxLayout, QLabel, QMessageBox, QProgressDialog,
    QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget, QAbstractItemView, QHeaderView,
)

from movement_analysis import prepare_speed, align_speed, analyze_cells, lag_correlations


class MovementAnalysisDialog(QDialog):
    def __init__(self, viewer, tracking_factory):
        super().__init__(viewer)
        self.viewer = viewer
        self.tracking_reader = tracking_factory(viewer)
        self.tracking_path = None
        self.numeric_data = {}
        self.summary = self.context = self.behavior = None
        self.generation = 0
        self.setWindowTitle("CALI · Movement analysis")
        self.resize(1140, 850)
        self.setMinimumSize(1000, 760)
        self.build_ui()
        viewer.alignment_changed.connect(self.invalidate)
        viewer.calcium_source_changed.connect(self.invalidate)
        viewer.calcium_first_frame.valueChanged.connect(self.invalidate)
        viewer.theme_changed.connect(self.apply_theme)
        viewer.time_changed.connect(self.move_cursor)
        self.apply_theme(viewer.day_mode)
        existing = getattr(viewer, "_tracking_alignment_dialog", None)
        if existing is not None and existing.tracking_path is not None:
            self.load_tracking_path(existing.tracking_path)

    @staticmethod
    def number(minimum, maximum, value, decimals=2, suffix=""):
        field = QDoubleSpinBox()
        field.setDecimals(decimals)
        field.setRange(minimum, maximum)
        field.setValue(value)
        field.setSuffix(suffix)
        return field

    def build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        title = QLabel("Calcium & movement")
        title.setObjectName("analysisTitle")
        layout.addWidget(title)
        description = QLabel("Use tracking from the behavior video. Frame IDs are mapped through the camera TTLs; missing or low-confidence tracking is excluded.")
        description.setWordWrap(True)
        layout.addWidget(description)
        load_row = QHBoxLayout()
        load = QPushButton("Load tracking CSV")
        load.clicked.connect(self.load_tracking)
        load_row.addWidget(load)
        self.file_label = QLabel("Choose X/Y positions or a non-negative speed column.")
        load_row.addWidget(self.file_label, 1)
        layout.addLayout(load_row)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        self.input_mode = QComboBox()
        self.input_mode.addItems(["Position X/Y", "Speed column"])
        self.x = QComboBox()
        self.y = QComboBox()
        self.speed_column = QComboBox()
        self.confidence = QComboBox()
        self.confidence.addItem("None", None)
        self.threshold = self.number(0, 1e6, 20)
        self.smoothing = self.number(0, 10, .2, suffix=" s")
        self.max_gap = self.number(1, 10000, 100, decimals=0, suffix=" ms")
        self.min_confidence = self.number(0, 1, .9)
        self.units = QComboBox()
        self.units.addItems(["px", "cm", "mm"])
        self.units.setToolTip("Units already used by the input coordinates or speed. This selector does not calibrate or rescale data.")
        self.signal = QComboBox()
        for kind in self.viewer.caiman.trace_types:
            self.signal.addItem(self.viewer.caiman.TRACE_LABELS[kind], kind)
        self.signal.setCurrentIndex(max(0, self.signal.findData("F_dff")))
        self.quality = QComboBox()
        self.quality.addItem("Accepted", "accepted")
        self.quality.addItem("All components", "all")
        self.quality.addItem("Rejected", "rejected")
        self.quality.setCurrentIndex(0 if self.viewer.caiman.accepted is not None else 1)
        self.max_lag = self.number(0, 10, 2, suffix=" s")
        fields = [
            ("Input", self.input_mode), ("X", self.x), ("Y", self.y), ("Speed", self.speed_column),
            ("Move ≥", self.threshold), ("Median window", self.smoothing),
            ("Max frame gap", self.max_gap), ("Confidence column", self.confidence),
            ("Signal", self.signal), ("Components", self.quality),
            ("Input units", self.units), ("Min confidence", self.min_confidence),
        ]
        for index, (label, field) in enumerate(fields):
            row, column = divmod(index, 4)
            grid.addWidget(QLabel(label), row, column * 2)
            grid.addWidget(field, row, column * 2 + 1)
            field.setMinimumWidth(110)
        layout.addLayout(grid)
        actions = QHBoxLayout()
        actions.addWidget(QLabel("Lag range ±"))
        actions.addWidget(self.max_lag)
        self.run_btn = QPushButton("Analyze")
        self.run_btn.setObjectName("analyzeButton")
        self.run_btn.clicked.connect(self.run_analysis)
        actions.addWidget(self.run_btn)
        self.export_btn = QPushButton("Export analysis")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self.export_analysis)
        actions.addWidget(self.export_btn)
        actions.addStretch()
        layout.addLayout(actions)
        self.status = QLabel("Load tracking, verify its units and movement threshold, then press Analyze. Results are descriptive; no significance tests are applied.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["ROI ID", "Quality", "Mean rest", "Mean moving", "Moving − rest", "Speed r", "Valid frames"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.setMinimumHeight(130)
        self.table.setMaximumHeight(210)
        self.table.itemSelectionChanged.connect(self.show_selected_cell)
        layout.addWidget(self.table)
        self.selected_status = QLabel("Select a cell to inspect its activity and behavioral coverage.")
        self.selected_status.setWordWrap(True)
        layout.addWidget(self.selected_status)
        self.tabs = QTabWidget()
        times = QWidget()
        time_layout = QVBoxLayout(times)
        time_layout.setContentsMargins(0, 0, 0, 0)
        self.activity_plot = pg.PlotWidget()
        self.speed_plot = pg.PlotWidget()
        self.activity_curve = self.activity_plot.plot([], [], connect="finite")
        self.speed_curve = self.speed_plot.plot([], [], connect="finite")
        self.activity_cursor = pg.InfiniteLine(angle=90)
        self.speed_cursor = pg.InfiniteLine(angle=90)
        self.speed_threshold = pg.InfiniteLine(angle=0, pen=pg.mkPen("#B54747", style=Qt.DashLine))
        self.activity_plot.addItem(self.activity_cursor)
        self.speed_plot.addItem(self.speed_cursor)
        self.speed_plot.addItem(self.speed_threshold)
        self.speed_plot.setXLink(self.activity_plot)
        for plot in (self.activity_plot, self.speed_plot):
            plot.setLabel("bottom", "Time", units="s")
            plot.scene().sigMouseClicked.connect(lambda event, p=plot: self.plot_clicked(event, p))
            time_layout.addWidget(plot, 1)
        self.tabs.addTab(times, "Time")
        self.scatter_plot = pg.PlotWidget()
        self.scatter = self.scatter_plot.plot([], [], pen=None, symbol="o", symbolSize=4,
                                              symbolPen=None, symbolBrush=pg.mkBrush(40, 125, 113, 100))
        self.tabs.addTab(self.scatter_plot, "Speed vs calcium")
        self.state_plot = pg.PlotWidget()
        self.state_plot.getAxis("bottom").setTicks([[(0, "Rest"), (1, "Moving")]])
        self.bars = pg.BarGraphItem(x=[], height=[], width=.55, brush="#287D71")
        self.state_plot.addItem(self.bars)
        self.tabs.addTab(self.state_plot, "Movement / rest")
        self.lag_plot = pg.PlotWidget()
        self.lag_curve = self.lag_plot.plot([], [], connect="finite")
        self.lag_plot.setLabel("bottom", "Calcium follows movement →", units="s")
        self.lag_plot.setLabel("left", "Pearson r")
        self.tabs.addTab(self.lag_plot, "Lag (descriptive)")
        layout.addWidget(self.tabs, 1)
        self.curves = (self.activity_curve, self.speed_curve, self.scatter, self.lag_curve)
        for widget in (self.input_mode, self.x, self.y, self.speed_column, self.confidence,
                       self.threshold, self.smoothing, self.max_gap, self.min_confidence,
                       self.units, self.signal, self.quality, self.max_lag):
            change = widget.currentIndexChanged if isinstance(widget, QComboBox) else widget.valueChanged
            change.connect(self.invalidate)
        self.input_mode.currentIndexChanged.connect(self.update_input_mode)
        self.units.currentIndexChanged.connect(self.update_units)
        self.update_input_mode()
        self.update_units()

    def update_input_mode(self):
        positions = self.input_mode.currentIndex() == 0
        self.x.setEnabled(positions)
        self.y.setEnabled(positions)
        self.speed_column.setEnabled(not positions)

    def update_units(self):
        self.threshold.setSuffix(f" {self.units.currentText()}/s")

    def apply_theme(self, day):
        background, card = ("#F2EEE5", "#FAF7F0") if day else ("#102131", "#14283A")
        text, border = ("#454D46", "#D2CCBF") if day else ("#EAF5FA", "#315067")
        accent = "#287D71" if day else "#12C4BE"
        icon_dir = Path(__file__).with_name("icons").as_posix()
        self.setStyleSheet(f"""
            QDialog {{ background: {background}; }}
            QLabel, QCheckBox {{ color: {text}; }}
            QLabel#analysisTitle {{ font-size: 22px; font-weight: 700; }}
            QComboBox, QDoubleSpinBox, QPushButton {{
                background: {card}; color: {text}; border: 1px solid {border};
                border-radius: 7px; min-height: 27px; padding: 2px 7px;
            }}
            QComboBox, QDoubleSpinBox {{ padding-right: 26px; }}
            QComboBox::drop-down {{
                subcontrol-origin: padding; subcontrol-position: top right;
                width: 22px; border: none; border-left: 1px solid {border};
            }}
            QComboBox::down-arrow {{ image: url("{icon_dir}/chevron-down.svg"); width: 9px; height: 6px; }}
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
                subcontrol-origin: padding; width: 19px; height: 15px;
                border: none; border-left: 1px solid {border};
            }}
            QDoubleSpinBox::up-button {{ subcontrol-position: top right; }}
            QDoubleSpinBox::down-button {{ subcontrol-position: bottom right; }}
            QDoubleSpinBox::up-arrow {{ image: url("{icon_dir}/chevron-up.svg"); width: 8px; height: 5px; }}
            QDoubleSpinBox::down-arrow {{ image: url("{icon_dir}/chevron-down.svg"); width: 8px; height: 5px; }}
            QPushButton:hover {{ border-color: {accent}; }}
            QPushButton#analyzeButton {{ background: #287D71; color: #FAF7F0; }}
            QPushButton:disabled {{ color: #96968B; }}
            QTableWidget {{ background: {card}; color: {text}; gridline-color: {border}; border: 1px solid {border}; }}
            QTableWidget::item:selected {{ background: #287D71; color: #FAF7F0; }}
            QHeaderView::section {{ background: {background}; color: {text}; padding: 5px; border: none; }}
            QTabWidget::pane {{ border: none; }}
            QTabBar::tab {{ background: {card}; color: {text}; padding: 7px 12px; margin-right: 4px; }}
            QTabBar::tab:selected {{ color: {accent}; }}
        """)
        for plot in (self.activity_plot, self.speed_plot, self.scatter_plot, self.state_plot, self.lag_plot):
            plot.setBackground(card)
            for axis_name in ("bottom", "left"):
                axis = plot.getAxis(axis_name)
                axis.setTextPen(pg.mkPen(text))
                axis.setPen(pg.mkPen(border))
                self.plot_label(plot, axis_name, axis.labelText, axis.labelUnits, color=text)
                # Recent pyqtgraph versions can recalculate a prefix from
                # setLabel even after auto-prefixing is disabled.
                if hasattr(axis, "setSIPrefixEnableRanges"):
                    axis.setSIPrefixEnableRanges(())
                axis.enableAutoSIPrefix(False)
        for curve in (self.activity_curve, self.speed_curve, self.lag_curve):
            curve.setPen(pg.mkPen(accent, width=1.4))
        for cursor in (self.activity_cursor, self.speed_cursor):
            cursor.setPen(pg.mkPen(text))

    def plot_label(self, plot, axis_name, text, units=None, color=None):
        axis = plot.getAxis(axis_name)
        options = {"color": color or ("#454D46" if self.viewer.day_mode else "#EAF5FA")}
        if hasattr(axis, "setSIPrefixEnableRanges"):
            options["siPrefixEnableRanges"] = ()
        axis.setLabel(text=text, units=units, **options)

    def invalidate(self, *_):
        self.generation += 1
        self.summary = self.context = self.behavior = None
        self.table.setRowCount(0)
        for curve in self.curves:
            curve.setData([], [])
        self.bars.setOpts(x=[], height=[])
        self.export_btn.setEnabled(False)
        self.status.setText("Settings or source data changed. Press Analyze to recalculate.")
        self.selected_status.setText("Select a cell after analysis. Results are descriptive; no significance tests are applied.")
        # A replaced CaImAn file may expose a different set of signals.
        if self.viewer.caiman is not None:
            available = [self.signal.itemData(i) for i in range(self.signal.count())]
            if available != self.viewer.caiman.trace_types:
                previous = self.signal.currentData()
                self.signal.blockSignals(True)
                self.signal.clear()
                for kind in self.viewer.caiman.trace_types:
                    self.signal.addItem(self.viewer.caiman.TRACE_LABELS[kind], kind)
                self.signal.setCurrentIndex(max(0, self.signal.findData(previous)))
                self.signal.blockSignals(False)

    def load_tracking(self):
        path, _ = QFileDialog.getOpenFileName(self, "Behavior tracking", "", "CSV (*.csv)")
        if path:
            self.load_tracking_path(path)

    def load_tracking_path(self, path):
        try:
            table, numeric = self.tracking_reader.load_tracking_table(path)
            if not numeric:
                raise ValueError("No numeric tracking columns found.")
            self.invalidate()
            self.tracking_reader.tracking_df = table
            self.numeric_data = numeric
            self.tracking_path = Path(path).resolve()
            for combo in (self.x, self.y, self.speed_column, self.confidence):
                combo.blockSignals(True)
                combo.clear()
                if combo is self.confidence:
                    combo.addItem("None", None)
                for name in numeric:
                    combo.addItem(name, name)
                combo.blockSignals(False)
            def choose(combo, suffixes):
                for name in numeric:
                    if any(name.lower() == suffix or name.lower().endswith("." + suffix)
                           or name.lower().endswith("_" + suffix) for suffix in suffixes):
                        combo.setCurrentIndex(combo.findData(name))
                        return
            choose(self.x, ("x",))
            choose(self.y, ("y",))
            choose(self.speed_column, ("speed", "speed_px_s", "velocity"))
            prefix = self.x.currentText().rsplit(".", 1)[0] if "." in self.x.currentText() else ""
            confidence = f"{prefix}.likelihood" if prefix else "likelihood"
            if confidence in numeric:
                self.confidence.setCurrentIndex(self.confidence.findData(confidence))
            self.file_label.setText(f"{self.tracking_path.name} · {len(table)} rows")
            self.status.setText("Tracking loaded. Verify X/Y (same body part), input units, confidence and movement threshold, then Analyze.")
        except Exception as exc:
            QMessageBox.warning(self, "Movement analysis", str(exc))

    def run_analysis(self):
        self.invalidate()
        self.run_btn.setEnabled(False)
        generation = self.generation
        progress = None
        try:
            v = self.viewer
            if not self.numeric_data or v.caiman is None or v.mini_t is None or v.camera_t is None:
                raise ValueError("Load CaImAn, both TTL CSV files and behavior tracking first.")
            n_video = v.video.count if v.video.cap is not None else None
            indices = self.tracking_reader.tracking_indices(n_video)
            count = n_video if n_video is not None else int(indices[-1]) + 1
            video_times = self.tracking_reader.build_video_times(count) / 1000
            source_times = video_times[indices]
            confidence = self.numeric_data.get(self.confidence.currentData())
            if self.input_mode.currentIndex() == 0 and self.x.currentData() == self.y.currentData():
                raise ValueError("Choose distinct X and Y coordinate columns for the same tracked body part.")
            arguments = {"speed": self.numeric_data[self.speed_column.currentData()]} if self.input_mode.currentIndex() else {
                "x": self.numeric_data[self.x.currentData()], "y": self.numeric_data[self.y.currentData()]}
            speed, segments = prepare_speed(source_times, indices, **arguments,
                confidence=confidence, min_confidence=self.min_confidence.value(),
                max_gap_s=self.max_gap.value()/1000, smoothing_s=self.smoothing.value())
            times = v.visible_timeline_times()[0].copy()/1000
            frames = v.mini_df.frame.to_numpy()[:len(times)].copy()
            aligned, segment_ids = align_speed(source_times, speed, segments, times, return_segments=True)
            ids = v.caiman.component_ids(self.quality.currentData()).copy()
            progress = QProgressDialog("Analyzing calcium and movement…", "Cancel", 0, len(ids), self)
            progress.setMinimumDuration(300)
            def advance(index, total):
                if index % 10 == 0:
                    progress.setValue(index)
                    QApplication.processEvents()
                if progress.wasCanceled() or self.generation != generation:
                    raise InterruptedError("Analysis cancelled or settings changed. Run Analyze again.")
            summary, weights = analyze_cells(v.caiman, self.signal.currentData(), ids, frames,
                times, aligned, self.threshold.value(), first_frame=v.calcium_first_frame.value(),
                max_gap_s=self.max_gap.value()/1000, progress=advance, segment_ids=segment_ids)
            if self.generation != generation:
                raise InterruptedError("Settings changed during analysis. Run Analyze again.")
            self.context = {"results": v.caiman, "signal": self.signal.currentData(), "frames": frames,
                "times": times, "source_times": source_times, "speed": speed, "segments": segments,
                "first_frame": v.calcium_first_frame.value(), "max_lag": self.max_lag.value()}
            self.summary = summary
            self.settings = {"tracking_csv": str(self.tracking_path), "caiman_hdf5": str(v.caiman.path),
                "camera_csv": str(v.camera_csv_path) if v.camera_csv_path else None,
                "mini2p_csv": str(v.mini_csv_path) if v.mini_csv_path else None,
                "video_mapping": v.mode.currentText(), "mp4_offset": v.offset.value(),
                "first_mini2p_frame": v.calcium_first_frame.value(), "signal": self.signal.currentData(),
                "component_filter": self.quality.currentData(), "input_mode": self.input_mode.currentText(),
                "x_column": self.x.currentData(), "y_column": self.y.currentData(),
                "speed_column": self.speed_column.currentData(), "units": self.units.currentText(),
                "movement_threshold": self.threshold.value(), "median_window_s": self.smoothing.value(),
                "confidence_column": self.confidence.currentData(), "min_confidence": self.min_confidence.value(),
                "max_frame_gap_ms": self.max_gap.value(), "lag_range_s": self.max_lag.value(),
                "trim_time_ms": float(v.camera_t[v.trim_idx]) if v.trim_idx is not None else None,
                "means": "Duration weighted over adjacent covered samples; no endpoint extrapolation.",
                "pearson": "Unweighted over paired finite frames; no p-values or significance labels.",
                "lag_convention": "Positive: calcium(t) versus speed(t-lag), calcium follows movement.",
                "tracking_gaps": "No interpolation across missing, rejected or skipped tracking frames.",
                "calibration": "Units describe the supplied values; no spatial rescaling is performed."}
            state = np.full(len(times), "unknown", dtype=object)
            valid = np.isfinite(aligned) & (weights > 0)
            state[valid & (aligned >= self.threshold.value())] = "moving"
            state[valid & (aligned < self.threshold.value())] = "rest"
            self.behavior = pd.DataFrame({"mini2p_frame": frames, "time_ms": times*1000,
                "speed": aligned, "state": state, "observed_duration_s": weights})
            self.table.setRowCount(len(summary))
            columns = ("roi_id_zero_based", "quality", "mean_rest", "mean_moving", "moving_minus_rest", "pearson_speed", "valid_frames")
            for row, record in summary.iterrows():
                for col, name in enumerate(columns):
                    value = record[name]
                    text = str(value) if name in ("quality", "roi_id_zero_based", "valid_frames") else f"{value:.4g}" if np.isfinite(value) else "—"
                    item = QTableWidgetItem(text)
                    item.setData(Qt.UserRole, int(record.roi_id_zero_based))
                    self.table.setItem(row, col, item)
            self.status.setText(f"{len(summary)} cells · movement {weights[valid & (aligned >= self.threshold.value())].sum():.2f} s · rest {weights[valid & (aligned < self.threshold.value())].sum():.2f} s · {len(times)-int(valid.sum())} frames excluded. Descriptive associations; no significance tests.")
            self.export_btn.setEnabled(True)
            self.table.selectRow(0)
        except InterruptedError as exc:
            self.invalidate()
            self.status.setText(str(exc))
        except Exception as exc:
            self.invalidate()
            QMessageBox.warning(self, "Movement analysis", str(exc))
        finally:
            if progress is not None:
                progress.close()
            self.run_btn.setEnabled(True)

    def selected_values(self):
        row = self.table.currentRow()
        if self.context is None or row < 0:
            return None, None
        component = int(self.table.item(row, 0).data(Qt.UserRole))
        c = self.context
        trace = c["results"].trace(component, c["signal"])
        values, _ = c["results"].mapped_trace(trace, c["frames"], c["first_frame"])
        return component, values

    def show_selected_cell(self):
        if self.context is None or self.table.currentRow() < 0:
            return
        try:
            component, values = self.selected_values()
            c = self.context
            speed = self.behavior.speed.to_numpy()
            self.activity_curve.setData(c["times"], values, connect="finite")
            self.speed_curve.setData(c["times"], speed, connect="finite")
            self.speed_threshold.setValue(self.settings["movement_threshold"])
            valid = np.isfinite(values) & np.isfinite(speed) & (self.behavior.observed_duration_s.to_numpy() > 0)
            self.scatter.setData(speed[valid], values[valid])
            record = self.summary.loc[self.summary.roi_id_zero_based == component].iloc[0]
            heights = np.array([record.mean_rest, record.mean_moving])
            self.bars.setOpts(x=np.arange(2)[np.isfinite(heights)], height=heights[np.isfinite(heights)])
            step = max(float(np.median(np.diff(c["times"]))), .02)
            steps = max(1, int(np.ceil(c["max_lag"]/step)))
            self.lags = np.linspace(-c["max_lag"], c["max_lag"], 2*steps+1) if c["max_lag"] else np.array([0.])
            self.correlations = lag_correlations(values, c["times"], c["source_times"], c["speed"], c["segments"], self.lags)
            self.lag_curve.setData(self.lags, self.correlations, connect="finite")
            label = c["results"].TRACE_LABELS[c["signal"]]
            self.plot_label(self.activity_plot, "left", label)
            self.plot_label(self.speed_plot, "left", f"Speed ({self.settings['units']}/s)")
            self.plot_label(self.scatter_plot, "bottom", f"Speed ({self.settings['units']}/s)")
            self.plot_label(self.scatter_plot, "left", label)
            self.plot_label(self.state_plot, "left", label + " · time-weighted mean")
            self.selected_status.setText(f"ROI {component} · paired rest {record.rest_duration_s:.2f} s / moving {record.moving_duration_s:.2f} s. Missing states and constant signals produce undefined values (—). Positive lag: calcium follows movement.")
            self.activity_plot.enableAutoRange()
            self.move_cursor(self.viewer.current_t)
            v = self.viewer
            index = v.calcium_component.findData(component)
            if index < 0:
                v.calcium_filter.setCurrentIndex(v.calcium_filter.findData("all"))
                index = v.calcium_component.findData(component)
            v.calcium_component.setCurrentIndex(index)
            v.calcium_signal.setCurrentIndex(v.calcium_signal.findData(c["signal"]))
        except Exception as exc:
            self.invalidate()
            QMessageBox.warning(self, "Movement analysis", str(exc))

    def move_cursor(self, time_ms):
        self.activity_cursor.setValue(time_ms/1000)
        self.speed_cursor.setValue(time_ms/1000)

    def plot_clicked(self, event, plot):
        if event.button() == Qt.LeftButton:
            view = plot.getViewBox()
            if view.sceneBoundingRect().contains(event.scenePos()):
                self.viewer.set_time(float(view.mapSceneToView(event.scenePos()).x())*1000)

    def export_analysis(self):
        if self.summary is None:
            return
        parent = QFileDialog.getExistingDirectory(self, "Folder for movement analysis")
        if not parent:
            return
        try:
            folder = Path(parent)/("movement_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
            folder.mkdir(exist_ok=False)
            self.summary.to_csv(folder/"per_cell_summary.csv", index=False)
            self.behavior.to_csv(folder/"aligned_movement.csv", index=False)
            component, values = self.selected_values()
            selected = self.behavior.copy()
            selected["roi_id_zero_based"] = component
            selected["signal"] = self.context["signal"]
            selected["calcium_value"] = values
            selected.to_csv(folder/f"roi_{component}_aligned.csv", index=False)
            pd.DataFrame({"lag_s": self.lags, "pearson_r": self.correlations}).to_csv(folder/f"roi_{component}_lag.csv", index=False)
            (folder/"analysis_settings.json").write_text(json.dumps(self.settings, indent=2) + "\n")
            QMessageBox.information(self, "Movement analysis exported", f"Created:\n{folder}")
        except Exception as exc:
            QMessageBox.warning(self, "Movement analysis", str(exc))
