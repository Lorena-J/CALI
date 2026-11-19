import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtWidgets import QApplication

from cali.viewer import FRAME_TICK_HEIGHT, FRAME_TICK_SYMBOL, Viewer


class TimelineFrameTickTests(unittest.TestCase):
    """Timeline frames are short vertical ticks, not dots (issue #2)."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.v = Viewer()
        self.v.mini_df = pd.DataFrame({"frame": [1, 3, 4, 6], "timestamp_ms": [100., 122., 131., 154.]})
        self.v.camera_df = pd.DataFrame({"frame": np.arange(1, 7), "timestamp_ms": np.arange(100., 160., 10.)})
        self.v.rebuild()

    def tearDown(self):
        self.v.close()

    def test_tick_symbol_is_a_vertical_line_centred_on_the_point(self):
        rect = FRAME_TICK_SYMBOL.boundingRect()
        self.assertEqual((rect.left(), rect.right()), (0, 0))
        self.assertEqual((rect.top(), rect.bottom()), (-0.5, 0.5))

    def test_both_series_draw_ticks_at_their_timestamps_on_their_rows(self):
        for item, times, row in ((self.v.mini_pts, self.v.mini_t, 0), (self.v.cam_pts, self.v.camera_t, 1)):
            x, y = item.getData()
            np.testing.assert_array_equal(x, times)
            np.testing.assert_array_equal(y, np.full(len(times), row))
            for point in item.points():
                self.assertIs(point.symbol(), FRAME_TICK_SYMBOL)
                self.assertEqual(point.size(), FRAME_TICK_HEIGHT)

    def test_ticks_take_the_series_accent_in_both_themes(self):
        for day in (False, True):
            self.v.set_day_mode(day)
            accents = self.v.accent_palette()
            for item, role in ((self.v.mini_pts, "mini"), (self.v.cam_pts, "camera")):
                self.assertEqual(item.opts["pen"].color().name(), pg.mkColor(accents[role]).name())

    def test_tick_height_does_not_change_with_zoom(self):
        self.v.plot.setXRange(20., 35., padding=0)
        self.assertTrue(self.v.cam_pts.opts["pxMode"])
        self.assertTrue(all(point.size() == FRAME_TICK_HEIGHT for point in self.v.cam_pts.points()))


if __name__ == "__main__":
    unittest.main()
