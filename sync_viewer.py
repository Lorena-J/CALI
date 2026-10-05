#!/usr/bin/env python3
import sys
from pathlib import Path
from collections import OrderedDict

import cv2
import numpy as np
import pandas as pd
import pyqtgraph as pg
import tifffile
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QSpinBox, QSplitter, QVBoxLayout, QWidget, QToolTip
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
    """Reconstruct expected frame indices from STROBE timing.
    A ~2x interval advances the virtual index by 2, etc.
    This is QC assistance, not proof that an exposure occurred.
    """
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
        v = self.d.pop(k); self.d[k] = v; return v
    def put(self, k, v):
        if k in self.d: self.d.pop(k)
        self.d[k] = v
        while len(self.d) > self.n: self.d.popitem(last=False)
    def clear(self): self.d.clear()


class VideoReader:
    def __init__(self):
        self.cap = None; self.count = 0; self.fps = np.nan; self.cache = Cache(80)
    def open(self, path):
        self.close(); self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened(): raise RuntimeError(f"Cannot open video: {path}")
        self.count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = float(self.cap.get(cv2.CAP_PROP_FPS))
    def read(self, idx):
        if self.cap is None or idx < 0 or idx >= self.count: return None
        c = self.cache.get(idx)
        if c is not None: return c
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, frame = self.cap.read()
        if not ok: return None
        self.cache.put(idx, frame); return frame
    def close(self):
        if self.cap is not None: self.cap.release()
        self.cap = None; self.count = 0; self.fps = np.nan; self.cache.clear()


class TiffReader:
    def __init__(self):
        self.tif = None; self.count = 0; self.cache = Cache(40)
    def open(self, path):
        self.close(); self.tif = tifffile.TiffFile(str(path)); self.count = len(self.tif.pages)
        if self.count == 0: raise RuntimeError("TIFF contains no pages")
    def read(self, idx):
        if self.tif is None or idx < 0 or idx >= self.count: return None
        c = self.cache.get(idx)
        if c is not None: return c
        frame = self.tif.pages[idx].asarray(); self.cache.put(idx, frame); return frame
    def close(self):
        if self.tif is not None: self.tif.close()
        self.tif = None; self.count = 0; self.cache.clear()


class ImagePanel(QGroupBox):
    def __init__(self, title):
        super().__init__(title)
        self.image = QLabel("No file loaded"); self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumSize(420, 300)
        self.image.setStyleSheet("background:#111;color:#aaa;border:1px solid #333")
        self.info = QLabel("—"); self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay = QVBoxLayout(self); lay.addWidget(self.image, 1); lay.addWidget(self.info)
        self.pm = None
    def set_frame(self, frame, info, bgr=False):
        self.info.setText(info)
        if frame is None:
            self.pm = None; self.image.setPixmap(QPixmap()); self.image.setText("Frame unavailable")
        else:
            self.pm = pixmap_from_array(frame, bgr=bgr); self.image.setText(""); self._fit()
    def _fit(self):
        if self.pm is not None and not self.pm.isNull():
            self.image.setPixmap(self.pm.scaled(self.image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
    def resizeEvent(self, e):
        super().resizeEvent(e); self._fit()


class Viewer(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("Mini2P / Behavior Synchronization Viewer"); self.resize(1450, 900)
        self.camera_df = self.mini_df = None
        self.camera_t = self.mini_t = None
        self.camera_dt = self.mini_dt = None
        self.camera_gap = self.mini_gap = None
        self.camera_virtual = None
        self.t0 = None; self.current_t = 0.0
        self.video = VideoReader(); self.tiff = TiffReader()
        self.hover_pos = None
        self.hover_timer = QTimer(self); self.hover_timer.setSingleShot(True); self.hover_timer.setInterval(500)
        self.hover_timer.timeout.connect(self.show_hover)
        self.build_ui()

    def build_ui(self):
        w = QWidget(); self.setCentralWidget(w); root = QVBoxLayout(w)
        row = QHBoxLayout()
        for text, fn in [("Load camera CSV", self.load_camera), ("Load Mini2P CSV", self.load_mini),
                         ("Load behavior MP4", self.load_video), ("Load ScanImage TIFF", self.load_tiff)]:
            b = QPushButton(text); b.clicked.connect(fn); row.addWidget(b)
        row.addStretch(); root.addLayout(row)

        self.qc = QLabel("Load the two TTL CSV files."); self.qc.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.qc.setStyleSheet("padding:7px;background:#f4f4f4;border:1px solid #ccc")
        root.addWidget(self.qc)

        sp = QSplitter(Qt.Horizontal); self.cam_panel = ImagePanel("Behavior camera"); self.mini_panel = ImagePanel("Mini2P / calcium")
        sp.addWidget(self.cam_panel); sp.addWidget(self.mini_panel); root.addWidget(sp, 1)

        self.plot = pg.PlotWidget(); self.plot.setMinimumHeight(230); self.plot.setLabel("bottom", "Common Arduino time", units="ms")
        self.plot.setYRange(-0.6, 1.6); self.plot.setMouseEnabled(x=True, y=False); self.plot.showGrid(x=True, alpha=.2)
        self.plot.getAxis("left").setTicks([[(0, "Mini2P"), (1, "Camera")]])
        self.cam_pts = pg.ScatterPlotItem(size=5, pen=None, brush=pg.mkBrush(70,130,220,180))
        self.mini_pts = pg.ScatterPlotItem(size=7, pen=None, brush=pg.mkBrush(230,150,40,210))
        self.gap_pts = pg.ScatterPlotItem(size=11, symbol="x", pen=pg.mkPen(220,40,40,width=2))
        self.plot.addItem(self.cam_pts); self.plot.addItem(self.mini_pts); self.plot.addItem(self.gap_pts)
        self.cursor_line = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen(30,30,30,width=2)); self.plot.addItem(self.cursor_line)
        self.cursor_line.sigPositionChanged.connect(lambda: self.set_time(float(self.cursor_line.value())))
        self.plot.scene().sigMouseClicked.connect(self.plot_clicked); self.plot.scene().sigMouseMoved.connect(self.mouse_moved)
        root.addWidget(self.plot)

        ctrl = QHBoxLayout()
        p = QPushButton("← Mini2P frame"); p.clicked.connect(lambda: self.step_mini(-1)); ctrl.addWidget(p)
        p = QPushButton("Mini2P frame →"); p.clicked.connect(lambda: self.step_mini(1)); ctrl.addWidget(p)
        p = QPushButton("← Previous gap"); p.clicked.connect(lambda: self.jump_gap(-1)); ctrl.addWidget(p)
        p = QPushButton("Next gap →"); p.clicked.connect(lambda: self.jump_gap(1)); ctrl.addWidget(p)
        ctrl.addStretch()
        g = QGroupBox("Behavior video mapping"); f = QFormLayout(g)
        self.mode = QComboBox(); self.mode.addItems(["Timing reconstruction", "TTL index"]); self.mode.currentIndexChanged.connect(self.update_views)
        self.offset = QSpinBox(); self.offset.setRange(-1000000,1000000); self.offset.setValue(0); self.offset.valueChanged.connect(self.update_views)
        f.addRow("Mapping:", self.mode); f.addRow("MP4 start offset:", self.offset); ctrl.addWidget(g)
        root.addLayout(ctrl)

        self.info = QLabel("Click or drag on the timeline."); self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.info.setStyleSheet("padding:7px;border-top:1px solid #ccc"); root.addWidget(self.info)

    def choose(self, title, filt):
        p,_ = QFileDialog.getOpenFileName(self,title,"",filt); return p
    def load_camera(self):
        p=self.choose("Camera TTL CSV","CSV (*.csv)")
        if not p:return
        try:self.camera_df=load_csv(p,"Camera");self.rebuild()
        except Exception as e:self.err(e)
    def load_mini(self):
        p=self.choose("Mini2P TTL CSV","CSV (*.csv)")
        if not p:return
        try:self.mini_df=load_csv(p,"Mini2P");self.rebuild()
        except Exception as e:self.err(e)
    def load_video(self):
        p=self.choose("Behavior video","Video (*.mp4 *.avi *.mov *.mkv)")
        if not p:return
        try:self.video.open(p);self.update_qc();self.update_views()
        except Exception as e:self.err(e)
    def load_tiff(self):
        p=self.choose("ScanImage TIFF","TIFF (*.tif *.tiff)")
        if not p:return
        try:self.tiff.open(p);self.update_qc();self.update_views()
        except Exception as e:self.err(e)

    def rebuild(self):
        if self.mini_df is None:
            self.update_qc(); return
        self.t0=float(self.mini_df.timestamp_ms.iloc[0]); self.mini_t=self.mini_df.timestamp_ms.to_numpy(float)-self.t0
        self.mini_df["time_ms"]=self.mini_t; self.mini_dt=np.r_[np.nan,np.diff(self.mini_t)]
        pm=median_period(self.mini_t); self.mini_gap=self.mini_dt>(1.5*pm) if np.isfinite(pm) else np.zeros(len(self.mini_t),bool)
        if self.camera_df is not None:
            self.camera_t=self.camera_df.timestamp_ms.to_numpy(float)-self.t0; self.camera_df["time_ms"]=self.camera_t
            self.camera_dt=np.r_[np.nan,np.diff(self.camera_t)]; pc=median_period(self.camera_t)
            self.camera_gap=self.camera_dt>(1.5*pc) if np.isfinite(pc) else np.zeros(len(self.camera_t),bool)
            self.camera_virtual=virtual_camera_indices(self.camera_t)
        self.draw(); self.update_qc(); self.set_time(float(self.mini_t[0]))

    def draw(self):
        if self.mini_t is not None:self.mini_pts.setData(x=self.mini_t,y=np.zeros(len(self.mini_t)))
        if self.camera_t is not None:
            self.cam_pts.setData(x=self.camera_t,y=np.ones(len(self.camera_t)))
            self.gap_pts.setData(x=self.camera_t[self.camera_gap],y=np.ones(int(self.camera_gap.sum())))
        arr=[x for x in (self.mini_t,self.camera_t) if x is not None and len(x)]
        if arr:
            a=np.concatenate(arr); lo=float(a.min()); hi=float(a.max()); m=max(20.,(hi-lo)*.02); self.plot.setXRange(lo-m,hi+m,padding=0)

    def update_qc(self):
        s=[]
        if self.mini_t is not None:
            p=median_period(self.mini_t); hz=1000/p if np.isfinite(p) else np.nan
            s.append(f"<b>Mini2P TTL</b>: {len(self.mini_t)} · {hz:.3f} Hz · gaps {int(self.mini_gap.sum())}")
        if self.camera_t is not None:
            p=median_period(self.camera_t); hz=1000/p if np.isfinite(p) else np.nan
            s.append(f"<b>Camera STROBE</b>: {len(self.camera_t)} · {hz:.3f} Hz · gaps {int(self.camera_gap.sum())}")
        if self.tiff.tif is not None:
            match=(self.mini_df is not None and self.tiff.count==len(self.mini_df)); s.append(f"<b>TIFF</b>: {self.tiff.count} pages · {'✓ count matches' if match else '⚠ check count'}")
        if self.video.cap is not None:s.append(f"<b>MP4</b>: {self.video.count} frames · {self.video.fps:.3f} fps")
        self.qc.setText(" &nbsp; | &nbsp; ".join(s) if s else "Load files.")

    def nearest(self, a,t): return None if a is None or len(a)==0 else int(np.argmin(np.abs(a-t)))
    def set_time(self,t):
        self.current_t=float(t); self.cursor_line.blockSignals(True); self.cursor_line.setValue(self.current_t); self.cursor_line.blockSignals(False); self.update_views()
    def plot_clicked(self,e):
        if e.button()!=Qt.LeftButton:return
        p=self.plot.getViewBox().mapSceneToView(e.scenePos()); self.set_time(float(p.x()))
    def step_mini(self,d):
        i=self.nearest(self.mini_t,self.current_t)
        if i is None:return
        i=int(np.clip(i+d,0,len(self.mini_t)-1)); self.set_time(float(self.mini_t[i]))
    def jump_gap(self,d):
        if self.camera_t is None or not self.camera_gap.any():return
        g=self.camera_t[self.camera_gap]
        if d>0:
            c=g[g>self.current_t+1e-9]; target=c[0] if len(c) else g[0]
        else:
            c=g[g<self.current_t-1e-9]; target=c[-1] if len(c) else g[-1]
        self.set_time(float(target))

    def video_index(self,ci):
        if ci is None:return None
        base=int(self.camera_virtual[ci]) if self.mode.currentText()=="Timing reconstruction" else ci
        return int(self.offset.value())+base

    def update_views(self):
        t=self.current_t; mi=self.nearest(self.mini_t,t); ci=self.nearest(self.camera_t,t)
        mf=None; minfo="No Mini2P TTL loaded"
        if mi is not None:
            mt=float(self.mini_t[mi]); fn=int(self.mini_df.frame.iloc[mi]); minfo=f"Frame {fn} | t={mt:.3f} ms | cursor Δ={t-mt:+.3f} ms"
            if self.tiff.tif is not None:
                mf=self.tiff.read(fn-1); minfo+=f" | TIFF page {fn}"
        self.mini_panel.set_frame(mf,minfo)
        cf=None; cinfo="No camera TTL loaded"
        if ci is not None:
            ct=float(self.camera_t[ci]); fn=int(self.camera_df.frame.iloc[ci]); cinfo=f"STROBE {fn} | t={ct:.3f} ms | cursor Δ={t-ct:+.3f} ms"
            if ci>0:cinfo+=f" | interval={self.camera_dt[ci]:.3f} ms"
            if self.camera_gap[ci]:cinfo+=" | ⚠ gap"
            if self.video.cap is not None:
                vi=self.video_index(ci); cf=self.video.read(vi); cinfo+=f" | MP4 frame {vi+1}"
        self.cam_panel.set_frame(cf,cinfo,bgr=True)
        bits=[f"<b>Cursor:</b> {t:.3f} ms"]
        if mi is not None: bits.append(f"<b>Mini2P:</b> {int(self.mini_df.frame.iloc[mi])} @ {self.mini_t[mi]:.3f} ms")
        if ci is not None: bits.append(f"<b>Camera:</b> {int(self.camera_df.frame.iloc[ci])} @ {self.camera_t[ci]:.3f} ms")
        if mi is not None and ci is not None: bits.append(f"<b>Camera−Mini2P:</b> {self.camera_t[ci]-self.mini_t[mi]:+.3f} ms")
        self.info.setText(" &nbsp; | &nbsp; ".join(bits))

    def mouse_moved(self,p): self.hover_pos=p; self.hover_timer.start()
    def show_hover(self):
        if self.hover_pos is None:return
        vb=self.plot.getViewBox(); q=vb.mapSceneToView(self.hover_pos); x=float(q.x()); y=float(q.y())
        (x0,x1),_=vb.viewRange(); width=max(self.plot.getPlotItem().vb.sceneBoundingRect().width(),1); tol=abs(x1-x0)*8/width
        text=None
        if y>=.5 and self.camera_t is not None:
            i=self.nearest(self.camera_t,x); tt=float(self.camera_t[i])
            if abs(tt-x)<=tol:
                j=self.nearest(self.mini_t,tt); lines=[f"Camera STROBE #{int(self.camera_df.frame.iloc[i])}",f"t = {tt:.3f} ms"]
                if i>0:lines.append(f"interval = {self.camera_dt[i]:.3f} ms")
                if self.camera_gap[i]:lines.append("⚠ gap detected")
                if j is not None:lines += ["",f"Nearest Mini2P #{int(self.mini_df.frame.iloc[j])}",f"t = {self.mini_t[j]:.3f} ms",f"Δ = {tt-self.mini_t[j]:+.3f} ms"]
                text="\n".join(lines)
        elif y<.5 and self.mini_t is not None:
            i=self.nearest(self.mini_t,x); tt=float(self.mini_t[i])
            if abs(tt-x)<=tol:
                j=self.nearest(self.camera_t,tt); lines=[f"Mini2P frame #{int(self.mini_df.frame.iloc[i])}",f"t = {tt:.3f} ms"]
                if j is not None:lines += ["",f"Nearest camera STROBE #{int(self.camera_df.frame.iloc[j])}",f"t = {self.camera_t[j]:.3f} ms",f"Δ = {self.camera_t[j]-tt:+.3f} ms"]
                text="\n".join(lines)
        if text:QToolTip.showText(self.cursor().pos(),text,self.plot)

    def keyPressEvent(self,e):
        if e.key()==Qt.Key_Left:self.step_mini(-1);return
        if e.key()==Qt.Key_Right:self.step_mini(1);return
        if e.key()==Qt.Key_PageUp:self.jump_gap(-1);return
        if e.key()==Qt.Key_PageDown:self.jump_gap(1);return
        super().keyPressEvent(e)
    def err(self,e): QMessageBox.critical(self,"Error",f"{type(e).__name__}: {e}")
    def closeEvent(self,e): self.video.close(); self.tiff.close(); super().closeEvent(e)


def main():
    app=QApplication(sys.argv); pg.setConfigOptions(antialias=False); v=Viewer(); v.show(); sys.exit(app.exec())

if __name__=="__main__": main()
