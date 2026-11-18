import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import QApplication

from cali.viewer import TimelineCursor, Viewer


class TimelineCursorTests(unittest.TestCase):
    """Timeline cursor is easy to grab and drag (issue #3)."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")

    def setUp(self):
        self.v = Viewer()
        self.v.resize(1400, 900)
        self.v.show()
        self.v.mini_df = pd.DataFrame({"frame": np.arange(1, 101), "timestamp_ms": np.arange(100) * 50.})
        self.v.camera_df = pd.DataFrame({"frame": np.arange(1, 151), "timestamp_ms": np.arange(150) * 33.})
        self.v.rebuild()
        self.v.set_time(2000.)
        self.settle()
        self.line = self.v.cursor_line

    def tearDown(self):
        self.v.close()

    def settle(self):
        for _ in range(5):
            self.app.processEvents()

    def line_point(self, dx=0.):
        """Viewport position on the cursor line, dx screen pixels to its right."""
        plot = self.v.plot
        vb = plot.getViewBox()
        scene = vb.mapViewToScene(QPointF(self.line.value(), 0.5))
        point = plot.mapFromScene(scene)
        return QPointF(point.x() + dx, point.y())

    def send(self, kind, point, button=Qt.NoButton, buttons=Qt.NoButton):
        viewport = self.v.plot.viewport()
        # pyqtgraph drops moves closer together than its frame rate; tests send them instantly.
        self.v.plot.scene()._lastMoveEventTime = 0
        event = QMouseEvent(kind, point, viewport.mapToGlobal(point), button, buttons, Qt.NoModifier)
        QApplication.sendEvent(viewport, event)
        self.settle()

    def width(self):
        return self.line.currentPen.widthF()

    def test_line_thickens_when_pointer_is_near_and_thins_when_it_leaves(self):
        self.assertEqual(self.width(), TimelineCursor.WIDTH)
        self.send(QEvent.MouseMove, self.line_point(TimelineCursor.GRAB_PX - 1))
        self.assertTrue(self.line.mouseHovering)
        self.assertEqual(self.width(), TimelineCursor.HOVER_WIDTH)
        self.send(QEvent.MouseMove, self.line_point(40))
        self.assertFalse(self.line.mouseHovering)
        self.assertEqual(self.width(), TimelineCursor.WIDTH)

    def test_grab_zone_extends_past_the_line_but_not_far(self):
        self.send(QEvent.MouseMove, self.line_point(-(TimelineCursor.GRAB_PX - 1)))
        self.assertTrue(self.line.mouseHovering)
        self.send(QEvent.MouseMove, self.line_point(TimelineCursor.GRAB_PX + 6))
        self.assertFalse(self.line.mouseHovering)

    def test_drag_from_beside_the_line_moves_time_and_viewers(self):
        start = self.line_point(TimelineCursor.GRAB_PX - 1)
        self.send(QEvent.MouseMove, start)
        self.send(QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton)
        for step in range(1, 11):
            point = QPointF(start.x() + 20 * step, start.y())
            self.send(QEvent.MouseMove, point, Qt.NoButton, Qt.LeftButton)
            self.assertEqual(self.width(), TimelineCursor.HOVER_WIDTH)
        self.send(QEvent.MouseButtonRelease, point, Qt.LeftButton, Qt.NoButton)
        self.assertGreater(self.v.current_t, 2000.)
        self.assertEqual(self.line.value(), self.v.current_t)
        mini = int(self.v.mini_df.frame.iloc[self.v.nearest(self.v.mini_t, self.v.current_t)])
        self.assertIn(f"Frame {mini} ", self.v.mini_panel.image.toolTip())
        self.assertFalse(self.line.moving)

    def test_line_thins_once_drag_ends_and_pointer_leaves(self):
        start = self.line_point()
        self.send(QEvent.MouseMove, start)
        self.send(QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton)
        end = QPointF(start.x() + 100, start.y())
        self.send(QEvent.MouseMove, end, Qt.NoButton, Qt.LeftButton)
        self.send(QEvent.MouseButtonRelease, end, Qt.LeftButton, Qt.NoButton)
        # The released line sits under the pointer, so it is still highlighted.
        self.assertEqual(self.width(), TimelineCursor.HOVER_WIDTH)
        self.send(QEvent.MouseMove, QPointF(end.x() + 60, end.y()))
        self.assertFalse(self.line.mouseHovering)
        self.assertEqual(self.width(), TimelineCursor.WIDTH)

    def test_both_cursors_follow_the_theme_and_never_hover_red(self):
        for cursor in (self.v.cursor_line, self.v.calcium_cursor):
            self.assertIsInstance(cursor, TimelineCursor)
        for _ in range(2):
            self.v.theme_btn.click()
            self.settle()
            for cursor in (self.v.cursor_line, self.v.calcium_cursor):
                self.assertEqual(cursor.hoverPen.color(), cursor.pen.color())
                self.assertNotEqual(cursor.pen.color(), QColor(255, 0, 0))
                self.assertEqual(cursor.hoverPen.widthF(), TimelineCursor.HOVER_WIDTH)


if __name__ == "__main__":
    unittest.main()
