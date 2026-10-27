"""Compact calcium analysis controls; CaImAn runs in an isolated worker."""
from dataclasses import asdict
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

import numpy as np
from PySide6.QtCore import QLocale, QProcess, QProcessEnvironment, QTimer, Qt
from PySide6.QtGui import QDoubleValidator, QIcon
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox,
    QToolButton, QVBoxLayout, QWidget, QScrollArea,
)

from calcium_pipeline import PipelineSettings, inspect_tiff, inspect_sources, write_manifest


class CalciumProcessingDialog(QDialog):
    def __init__(self, viewer):
        super().__init__(viewer)
        self.viewer = viewer
        self.sources = []
        self.viewer_source = None
        self.output = self.run_root = self.result = None
        self.completed_results, self.jobs = [], []
        self.job_index = 0
        self.cancelled = False
        self.config_path = None
        self.log_text = ""
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.worker_finished)
        self.process.errorOccurred.connect(self.process_error)
        self.cancel_timer = QTimer(self)
        self.cancel_timer.setSingleShot(True)
        self.cancel_timer.timeout.connect(self.kill_if_cancelled)
        self.layout_timer = QTimer(self)
        self.layout_timer.setSingleShot(True)
        self.layout_timer.timeout.connect(self.fit_dialog)
        self.setWindowTitle("MINISYNC · Calcium analysis")
        self.setObjectName("calciumAnalysisDialog")
        self.setMinimumWidth(480)
        self.resize(520, 250)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)
        self.inputs = QWidget()
        inputs = QVBoxLayout(self.inputs)
        inputs.setContentsMargins(0, 0, 0, 0)
        inputs.setSpacing(14)
        files = QHBoxLayout()
        self.add_button = QPushButton("Add TIFF")
        self.add_button.clicked.connect(self.add_sources)
        self.remove_button = QToolButton()
        self.remove_button.setIcon(QIcon(str(Path(__file__).with_name("icons") / "trash.svg")))
        self.remove_button.setFixedSize(34, 34)
        self.remove_button.setToolTip("Remove TIFFs from this analysis")
        self.remove_button.setAccessibleName("Remove TIFFs")
        self.remove_button.clicked.connect(self.remove_sources)
        self.file_name = QLabel("No TIFF selected")
        self.file_name.setMinimumWidth(0)
        files.addWidget(self.add_button)
        files.addWidget(self.remove_button)
        files.addWidget(self.file_name, 1)
        inputs.addLayout(files)
        basic = QFormLayout()
        basic.setVerticalSpacing(12)
        self.frame_rate = QComboBox()
        self.frame_rate.setEditable(True)
        self.frame_rate.addItems(["5", "10", "15", "20", "30", "40", "50", "60"])
        self.frame_rate.setCurrentIndex(-1)
        self.frame_rate.lineEdit().setPlaceholderText("Hz")
        validator = QDoubleValidator(.001, 1000, 6, self.frame_rate)
        validator.setLocale(QLocale.c())
        self.frame_rate.lineEdit().setValidator(validator)
        self.frame_rate.setToolTip("Acquisition frame rate per channel, in Hz; not neuronal firing rate.")
        self.channels = QComboBox()
        self.channels.addItem("1 channel", 1)
        self.channels.addItem("2 channels", 2)
        self.channels.currentIndexChanged.connect(self.update_channels)
        self.channel = QComboBox()
        channel_row = QHBoxLayout()
        channel_row.addWidget(self.channels)
        channel_row.addWidget(self.channel)
        self.planes = QComboBox()
        self.planes.addItem("1 plane", 1)
        for planes in range(2, 9):
            self.planes.addItem(f"{planes} planes — coming later", planes)
            item = self.planes.model().item(self.planes.count() - 1)
            item.setEnabled(False)
            item.setToolTip("The current processing engine supports a single imaging plane.")
        basic.addRow("Frame rate (Hz)", self.frame_rate)
        basic.addRow("Channels", channel_row)
        basic.addRow("Planes", self.planes)
        inputs.addLayout(basic)
        self.more_button = QPushButton("More options")
        self.more_button.setCheckable(True)
        self.more_button.toggled.connect(self.toggle_options)
        inputs.addWidget(self.more_button, alignment=Qt.AlignLeft)
        self.advanced = QWidget()
        self.advanced.setObjectName("analysisAdvanced")
        advanced = QFormLayout(self.advanced)
        advanced.setContentsMargins(0, 0, 0, 0)
        self.motion_mode = QComboBox()
        self.motion_mode.addItems(["Rigid", "Piecewise rigid"])
        self.max_shift = self.integer(1, 200, 6)
        self.patch_stride = self.integer(4, 512, 48)
        self.patch_overlap = self.integer(1, 256, 24)
        self.first_frame = self.integer(1, 1000000000, 1)
        self.decay_time = self.decimal(.01, 30, .4)
        self.neuron_size = self.integer(1, 100, 4)
        self.components = self.integer(1, 100, 4)
        self.cnmf_patch = self.integer(4, 512, 25)
        self.snr = self.decimal(.01, 100, 2)
        self.rval = self.decimal(-1, 1, .85)
        for label, field in (
            ("Motion correction", self.motion_mode), ("Maximum shift (px)", self.max_shift),
            ("Motion patch stride (px)", self.patch_stride), ("Motion patch overlap (px)", self.patch_overlap),
            ("First Mini2P frame", self.first_frame), ("Calcium decay time (s)", self.decay_time),
            ("Neuron half-size (px)", self.neuron_size), ("Initial components / patch", self.components),
            ("CNMF patch half-size (px)", self.cnmf_patch), ("Minimum SNR", self.snr),
            ("Spatial correlation threshold", self.rval),
        ):
            advanced.addRow(label, field)
        self.advanced.hide()
        self.advanced_scroll = QScrollArea()
        self.advanced_scroll.setWidgetResizable(True)
        self.advanced_scroll.setFrameShape(QFrame.NoFrame)
        self.advanced_scroll.setWidget(self.advanced)
        self.advanced_scroll.setFixedHeight(300)
        self.advanced_scroll.hide()
        inputs.addWidget(self.advanced_scroll)
        layout.addWidget(self.inputs)
        self.result_row = QWidget()
        results = QHBoxLayout(self.result_row)
        results.setContentsMargins(0, 0, 0, 0)
        results.addWidget(QLabel("View channel"))
        self.result_channel = QComboBox()
        self.result_channel.currentIndexChanged.connect(self.select_result)
        results.addWidget(self.result_channel, 1)
        self.result_row.hide()
        layout.addWidget(self.result_row)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.hide()
        layout.addWidget(self.status)
        self.run_button = QPushButton("Run analysis")
        self.run_button.setObjectName("analysisRun")
        self.run_button.clicked.connect(self.run_or_cancel)
        layout.addWidget(self.run_button)
        self.update_channels()
        self.remove_button.setEnabled(False)
        self.run_button.setEnabled(False)
        viewer.theme_changed.connect(self.apply_theme)
        self.apply_theme(viewer.day_mode)
        self.sync_source_from_viewer()

    def apply_theme(self, day):
        background, field, text, border = (("#F2EEE4", "#F8F5EE", "#454D46", "#D1CCBE") if day
                                          else ("#102332", "#183146", "#EEF7FB", "#2C4C62"))
        icons = Path(__file__).with_name("icons").as_posix()
        self.setStyleSheet(f'''
            QDialog#calciumAnalysisDialog, QWidget#analysisAdvanced {{ background: {background}; }}
            QLabel {{ color: {text}; }}
            QPushButton {{ background: {field}; color: {text}; border: 1px solid {border}; }}
            QComboBox, QSpinBox, QDoubleSpinBox {{
                background: {field}; color: {text}; border: 1px solid {border};
                border-radius: 8px; min-height: 30px; max-height: 30px; padding: 0 28px 0 8px;
            }}
            QComboBox::drop-down {{ width: 26px; border: none; }}
            QComboBox::down-arrow {{ image: url("{icons}/chevron-down.svg"); width: 10px; height: 6px; }}
            QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: padding; subcontrol-position: top right; width: 22px; height: 15px; border: none; }}
            QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: padding; subcontrol-position: bottom right; width: 22px; height: 15px; border: none; }}
            QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{icons}/chevron-up.svg"); width: 10px; height: 6px; }}
            QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{icons}/chevron-down.svg"); width: 10px; height: 6px; }}
            QComboBox QAbstractItemView {{ background: {field}; color: {text}; selection-background-color: #287D71; selection-color: white; }}
            QToolButton {{ background: {field}; border: 1px solid {border}; border-radius: 8px; padding: 8px; }}
            QToolButton:hover {{ border-color: #287D71; }}
            QPushButton#analysisRun {{ background: #287D71; color: white; border: 1px solid #287D71; }}
            QPushButton#analysisRun:disabled {{ background: {field}; color: #92998F; border-color: {border}; }}
            QScrollArea {{ background: transparent; border: none; }}
        ''')
        self.layout_timer.start(0)

    @staticmethod
    def default_engine_python():
        override = os.environ.get("MINISYNC_CAIMAN_PYTHON")
        if override:
            return str(Path(override).expanduser())
        if importlib.util.find_spec("caiman") is not None:
            return sys.executable
        suffix = Path("python.exe") if sys.platform == "win32" else Path("bin/python")
        for name in ("caiman", "minisync-caiman"):
            candidate = Path(sys.prefix).parent / name / suffix
            if candidate.is_file():
                return str(candidate)
        raise RuntimeError("CaImAn is unavailable. Install the analysis environment before running.")

    @staticmethod
    def integer(low, high, value):
        field = QSpinBox()
        field.setRange(low, high)
        field.setValue(value)
        return field

    @staticmethod
    def decimal(low, high, value):
        field = QDoubleSpinBox()
        field.setRange(low, high)
        field.setValue(value)
        return field

    def toggle_options(self, expanded):
        self.advanced.setVisible(expanded)
        self.advanced_scroll.setVisible(expanded)
        self.more_button.setText("Fewer options" if expanded else "More options")
        self.layout().activate()
        self.adjustSize()
        self.layout_timer.start(0)

    def fit_dialog(self):
        self.layout().activate()
        self.resize(self.width(), self.sizeHint().height())

    def sync_source_from_viewer(self):
        if self.is_running() or self.viewer.tiff.tif is None:
            return
        path = str(Path(self.viewer.tiff.tif.filehandle.path).resolve())
        corrected = {entry["outputs"]["corrected_tiff"] for entry in self.completed_results}
        if path == self.viewer_source or path in corrected:
            return
        try:
            inspect_tiff(path)
            self.sources = [path]
            self.viewer_source = path
            self.first_frame.setValue(self.viewer.tiff_first_frame)
            self.refresh_sources()
        except Exception as exc:
            self.set_status(str(exc))

    def update_channels(self):
        count = self.channels.currentData() or 1
        previous = self.channel.currentData()
        self.channel.clear()
        for index in range(count):
            self.channel.addItem(f"Channel {index + 1}", index)
        if count > 1:
            self.channel.addItem("Both channels" if count == 2 else "All channels", -1)
        self.channel.setCurrentIndex(self.channel.findData(previous) if previous in range(count) else self.channel.count() - 1)
        self.channel.setVisible(count > 1)

    def add_sources(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Add TIFF", "", "TIFF (*.tif *.tiff)")
        if not paths:
            return
        try:
            for path in paths:
                inspect_tiff(path)
            self.sources.extend(str(Path(path).resolve()) for path in paths if str(Path(path).resolve()) not in self.sources)
            self.refresh_sources()
        except Exception as exc:
            QMessageBox.warning(self, "TIFF", str(exc))

    def remove_sources(self):
        self.sources = []
        self.refresh_sources()

    def refresh_sources(self):
        self.remove_button.setEnabled(bool(self.sources))
        self.file_name.setText(Path(self.sources[0]).name if len(self.sources) == 1 else f"{len(self.sources)} TIFFs" if self.sources else "No TIFF selected")
        self.file_name.setToolTip("\n".join(self.sources))
        self.run_button.setEnabled(bool(self.sources))
        self.channels.setEnabled(True)
        if not self.sources:
            return
        info = inspect_tiff(self.sources[0])
        ids = info["channel_ids"]
        count = len(ids) if ids else info["axis_channels"]
        if count:
            if self.channels.findData(count) < 0:
                self.channels.addItem(f"{count} channels", count)
            self.channels.setCurrentIndex(self.channels.findData(count))
            self.channels.setEnabled(False)
        self.update_channels()
        if ids:
            for index, channel_id in enumerate(ids):
                self.channel.setItemText(index, f"Channel {channel_id}")
        rate = info["frame_rate"]
        times = self.viewer.mini_t
        if rate is None and times is not None and len(times) >= 2:
            positive = np.diff(times)
            positive = positive[np.isfinite(positive) & (positive > 0)]
            if len(positive):
                rate = 1000 / float(np.median(positive))
        self.frame_rate.setCurrentText(f"{rate:.6g}" if rate else "")

    def settings(self, output, channel_index=None):
        try:
            rate = float(self.frame_rate.currentText().replace(",", "."))
        except ValueError as exc:
            raise ValueError("Enter the acquisition frame rate in Hz.") from exc
        if self.planes.currentData() != 1:
            raise ValueError("Only single-plane recordings are supported by the current engine.")
        selected = self.channel.currentData() if channel_index is None else channel_index
        return PipelineSettings(sources=list(self.sources), output=str(output), frame_rate=rate,
            channels=self.channels.currentData(), channel_index=0 if selected == -1 else selected,
            single_plane_confirmed=True, first_mini_frame=self.first_frame.value(),
            pw_rigid=self.motion_mode.currentIndex() == 1, max_shift=self.max_shift.value(),
            patch_stride=self.patch_stride.value(), patch_overlap=self.patch_overlap.value(),
            decay_time=self.decay_time.value(), neuron_half_size=self.neuron_size.value(),
            components_per_patch=self.components.value(), cnmf_patch_half_size=self.cnmf_patch.value(),
            min_snr=self.snr.value(), rval_thr=self.rval.value())

    def set_status(self, text):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def run_or_cancel(self):
        self.cancel() if self.is_running() else self.start()

    def start(self):
        try:
            if self.is_running():
                return
            python = Path(self.default_engine_python())
            if not python.is_file():
                raise ValueError("The CaImAn analysis environment is unavailable.")
            settings = self.settings("unused")
            inspect_sources(settings)
            selected = self.channel.currentData()
            indices = list(range(settings.channels)) if selected == -1 else [selected]
            parent = Path(self.sources[0]).parent / "minisync_results"
            parent.mkdir(exist_ok=True)
            self.run_root = parent / ("calcium_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
            if len(indices) > 1:
                self.run_root.mkdir(exist_ok=False)
            self.jobs = [self.settings(self.run_root / f"channel_{index + 1}" if len(indices) > 1 else self.run_root, index) for index in indices]
            self.job_index = 0
            self.completed_results = []
            self.result = None
            self.result_row.hide()
            self.result_channel.clear()
            self.cancelled = False
            self.log_text = ""
            self.inputs.setEnabled(False)
            self.run_button.setText("Cancel analysis")
            self.run_button.setEnabled(True)
            self.launch_job(str(python))
        except Exception as exc:
            self.reset_controls()
            self.set_status(str(exc))

    def launch_job(self, python):
        settings = self.jobs[self.job_index]
        self.output = Path(settings.output)
        self.clear_config()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", prefix="minisync_", delete=False) as handle:
            json.dump(asdict(settings), handle)
            self.config_path = Path(handle.name)
        env = QProcessEnvironment.systemEnvironment()
        for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
            env.insert(name, "1")
        env.insert("MPLBACKEND", "Agg")
        self.process.setProcessEnvironment(env)
        self.process.setWorkingDirectory(str(Path(__file__).parent))
        self.set_status("Running analysis…" if len(self.jobs) == 1 else f"Running analysis · channel {self.job_index + 1} of {len(self.jobs)}…")
        self.process.start(python, ["-u", str(Path(__file__).with_name("calcium_pipeline.py")), "--config", str(self.config_path)])

    def is_running(self):
        return self.process.state() != QProcess.NotRunning

    def read_output(self):
        if not self.process.isOpen():
            return
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self.log_text = (self.log_text + text)[-12000:]
        if self.output and self.output.exists():
            with (self.output / "processing.log").open("a", encoding="utf-8") as handle:
                handle.write(text)

    def process_error(self, error):
        if error == QProcess.FailedToStart:
            self.reset_controls()
            self.set_status("Could not start the calcium analysis engine.")
            self.write_batch_status("failed")

    def clear_config(self):
        if self.config_path:
            self.config_path.unlink(missing_ok=True)
            self.config_path = None

    def reset_controls(self):
        self.cancel_timer.stop()
        self.inputs.setEnabled(True)
        self.run_button.setText("Run analysis")
        self.run_button.setEnabled(bool(self.sources))
        self.clear_config()

    def write_batch_status(self, status):
        if len(self.jobs) > 1 and self.run_root and self.run_root.exists():
            write_manifest(self.run_root / "batch.json", {"status": status,
                "jobs": [asdict(job) for job in self.jobs],
                "completed_results": [entry["outputs"]["results"] for entry in self.completed_results]})

    def worker_finished(self, exit_code, exit_status):
        self.read_output()
        self.cancel_timer.stop()
        self.clear_config()
        manifest_path = self.output / "processing.json" if self.output else None
        try:
            if self.cancelled:
                if manifest_path and manifest_path.exists():
                    data = json.loads(manifest_path.read_text())
                    data["status"] = "cancelled"
                    write_manifest(manifest_path, data)
                self.write_batch_status("cancelled")
                self.reset_controls()
                self.set_status("Analysis cancelled.")
                return
            if exit_code != 0 or exit_status != QProcess.NormalExit:
                detail = ""
                if manifest_path and manifest_path.exists():
                    detail = json.loads(manifest_path.read_text()).get("error", "")
                raise RuntimeError("Analysis failed." + (f" {detail}" if detail else " Check processing.log in the results folder."))
            data = json.loads(manifest_path.read_text())
            if data.get("status") != "complete":
                raise RuntimeError("Analysis did not produce a complete result.")
            self.completed_results.append(data)
            self.job_index += 1
            if self.job_index < len(self.jobs):
                self.write_batch_status("running")
                self.launch_job(self.process.program())
                return
            self.write_batch_status("complete")
            self.reset_controls()
            self.result_channel.blockSignals(True)
            self.result_channel.clear()
            for number, result in enumerate(self.completed_results):
                index = result["settings"].get("channel_index", number)
                ids = result.get("sources", [{}])[0].get("channel_ids")
                channel_id = ids[index] if ids else index + 1
                self.result_channel.addItem(f"Channel {channel_id}", number)
            self.result_channel.blockSignals(False)
            self.result_row.setVisible(len(self.completed_results) > 1)
            components = sum(result["components"] for result in self.completed_results)
            self.set_status(f"Analysis complete · {components} candidate components.")
            self.status.setToolTip(f"Results saved in {self.run_root or self.output}")
            self.result = self.completed_results[0]
            try:
                self.viewer.show_processing_results(self.completed_results)
            except Exception as exc:
                self.set_status(f"Analysis completed, but results could not be displayed: {exc}")
                return
            self.close()
        except Exception as exc:
            self.result = None
            self.result_row.hide()
            self.write_batch_status("failed")
            self.reset_controls()
            self.set_status(str(exc))

    def select_result(self, index):
        if not 0 <= index < len(self.completed_results):
            return
        self.result = self.completed_results[index]
        try:
            self.viewer.open_processing_result(self.result)
        except Exception as exc:
            self.set_status(f"Could not open the analysis result: {exc}")

    def cancel(self):
        if not self.is_running():
            return
        self.cancelled = True
        self.run_button.setEnabled(False)
        self.set_status("Cancelling analysis…")
        self.process.terminate()
        self.cancel_timer.start(3000)

    def kill_if_cancelled(self):
        if self.cancelled and self.is_running():
            self.process.kill()

    def closeEvent(self, event):
        if self.is_running():
            self.set_status("Cancel the analysis before closing this window.")
            event.ignore()
            return
        event.accept()
