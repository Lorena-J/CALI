"""Main CALI window: coordinates sources, timeline and calcium browsing."""
import sys
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal, QSize, QPoint, QEvent
from PySide6.QtGui import QIcon, QPainterPath, QPalette
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPushButton, QSpinBox, QSplitter,
    QVBoxLayout, QWidget, QToolTip, QProgressDialog, QSizePolicy,
    QTabWidget, QCheckBox, QSlider, QScrollArea,
)

from .caiman_results import CaImAnResults
from .image_widgets import ImagePanel
from .movement_dialog import MovementAnalysisDialog
from .readers import VideoReader, TiffReader
from .theme import accent_palette, app_stylesheet, application_palette
from .theme_toggle import LandscapeThemeButton, RadialThemeReveal
from .timing import load_csv, median_period, virtual_camera_indices, fill_camera_timestamps
from .tracking_dialog import TrackingAlignmentDialog
from .video_exports import write_video_prefix, write_export_metadata

# Layout sizes in pixels. Change them here instead of in the code below.
SIDEBAR_WIDTH = 350
VIEWER_GAP = 14              # space between the Behavior camera and Mini2P viewers
WORKSPACE_SPACING = 13      # space between the viewers and the Timeline
TIMELINE_MIN_HEIGHT = 250
TIMELINE_CHROME_HEIGHT = 110  # tab bar, title and margins around a Timeline page


def frame_tick_symbol():
    """Vertical line one symbol unit tall, centred on the point."""
    path = QPainterPath()
    path.moveTo(0, -0.5)
    path.lineTo(0, 0.5)
    return path


FRAME_TICK_SYMBOL = frame_tick_symbol()
FRAME_TICK_HEIGHT = 14  # px; rows are one y unit (~70 px) apart, so ticks stay short
FRAME_TICK_WIDTH = 1.4  # px


class TimelineCursor(pg.InfiniteLine):
    """Vertical plot cursor with a wider mouse target and hover feedback."""

    GRAB_PX = 6
    WIDTH = 1.4
    HOVER_WIDTH = 3.5

    def __init__(self, color="#F0F7FC"):
        super().__init__(angle=90, movable=True)
        self.setCursor(Qt.SizeHorCursor)
        self.set_color(color)

    def set_color(self, color):
        self.setPen(pg.mkPen(color, width=self.WIDTH))
        self.setHoverPen(pg.mkPen(color, width=self.HOVER_WIDTH))

    def _computeBoundingRect(self):
        markers = self._maxMarkerSize
        self._maxMarkerSize = markers + self.GRAB_PX
        try:
            return super()._computeBoundingRect()
        finally:
            self._maxMarkerSize = markers

    def setMouseHover(self, hover):
        if self.moving and not hover:
            return
        super().setMouseHover(hover)

    def mouseDragEvent(self, ev):
        super().mouseDragEvent(ev)
        if ev.isStart() and self.moving:
            self.setMouseHover(True)


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
        self.default_palette = QPalette(QApplication.palette())
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
        self._alignment_pending = False
        self.video = VideoReader()
        self.tiff = TiffReader()
        self.tiff_first_frame = 1
        self.hover_pos = None
        self.hover_timer = QTimer(self)
        self.hover_timer.setSingleShot(True)
        self.hover_timer.setInterval(500)
        self.hover_timer.timeout.connect(self.show_hover)
        self.build_ui()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "viewer_splitter"):
            self.schedule_alignment()

    def schedule_alignment(self):
        """Queue one alignment, cancelled automatically if this window is deleted."""
        if self._alignment_pending:
            return
        self._alignment_pending = True
        QTimer.singleShot(0, self, self.align_workspace_panels)

    def align_workspace_panels(self):
        self._alignment_pending = False
        root = self.centralWidget()
        root.layout().activate()
        video_top = self.viewer_splitter.mapTo(root, QPoint()).y()
        navigate_top = self.navigate_card.mapTo(root, QPoint()).y()
        navigate_top += self.sidebar_scroll.verticalScrollBar().value()
        spacing = WORKSPACE_SPACING
        available_bottom = root.height() - root.layout().contentsMargins().bottom()
        timeline_minimum = max(TIMELINE_MIN_HEIGHT, self.timeline_tabs.currentWidget().minimumSizeHint().height() + TIMELINE_CHROME_HEIGHT)
        maximum = available_bottom - video_top - spacing - timeline_minimum
        desired = navigate_top - video_top - spacing
        minimum = self.viewer_splitter.minimumSizeHint().height()
        height = max(minimum, min(desired, maximum))
        if self.viewer_splitter.height() != height:
            self.viewer_splitter.setFixedHeight(height)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.KeyPress and hasattr(self, "sidebar_scroll"):
            focus = QApplication.focusWidget()
            widget = focus
            in_sidebar = False
            while widget is not None:
                if widget is self.sidebar_scroll:
                    in_sidebar = True
                    break
                widget = widget.parentWidget()
            if in_sidebar:
                actions = {
                    Qt.Key_Left: lambda: self.step_mini(-1),
                    Qt.Key_Right: lambda: self.step_mini(1),
                    Qt.Key_PageUp: lambda: self.jump_gap(-1),
                    Qt.Key_PageDown: lambda: self.jump_gap(1),
                }
                action = actions.get(event.key())
                if action is not None:
                    action()
                    return True
        if (watched is getattr(self, "navigate_card", None)
                and event.type() in (QEvent.Move, QEvent.Resize)
                and hasattr(self, "timeline_card")):
            self.schedule_alignment()
        return super().eventFilter(watched, event)

    def sidebar_tabs(self, object_name, tabs, make_button):
        tab_widget = QTabWidget()
        tab_widget.setObjectName(object_name)
        tab_widget.setProperty("sidebarTabs", True)
        tab_widget.setUsesScrollButtons(False)
        tab_widget.tabBar().setCursor(Qt.PointingHandCursor)
        tab_widget.tabBar().setElideMode(Qt.ElideNone)
        for title, entries in tabs:
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(10, 14, 10, 10)
            page_layout.setSpacing(7)
            for entry in entries:
                page_layout.addWidget(make_button(entry))
            page_layout.addStretch()
            tab_widget.addTab(page, title)
        return tab_widget

    def build_ui(self):
        self.setStyleSheet(self.app_stylesheet())

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)

        outer = QHBoxLayout(root)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(VIEWER_GAP)

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

        self.brand_logo = QSvgWidget()
        self.brand_logo.setObjectName("brandLogo")
        self.brand_logo.setFixedSize(300, 81)
        self.brand_logo.setAccessibleName("CALI — Calcium Linked Behavior explorer")
        brand_row.addStretch()
        brand_row.addWidget(self.brand_logo)
        brand_row.addStretch()
        side.addLayout(brand_row)

        # Files -----------------------------------------------------
        src_card = self.card("sideCard")
        src_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        src_lay = QVBoxLayout(src_card)
        src_lay.setContentsMargins(13, 12, 13, 12)
        src_lay.setSpacing(9)

        self.source_buttons = {}
        file_tabs = (
            ("Load Files", (
                ("Camera CSV", "Load behavior timestamps", self.load_camera),
                ("Mini2P CSV", "Load Mini2P timestamps", self.load_mini),
                ("Behavior MP4", "Behavior MP4", self.load_video),
                ("ScanImage TIFF", "ScanImage TIFF", self.load_tiff),
            )),
            ("Load Processed Data", (("CaImAn HDF5", "CaImAn HDF5", self.load_caiman),)),
        )
        def make_source_button(entry):
            key, label, callback = entry
            button = QPushButton(label)
            button.setProperty("variant", "source")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(callback)
            self.source_buttons[key] = button
            return button
        self.file_tabs = self.sidebar_tabs("fileTabs", file_tabs, make_source_button)
        src_lay.addWidget(self.file_tabs)

        analysis_tabs = (
            ("Tracking", (
                ("align_tracking_btn", "Align tracking", "camera", self.open_tracking_alignment),
            )),
            ("Analysis", (
                ("movement_btn", "Movement analysis", "mini", self.open_movement_analysis),
                ("processing_button", "Calcium analysis", "gap", self.open_calcium_processing),
            )),
        )
        def make_analysis_button(entry):
            attr, label, role, callback = entry
            button = QPushButton(label)
            button.setProperty("variant", "mainGhost")
            button.setProperty("accentRole", role)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(callback)
            setattr(self, attr, button)
            return button
        self.analysis_tabs = self.sidebar_tabs("analysisTabs", analysis_tabs, make_analysis_button)
        src_lay.addWidget(self.analysis_tabs)
        side.addWidget(src_card)

        # Navigate --------------------------------------------------
        controls_card = self.card("sideCard")
        self.navigate_card = controls_card
        controls_card.installEventFilter(self)
        controls_card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        controls_lay = QVBoxLayout(controls_card)
        controls_lay.setContentsMargins(13, 12, 13, 12)
        controls_lay.setSpacing(10)

        controls_title = QLabel("Navigate")
        self.navigate_title = controls_title
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

        self.sidebar_scroll = QScrollArea()
        self.sidebar_scroll.setObjectName("sidebarScroll")
        self.sidebar_scroll.setFrameShape(QFrame.NoFrame)
        self.sidebar_scroll.setWidgetResizable(True)
        self.sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sidebar_scroll.setFixedWidth(SIDEBAR_WIDTH)
        self.sidebar_scroll.setStyleSheet("QScrollArea#sidebarScroll { background: transparent; }")
        self.sidebar_scroll.setWidget(sidebar)
        outer.addWidget(self.sidebar_scroll)
        QApplication.instance().installEventFilter(self)

        # ----------------------------------------------------------
        # Main workspace
        # ----------------------------------------------------------
        main = QVBoxLayout()
        main.setSpacing(WORKSPACE_SPACING)

        self.theme_btn = LandscapeThemeButton()
        self.theme_btn.clicked.connect(lambda: self.set_day_mode(not self.day_mode))

        split = QSplitter(Qt.Horizontal)
        self.viewer_splitter = split
        split.setObjectName("viewerSplitter")
        split.setHandleWidth(VIEWER_GAP)
        accents = self.accent_palette()
        self.cam_panel = ImagePanel("Behavior camera", accents["camera"], croppable=True)
        self.cam_panel.cropChanged.connect(self.set_spatial_crop)
        self.cam_panel.exportCropRequested.connect(self.export_spatial_crop)
        self.mini_panel = ImagePanel("Mini2P", accents["mini"])
        self.mini_panel.add_header_widget(self.theme_btn)
        for panel in (self.cam_panel, self.mini_panel):
            split.addWidget(panel.container)
        split.setSizes([720, 720])
        main.addWidget(split, 1)

        timeline_card = self.card("timelineCard")
        self.timeline_card = timeline_card
        timeline_card.setMinimumHeight(TIMELINE_MIN_HEIGHT)
        timeline_lay = QVBoxLayout(timeline_card)
        timeline_lay.setContentsMargins(15, 13, 15, 12)
        timeline_lay.setSpacing(8)

        tl_top = QHBoxLayout()
        tl_title = QLabel("Timeline")
        tl_title.setObjectName("mainSectionTitle")
        tl_top.addWidget(tl_title)
        tl_top.addStretch()
        timeline_lay.addLayout(tl_top)

        self.plot = pg.PlotWidget()
        self.plot.setObjectName("timelinePlot")
        self.plot.setMinimumHeight(100)
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

        # One short vertical tick per frame, centred on its series row. Symbol
        # sizes are in screen pixels, so ticks keep the same height at any zoom.
        self.cam_pts = pg.ScatterPlotItem(
            size=FRAME_TICK_HEIGHT,
            symbol=FRAME_TICK_SYMBOL,
            pen=pg.mkPen(23, 185, 220, 225, width=FRAME_TICK_WIDTH),
            brush=None,
        )
        self.mini_pts = pg.ScatterPlotItem(
            size=FRAME_TICK_HEIGHT,
            symbol=FRAME_TICK_SYMBOL,
            pen=pg.mkPen(18, 196, 190, 235, width=FRAME_TICK_WIDTH),
            brush=None,
        )
        self.gap_pts = pg.ScatterPlotItem(
            size=10,
            symbol="x",
            pen=pg.mkPen(255, 107, 107, width=1.8),
        )
        self.plot.addItem(self.cam_pts)
        self.plot.addItem(self.mini_pts)
        self.plot.addItem(self.gap_pts)

        self.cursor_line = TimelineCursor()
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
        self.timeline_tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.timeline_tabs.currentChanged.connect(lambda _: self.schedule_alignment())
        self.timeline_tabs.addTab(self.plot, "Timing")
        self.build_calcium_tab()
        self.timeline_tabs.currentChanged.connect(self.calcium_tab_changed)
        timeline_lay.addWidget(self.timeline_tabs, 1)

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

        main.addWidget(timeline_card, 1)
        outer.addLayout(main, 1)
        self.schedule_alignment()
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
        self.calcium_cursor = TimelineCursor()
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
        from .processing_dialog import CalciumProcessingDialog
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
        self.calcium_status.setVisible(True)
        self.calcium_movie_mode = self.processing_manifest is not None or self.mini_t is None
        self.calcium_movie_controls.setVisible(self.calcium_movie_mode)
        prefix = ""
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
            notes = ""
            ttl_covered = np.isfinite(self.calcium_sample_times())
            if not ttl_covered.all():
                notes = (f"TTL coverage {int(ttl_covered.sum())}/{len(ttl_covered)}. "
                         "Behavior synchronization is unavailable for frames without measured TTL times.")
            self.calcium_export.setToolTip("Exports movie samples with empty time_ms outside measured TTL coverage. The current trim limits exported samples.")
        else:
            self.calcium_curve.setData(table.time_ms.to_numpy(), table.value.to_numpy(), connect="finite")
            self.calcium_plot.setLabel("bottom", "Common Arduino time", units="ms")
            if previous_mode:
                self.calcium_plot.setXRange(*self.plot.viewRange()[0], padding=0)
            notes = ""
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
        status_text = (prefix + notes).strip()
        self.calcium_status.setText(status_text)
        self.calcium_status.setVisible(bool(status_text))
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

    def accent_palette(self):
        return accent_palette(self.day_mode)

    def set_day_mode(self, enabled):
        snapshot = None
        if self.isVisible() and self.day_mode != enabled:
            # Capture any active reveal too, so rapid clicks continue smoothly.
            snapshot = self.grab()
            if getattr(self, "_theme_reveal", None) is not None:
                self._theme_reveal.stop()
        self.day_mode = enabled
        palette = application_palette(self.default_palette, enabled)
        QApplication.setPalette(palette)
        logo_name = "cali_logo_horizontal.svg" if enabled else "cali_logo_horizontal_dark.svg"
        logo_path = Path(__file__).parent / "assets" / "icons" / "logo" / logo_name
        self.brand_logo.load(str(logo_path))
        self.setWindowIcon(QIcon(str(logo_path)))
        self.theme_btn.set_day_mode(enabled)
        self.setStyleSheet(self.app_stylesheet())
        accents = self.accent_palette()
        self.cam_panel.accent_dot.setStyleSheet(f"color: {accents['camera']};")
        self.mini_panel.accent_dot.setStyleSheet(f"color: {accents['mini']};")
        self.plot.setBackground("#F8F5EE" if enabled else "#0C1927")
        for axis_name in ("bottom", "left"):
            axis = self.plot.getAxis(axis_name)
            axis.setPen(pg.mkPen("#C5BEB1" if enabled else "#315067"))
            axis.setTextPen(pg.mkPen("#625E55" if enabled else "#C8D7E3"))
        self.cursor_line.set_color("#49473F" if enabled else "#F0F7FC")
        self.cam_pts.setPen(pg.mkPen(accents["camera"], width=FRAME_TICK_WIDTH))
        self.mini_pts.setPen(pg.mkPen(accents["mini"], width=FRAME_TICK_WIDTH))
        self.gap_pts.setPen(pg.mkPen(accents["gap"], width=1.8))
        self.calcium_plot.setBackground("#F8F5EE" if enabled else "#0C1927")
        for axis_name in ("bottom", "left"):
            axis = self.calcium_plot.getAxis(axis_name)
            axis.setPen(pg.mkPen("#C5BEB1" if enabled else "#315067"))
            axis.setTextPen(pg.mkPen("#625E55" if enabled else "#C8D7E3"))
        self.calcium_curve.setPen(pg.mkPen(accents["mini"], width=1.5))
        self.calcium_cursor.set_color("#49473F" if enabled else "#F0F7FC")
        self.theme_changed.emit(enabled)
        if snapshot is not None:
            if getattr(self, "_theme_reveal", None) is None:
                self._theme_reveal = RadialThemeReveal(self)
            self._theme_reveal.start(snapshot)

    def card(self, obj_name="card"):
        frame = QFrame()
        frame.setObjectName(obj_name)
        return frame

    def app_stylesheet(self):
        return app_stylesheet(self.day_mode)

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

        progress = QProgressDialog(
            "Exporting cropped behavior video…",
            "Cancel",
            0,
            self.video.count,
            self,
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        def advance(written):
            progress.setValue(written)
            QApplication.processEvents()
            return progress.wasCanceled()

        try:
            written, cancelled = write_video_prefix(
                self.video_path, video_out, self.video.count, crop=crop, progress=advance,
                open_error="Could not open source/output MP4 for cropping")
        finally:
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
        write_export_metadata(info_out, info)
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
            dialog = MovementAnalysisDialog(self)
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

        n = vi + 1
        progress = QProgressDialog("Exporting trimmed behavior video…", "Cancel", 0, n, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        def advance(written):
            progress.setValue(written)
            QApplication.processEvents()
            return progress.wasCanceled()

        try:
            written, cancelled = write_video_prefix(
                self.video_path, video_out, n, crop=crop, progress=advance)
        finally:
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
        write_export_metadata(info_out, info)
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
