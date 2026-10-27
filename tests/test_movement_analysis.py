import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from PySide6.QtWidgets import QApplication

from movement_analysis import (prepare_speed, align_speed, duration_weights,
                               summarize_cell, pearson, lag_correlations, analyze_cells)
from movement_dialog import MovementAnalysisDialog
from sync_viewer import Viewer, TrackingAlignmentDialog
from caiman_results import CaImAnResults
from test_caiman_results import write_cnmf_fixture


class MovementMathTests(unittest.TestCase):
    def test_speed_of_known_trajectory_uses_actual_irregular_times(self):
        t = np.array([0, .02, .07, .1, .19])
        speed, runs = prepare_speed(t, np.arange(5), x=3*t, y=4*t,
                                    smoothing_s=0, max_gap_s=.1)
        np.testing.assert_allclose(speed, 5)
        self.assertEqual(len(runs), 1)

    def test_low_confidence_and_missing_coordinates_are_not_bridged(self):
        t = np.arange(8)*.05
        confidence = np.ones(8)
        confidence[3:5] = .2
        speed, runs = prepare_speed(t, np.arange(8), x=t, y=t*0,
                                    confidence=confidence, min_confidence=.9, smoothing_s=0)
        query = np.array([.05, .125, .15, .2, .225, .3])
        values = align_speed(t, speed, runs, query)
        np.testing.assert_allclose(values, [1, np.nan, np.nan, np.nan, np.nan, 1], equal_nan=True)
        self.assertEqual(len(runs), 2)

    def test_skipped_frame_ids_and_large_time_gaps_split_coverage(self):
        t = np.array([0., .05, .1, .15, .4, .45])
        speed, runs = prepare_speed(t, [0, 1, 3, 4, 5, 6], speed=np.ones(6), smoothing_s=0)
        self.assertEqual(len(runs), 3)
        result = align_speed(t, speed, runs, [-.01, .075, .3, .46])
        self.assertTrue(np.isnan(result).all())

    def test_median_smoothing_removes_single_speed_outlier(self):
        t = np.arange(7)*.03
        values = np.array([0., 0, 0, 100, 0, 0, 0])
        speed, _ = prepare_speed(t, np.arange(7), speed=values, smoothing_s=.1)
        np.testing.assert_array_equal(speed, 0)

    def test_speed_input_rejects_negative_or_missing_values(self):
        t = np.arange(8)*.02
        speed, runs = prepare_speed(t, np.arange(8), speed=[1, 1, -1, np.nan, 2, 2, 2, 2], smoothing_s=0)
        self.assertTrue(np.isnan(speed[2:4]).all())
        self.assertEqual(len(runs), 2)

    def test_duration_weighted_state_means_have_known_values(self):
        t = np.array([0., .1, .3])
        weights = duration_weights(t, max_gap_s=1)
        np.testing.assert_allclose(weights, [.05, .15, .1])
        stats = summarize_cell(np.array([0, 2, 6]), np.array([0, 1, 1]), weights, threshold=1)
        self.assertAlmostEqual(stats["mean_moving"], 3.6)
        self.assertEqual(stats["mean_rest"], 0)
        self.assertAlmostEqual(stats["moving_duration_s"], .25)
        self.assertAlmostEqual(stats["rest_duration_s"], .05)

    def test_gap_between_target_frames_is_not_counted_as_observed_time(self):
        t = np.array([0., .05, .1, .15])
        ids = np.array([0, 0, 1, 1])
        weights = duration_weights(t, .1, np.ones(4, dtype=bool), ids)
        np.testing.assert_allclose(weights, [.025, .025, .025, .025])
        self.assertAlmostEqual(weights.sum(), .1)

    def test_missing_state_and_constant_signal_produce_undefined_metrics(self):
        stats = summarize_cell(np.ones(4), np.ones(4), np.ones(4), threshold=.5)
        self.assertTrue(np.isnan(stats["mean_rest"]))
        self.assertTrue(np.isnan(stats["moving_minus_rest"]))
        self.assertTrue(np.isnan(stats["pearson_speed"]))
        self.assertTrue(np.isnan(pearson([1, 2], [1, 2])))

    def test_positive_lag_means_calcium_follows_behavior(self):
        source = np.arange(0, 5, .01)
        speed = 2 + np.sin(source*3) + .2*np.sin(source*7)
        times = np.arange(.6, 4.4, .01)
        calcium = np.interp(times-.3, source, speed)
        lags = np.arange(-.5, .501, .01)
        correlations = lag_correlations(calcium, times, source, speed, [np.arange(len(source))], lags)
        self.assertAlmostEqual(lags[np.nanargmax(correlations)], .3)
        self.assertAlmostEqual(np.nanmax(correlations), 1)

    def test_unusable_tracking_and_invalid_times_raise(self):
        for times in ([0, 0, 1], [0, 2, 1]):
            with self.assertRaises(ValueError):
                prepare_speed(times, [0, 1, 2], speed=np.ones(3))
        with self.assertRaises(ValueError):
            prepare_speed([0, .1], [0, 1], speed=[np.nan, np.nan])

    def test_intervals_at_gap_limit_tolerate_float_rounding(self):
        times = np.arange(12)*.1
        _, runs = prepare_speed(times, np.arange(12), speed=np.ones(12),
                                max_gap_s=.1, smoothing_s=0)
        self.assertEqual(len(runs), 1)
        self.assertAlmostEqual(duration_weights(times, .1).sum(), 1.1)


class MovementWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.hdf = self.root/"cnmf.h5"
        write_cnmf_fixture(self.hdf)
        self.v = Viewer()
        times = np.arange(6)*50.
        self.v.mini_df = pd.DataFrame({"frame": np.arange(1, 7), "timestamp_ms": times+1000})
        self.v.camera_df = self.v.mini_df.copy()
        self.v.rebuild()
        self.v.set_caiman_results(self.hdf)
        self.path = self.root/"tracking.csv"
        pd.DataFrame({"frame_index": np.arange(6), "x": [0, 0, 1, 3, 5, 7],
                      "y": np.zeros(6), "speed": [0, 0, 10, 30, 40, 50],
                      "likelihood": np.ones(6)}).to_csv(self.path, index=False)
        self.d = MovementAnalysisDialog(self.v, TrackingAlignmentDialog)
        self.d.load_tracking_path(self.path)
        self.d.input_mode.setCurrentIndex(1)
        self.d.speed_column.setCurrentIndex(self.d.speed_column.findData("speed"))
        self.d.smoothing.setValue(0)

    def tearDown(self):
        self.d.tracking_reader.close()
        self.d.close()
        self.v.close()
        self.folder.cleanup()

    def analyze(self):
        with patch("movement_dialog.QMessageBox.warning") as warning:
            self.d.run_analysis()
        warning.assert_not_called()
        self.assertIsNotNone(self.d.summary)

    def test_summary_uses_quality_ids_and_expected_state_means(self):
        self.analyze()
        np.testing.assert_array_equal(self.d.summary.roi_id_zero_based, [0, 2])
        # Equal 50ms sampling: resting weights .025,.05,.05; moving .05,.05,.025.
        row = self.d.summary.iloc[0]
        self.assertAlmostEqual(row.mean_rest, (.1*.05+.4*.05)/.125, places=6)
        self.assertAlmostEqual(row.mean_moving, (.2*.05+.1*.05)/.125, places=6)
        self.assertEqual(row.valid_frames, 6)
        self.assertTrue(self.d.export_btn.isEnabled())

    def test_setting_and_source_changes_invalidate_export(self):
        for change in (lambda: self.d.threshold.setValue(self.d.threshold.value()+1),
                       lambda: self.v.calcium_first_frame.setValue(2), self.v.rebuild):
            self.analyze()
            change()
            self.assertIsNone(self.d.summary)
            self.assertFalse(self.d.export_btn.isEnabled())

    def test_frame_mapping_and_trim_exclude_uncovered_calcium(self):
        self.v.calcium_first_frame.setValue(3)
        self.v.set_time(150)
        self.v.set_trim_current()
        self.analyze()
        np.testing.assert_array_equal(self.d.behavior.mini2p_frame, [1, 2, 3, 4])
        self.assertEqual(self.d.summary.iloc[0].valid_frames, 2)
        self.assertAlmostEqual(self.d.summary.iloc[0].moving_duration_s, .025)
        self.assertAlmostEqual(self.d.summary.iloc[0].rest_duration_s, .025)

    def test_export_includes_all_cells_alignment_lag_and_provenance(self):
        self.analyze()
        with patch("movement_dialog.QFileDialog.getExistingDirectory", return_value=str(self.root)), \
             patch("movement_dialog.QMessageBox.information"):
            self.d.export_analysis()
        folder = next(self.root.glob("movement_*"))
        summary = pd.read_csv(folder/"per_cell_summary.csv")
        self.assertEqual(len(summary), 2)
        self.assertTrue((folder/"roi_0_aligned.csv").exists())
        settings = json.loads((folder/"analysis_settings.json").read_text())
        self.assertEqual(settings["tracking_csv"], str(self.path.resolve()))
        self.assertEqual(settings["units"], "px")
        self.assertNotIn("p_value", summary.columns)
        self.assertEqual(len(pd.read_csv(folder/"aligned_movement.csv")), 6)

    def test_empty_quality_and_no_overlap_disable_export(self):
        self.d.quality.setCurrentIndex(2)
        self.analyze()  # Fixture ROI 1 is rejected.
        self.v.calcium_first_frame.setValue(100)
        with patch("movement_dialog.QMessageBox.warning") as warning:
            self.d.run_analysis()
        warning.assert_called_once()
        self.assertIsNone(self.d.summary)
        self.assertFalse(self.d.export_btn.isEnabled())

    def test_new_calcium_file_refreshes_signal_choices_and_invalidates(self):
        self.analyze()
        import h5py
        with h5py.File(self.hdf, "a") as file:
            del file["estimates/F_dff"]
        self.v.set_caiman_results(self.hdf)
        self.assertIsNone(self.d.summary)
        self.assertEqual(self.d.signal.findData("F_dff"), -1)

    def test_confidence_gap_is_unknown_not_rest(self):
        table = pd.read_csv(self.path)
        table.loc[2:3, "likelihood"] = .1
        table.to_csv(self.path, index=False)
        self.d.load_tracking_path(self.path)
        self.analyze()
        self.assertTrue((self.d.behavior.state.iloc[2:4] == "unknown").all())
        self.assertTrue(self.d.behavior.speed.iloc[2:4].isna().all())

    def test_axes_keep_explicit_seconds_and_signal_scale_after_theme_change(self):
        self.analyze()
        for day in (True, False):
            self.d.apply_theme(day)
            self.d.activity_plot.setXRange(0, .25, padding=0)
            self.d.state_plot.setYRange(0, .01, padding=0)
            self.d.show()
            self.app.processEvents()
            self.assertEqual(self.d.activity_plot.getAxis("bottom").labelUnits, "s")
            self.assertEqual(self.d.activity_plot.getAxis("bottom").autoSIPrefixScale, 1)
            self.assertEqual(self.d.state_plot.getAxis("left").autoSIPrefixScale, 1)

    def test_settings_changed_during_progress_prevent_stale_results(self):
        def change_threshold():
            self.d.threshold.setValue(self.d.threshold.value()+1)
        with patch("movement_dialog.QApplication.processEvents", side_effect=change_threshold), \
             patch("movement_dialog.QMessageBox.warning") as warning:
            self.d.run_analysis()
        warning.assert_not_called()
        self.assertIsNone(self.d.summary)
        self.assertFalse(self.d.export_btn.isEnabled())
        self.assertIn("cancelled", self.d.status.text())


if __name__ == "__main__":
    unittest.main()
