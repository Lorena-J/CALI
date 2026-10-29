import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import cv2
from PySide6.QtWidgets import QApplication

from cali import Viewer, TrackingAlignmentDialog


class TrackingAlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.v = Viewer()
        self.v.mini_df = pd.DataFrame({"frame": np.arange(1, 8), "timestamp_ms": np.arange(0., 61., 10.)})
        self.v.camera_df = pd.DataFrame({"frame": np.arange(1, 7), "timestamp_ms": np.arange(5., 56., 10.)})
        self.v.rebuild()
        self.v.video.cap = Mock()
        self.v.video.cap.read.return_value = (False, None)
        self.v.video.count = 8
        self.d = TrackingAlignmentDialog(self.v)
        self.set_tracking(np.arange(8.))

    def tearDown(self):
        self.d.close()
        self.v.close()

    def set_tracking(self, x, indices=None):
        self.d.tracking_df = pd.DataFrame({"x": x})
        if indices is not None:
            self.d.tracking_df.insert(0, "frame_index", indices)
        self.d.numeric_data = {"x": np.asarray(x, dtype=float)}
        self.d.x_combo.clear()
        self.d.x_combo.addItem("x")

    def test_no_extrapolation_and_one_row_per_mini_frame(self):
        self.d._align_tracking()
        result = self.d.result_df
        self.assertEqual(len(result), 7)
        self.assertTrue(result.x_aligned.iloc[[0, -1]].isna().all())
        self.assertTrue(result.nearest_behavior_frame.iloc[[0, -1]].isna().all())
        np.testing.assert_array_equal(self.d.target_video_indices[[0, -1]], [-1, -1])
        self.assertTrue(np.isnan(self.d.video_times[6:]).all())
        np.testing.assert_allclose(result.x_aligned.iloc[1:-1], np.arange(.5, 5., 1.))

    def test_trim_limits_sources_but_keeps_calcium_rows(self):
        self.v.set_time(35.)
        self.v.set_trim_current()
        self.d._align_tracking()
        result = self.d.result_df
        self.assertEqual(len(result), 7)
        self.assertTrue(result.x_aligned[result.target_time_ms > 35.].isna().all())
        self.assertLessEqual(result.source_right_frame.max(), 4)
        self.assertLessEqual(result.nearest_behavior_frame.max(), 4)
        self.assertTrue(np.isnan(self.d.video_times[4:]).all())

    def test_camera_mode_preserves_timestamps_instead_of_regular_grid(self):
        self.v.camera_df.timestamp_ms = [5., 15.1, 25., 35.2, 45., 55.]
        self.v.rebuild()
        self.d.mode_combo.setCurrentIndex(0)
        self.d._align_tracking()
        np.testing.assert_array_equal(self.d.target_times, self.v.camera_t)
        np.testing.assert_array_equal(self.d.target_x, np.arange(6.))

    def test_mapping_uses_actual_valid_tracking_neighbors(self):
        x = np.arange(8.)
        x[1] = np.nan
        self.set_tracking(x)
        self.d._align_tracking()
        row = self.d.result_df.iloc[2]  # t=20, between frame 1 at 5 and frame 3 at 25
        self.assertEqual(row.source_left_frame, 1)
        self.assertEqual(row.source_right_frame, 3)
        self.assertAlmostEqual(row.interpolation_alpha, .75)
        self.assertAlmostEqual(row.x_aligned, 1.5)
        self.assertTrue(np.isfinite(row.nearest_behavior_frame))

    def test_long_tracking_gaps_stay_empty_and_limit_is_configurable(self):
        x = np.arange(8.)
        x[1:4] = np.nan
        self.set_tracking(x)
        self.d._align_tracking()
        self.assertTrue(self.d.result_df.x_aligned.iloc[1:5].isna().all())
        self.assertTrue(self.d.result_df.source_left_frame.iloc[1:5].isna().all())
        # Tracking gaps do not erase existing video images.
        self.assertTrue(self.d.result_df.nearest_behavior_frame.iloc[1:5].notna().all())
        self.d.max_missing_frames.setValue(3)
        self.d._align_tracking()
        self.assertTrue(self.d.result_df.x_aligned.iloc[1:5].notna().all())

    def test_sparse_frame_indices_preserve_correspondence(self):
        indices = np.array([0, 2, 3, 5, 6, 7])
        self.set_tracking(indices.astype(float), indices)
        self.d._align_tracking()
        row = self.d.result_df.iloc[2]
        self.assertEqual(row.source_left_frame, 1)
        self.assertEqual(row.source_right_frame, 3)
        self.assertAlmostEqual(row.x_aligned, 1.5)

    def test_invalid_frame_correspondence_is_rejected(self):
        self.set_tracking(np.arange(5.))
        with self.assertRaisesRegex(ValueError, "matching video"):
            self.d._align_tracking()
        for indices in ([0, 1, 1], [1, 0, 2], [0, 1, 9], [0, .5, 2]):
            self.set_tracking(np.arange(3.), indices)
            with self.assertRaises(ValueError):
                self.d._align_tracking()

    def test_dlc_header_does_not_become_tracking_rows(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "dlc.csv"
            path.write_text("scorer,DLC,DLC,DLC\nbodyparts,nose,nose,nose\ncoords,x,y,likelihood\n"
                            "0,1,2,0.99\n1,3,4,0.99\n2,5,6,0.99\n")
            df, numeric = self.d.load_tracking_table(path)
        self.assertEqual(len(df), 3)
        np.testing.assert_array_equal(df.frame_index, [0, 1, 2])
        np.testing.assert_array_equal(numeric["nose.x"], [1, 3, 5])
        self.assertNotIn("frame_index", numeric)

    def test_changes_in_viewer_invalidate_alignment(self):
        for change in (lambda: self.v.offset.setValue(1), self.v.auto_trim,
                       self.v.clear_trim, self.v.rebuild):
            self.d._align_tracking()
            self.assertIsNotNone(self.d.result_df)
            change()
            self.assertIsNone(self.d.result_df)

    def test_invalid_alignment_does_not_leave_stale_export(self):
        self.d._align_tracking()
        self.set_tracking(np.arange(3.))
        with patch("cali.QMessageBox.warning") as warning:
            self.d.align_tracking()
        warning.assert_called_once()
        self.assertIsNone(self.d.result_df)

    def test_video_export_keeps_blank_frames_and_consistent_mapping(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / "source.mp4"
            target = Path(folder) / "aligned.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 100., (80, 60))
            self.assertTrue(writer.isOpened())
            for _ in range(8):
                writer.write(np.full((60, 80, 3), 160, dtype=np.uint8))
            writer.release()
            self.v.video.open(source)
            self.v.video_path = source
            self.d._align_tracking()
            expected = self.d.result_df.copy()
            # A change during progress must not corrupt the in-progress export.
            with patch("cali.QFileDialog.getSaveFileName", return_value=(str(target), "")), \
                 patch("cali.QMessageBox.information"), \
                 patch("cali.QMessageBox.critical") as error, \
                 patch("cali.QApplication.processEvents", side_effect=self.d.invalidate_alignment):
                self.d.export_video()
            error.assert_not_called()
            exported = pd.read_csv(target.with_suffix(".mapping.csv"))
            pd.testing.assert_frame_equal(exported, expected, check_dtype=False)
            cap = cv2.VideoCapture(str(target))
            frames = []
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                frames.append(frame)
            cap.release()
            self.assertEqual(len(frames), 7)
            self.assertLess(frames[0].mean(), 60)
            self.assertLess(frames[-1].mean(), 60)
            self.assertGreater(frames[1].mean(), 100)


if __name__ == "__main__":
    unittest.main()
