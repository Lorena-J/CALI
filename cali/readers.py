"""Local video/TIFF readers with bounded frame caches."""
from collections import OrderedDict
from pathlib import Path

import cv2
import numpy as np
import tifffile


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
