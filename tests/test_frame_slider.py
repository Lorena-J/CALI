import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cali.viewer import Viewer


class FrameSliderTests(unittest.TestCase):
    """Mini2P frame slider below the Timeline (issue #4)."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")

    def setUp(self):
        self.v = Viewer()

    def tearDown(self):
        self.v.close()

    def load(self):
        # Mini2P IDs are not consecutive on purpose: the slider steps through
        # recorded TTL frames, and the label shows their own IDs.
        self.v.mini_df = pd.DataFrame({"frame": [1, 3, 4, 6], "timestamp_ms": [100., 122., 131., 154.]})
        self.v.camera_df = pd.DataFrame({"frame": np.arange(1, 7), "timestamp_ms": np.arange(100., 160., 10.)})
        self.v.rebuild()

    def test_disabled_without_mini2p_timestamps(self):
        for widget in (self.v.frame_slider, self.v.frame_back_btn, self.v.frame_forward_btn):
            self.assertFalse(widget.isEnabled())
        self.assertEqual(self.v.frame_label.text(), "No Mini2P TTL loaded")

    def test_covers_loaded_mini2p_frames(self):
        self.load()
        self.assertTrue(self.v.frame_slider.isEnabled())
        self.assertEqual((self.v.frame_slider.minimum(), self.v.frame_slider.maximum()), (0, 3))
        self.assertEqual(self.v.frame_slider.value(), 0)
        self.assertEqual(self.v.frame_label.text(), "TTL-linked Mini2P frame 1 · 1/4")

    def test_moving_slider_selects_frame_and_moves_cursor(self):
        self.load()
        self.v.frame_slider.setValue(2)
        self.assertEqual(self.v.current_t, 31.)
        self.assertEqual(self.v.cursor_line.value(), 31.)
        self.assertEqual(self.v.frame_label.text(), "TTL-linked Mini2P frame 4 · 3/4")
        self.assertIn("Frame 4 ", self.v.mini_panel.image.toolTip())

    def test_arrows_step_exactly_one_frame_and_stop_at_the_ends(self):
        self.load()
        self.assertFalse(self.v.frame_back_btn.isEnabled())
        self.v.frame_forward_btn.click()
        self.assertEqual(self.v.current_t, 22.)
        self.assertTrue(self.v.frame_back_btn.isEnabled())
        for _ in range(5):
            self.v.step_frame_slider(1)
        self.assertEqual(self.v.current_t, 54.)
        self.assertFalse(self.v.frame_forward_btn.isEnabled())
        self.v.frame_back_btn.click()
        self.assertEqual(self.v.current_t, 31.)

    def test_follows_cursor_moved_elsewhere(self):
        self.load()
        self.v.cursor_line.setValue(50.)  # nearest Mini2P frame is the last one
        self.assertEqual(self.v.frame_slider.value(), 3)
        self.v.step_mini(-1)
        self.assertEqual(self.v.frame_slider.value(), 2)
        self.assertEqual(self.v.frame_label.text(), "TTL-linked Mini2P frame 4 · 3/4")

    def test_trim_limits_frames_like_the_arrow_keys(self):
        self.load()
        self.v.cursor_line.setValue(30.)
        self.v.set_trim_current()  # cut at camera time 30 ms
        self.assertEqual(self.v.frame_slider.maximum(), 1)
        self.v.trim_idx = None
        self.v.draw()
        self.assertEqual(self.v.frame_slider.maximum(), 3)

    def test_navigation_keys_on_slider_keep_their_viewer_meaning(self):
        self.load()
        calls = []
        self.v.step_mini = lambda step: calls.append(("frame", step))
        self.v.jump_gap = lambda step: calls.append(("gap", step))
        QTest.keyClick(self.v.frame_slider, Qt.Key_Right)
        QTest.keyClick(self.v.frame_slider, Qt.Key_PageDown)
        self.assertEqual(calls, [("frame", 1), ("gap", 1)])
        self.assertEqual(self.v.frame_slider.value(), 0)
        QTest.keyClick(self.v.frame_slider, Qt.Key_End)
        self.assertEqual(self.v.frame_slider.value(), 3)
        self.assertEqual(self.v.current_t, 54.)


if __name__ == "__main__":
    unittest.main()
