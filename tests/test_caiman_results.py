import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import h5py
import numpy as np
import pandas as pd
from PySide6.QtWidgets import QApplication

from caiman_results import CaImAnResults
from sync_viewer import Viewer


def write_cnmf_fixture(path, sparse=True, quality=True):
    """Use CaImAn's CNMF.save layout, including CSC and NoneType values."""
    dims = (32, 40)
    c = np.array([[0, 1, 4, 2, 1, 0], [1, 0, 2, 5, 3, 1], [2, 1, 0, 1, 4, 2]], dtype=np.float32)
    footprints = np.zeros((*dims, 3), dtype=np.float32)
    footprints[5:11, 8:15, 0] = 1
    footprints[15:22, 25:32, 1] = 2
    footprints[22:28, 10:16, 2] = 1.5
    a = footprints.reshape((-1, 3), order="F")
    with h5py.File(path, "w") as file:
        file["dims"] = dims
        e = file.create_group("estimates")
        e["dims"] = dims
        e["C"] = c
        e["YrA"] = np.ones_like(c) * .1
        e["F_dff"] = c / 10
        e["S"] = (c >= 4).astype(np.float32)
        e["Cn"] = np.indices(dims).sum(axis=0).astype(np.float32)
        e["idx_components"] = [0, 2] if quality else "NoneType"
        e["idx_components_bad"] = [1] if quality else "NoneType"
        if sparse:
            group = e.create_group("A")
            indices, data, ptr = [], [], [0]
            for component in range(3):
                nonzero = np.flatnonzero(a[:, component])
                indices.extend(nonzero)
                data.extend(a[nonzero, component])
                ptr.append(len(data))
            group["data"] = np.asarray(data, dtype=np.float32)
            group["indices"] = np.asarray(indices, dtype=np.int32)
            group["indptr"] = np.asarray(ptr, dtype=np.int32)
            group["shape"] = a.shape
        else:
            e["A"] = a
    return c, footprints


class CaImAnResultsTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.path = Path(self.folder.name) / "cnmf.hdf5"
        self.c, self.footprints = write_cnmf_fixture(self.path)

    def tearDown(self):
        self.folder.cleanup()

    def test_native_sparse_layout_preserves_spatial_orientation_and_ids(self):
        results = CaImAnResults(self.path)
        self.assertEqual(results.dims, (32, 40))
        np.testing.assert_array_equal(results.component_ids("accepted"), [0, 2])
        np.testing.assert_array_equal(results.component_ids("rejected"), [1])
        for component in range(3):
            np.testing.assert_array_equal(results.footprint(component), self.footprints[:, :, component])
        self.assertEqual(results.quality(1), "rejected")
        self.assertEqual(results.reference_image().shape, (32, 40))

    def test_dense_footprints_and_missing_quality_evaluation(self):
        write_cnmf_fixture(self.path, sparse=False, quality=False)
        results = CaImAnResults(self.path)
        np.testing.assert_array_equal(results.footprint(2), self.footprints[:, :, 2])
        self.assertEqual(results.quality(0), "unreviewed")
        self.assertEqual(len(results.component_ids("all")), 3)
        self.assertEqual(len(results.component_ids("accepted")), 0)

    def test_trace_types_are_imported_without_recomputing(self):
        results = CaImAnResults(self.path)
        np.testing.assert_array_equal(results.trace(0, "C"), self.c[0])
        np.testing.assert_allclose(results.trace(0, "C+YrA"), self.c[0] + .1)
        np.testing.assert_allclose(results.trace(0, "F_dff"), self.c[0] / 10)
        np.testing.assert_array_equal(results.trace(0, "S"), self.c[0] >= 4)

    def test_optional_none_datasets_are_not_treated_as_traces(self):
        with h5py.File(self.path, "a") as file:
            for key in ("YrA", "S", "F_dff"):
                del file["estimates"][key]
                file[f"estimates/{key}"] = "NoneType"
        results = CaImAnResults(self.path)
        self.assertEqual(results.trace_types, ["C"])
        with self.assertRaises(ValueError):
            results.trace(0, "F_dff")

    def test_frame_mapping_uses_frame_ids_and_keeps_out_of_range_empty(self):
        results = CaImAnResults(self.path)
        trace = results.trace(0, "C")
        values, covered = results.mapped_trace(trace, [1, 3, 6, 7])
        np.testing.assert_allclose(values, [0, 4, 0, np.nan], equal_nan=True)
        np.testing.assert_array_equal(covered, [True, True, True, False])
        values, _ = results.mapped_trace(trace, [1, 3, 6, 7], first_frame=3)
        np.testing.assert_allclose(values, [np.nan, 0, 2, 1], equal_nan=True)
        for frames in ([0, 1], [1, 1], [2, 1], [1, 2.5], [1, np.nan]):
            with self.assertRaises(ValueError):
                results.mapped_trace(trace, frames)

    def test_bad_shapes_and_csc_pointers_are_rejected(self):
        with h5py.File(self.path, "a") as file:
            del file["estimates/S"]
            file["estimates/S"] = np.zeros((3, 5))
        with self.assertRaisesRegex(ValueError, "shape"):
            CaImAnResults(self.path)
        write_cnmf_fixture(self.path)
        with h5py.File(self.path, "a") as file:
            file["estimates/A/indptr"][1] = 100000
        with self.assertRaisesRegex(ValueError, "pointers"):
            CaImAnResults(self.path)

    def test_missing_spatial_data_still_allows_trace_loading(self):
        with h5py.File(self.path, "a") as file:
            del file["estimates/A"]
        results = CaImAnResults(self.path)
        self.assertFalse(results.spatial)
        self.assertIsNone(results.footprint(0))
        np.testing.assert_array_equal(results.trace(1, "C"), self.c[1])

    def test_non_cnmf_file_is_rejected(self):
        with h5py.File(self.path, "w") as file:
            file["movie"] = np.ones((2, 3, 4))
        with self.assertRaisesRegex(ValueError, "CNMF"):
            CaImAnResults(self.path)


class CalciumViewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.path = Path(self.folder.name) / "cnmf.h5"
        self.c, _ = write_cnmf_fixture(self.path)
        self.v = Viewer()
        self.v.mini_df = pd.DataFrame({"frame": [1, 3, 4, 6], "timestamp_ms": [100., 122., 131., 154.]})
        self.v.camera_df = pd.DataFrame({"frame": np.arange(1, 7), "timestamp_ms": np.arange(100., 160., 10.)})
        self.v.rebuild()
        self.v.set_caiman_results(self.path)

    def tearDown(self):
        self.v.close()
        self.folder.cleanup()

    def test_quality_selection_retains_original_component_ids(self):
        self.assertEqual(self.v.calcium_component.count(), 2)
        self.v.calcium_component.setCurrentIndex(1)
        self.assertEqual(self.v.calcium_component.currentData(), 2)
        np.testing.assert_allclose(self.v.calcium_trace, self.c[2] / 10)
        self.v.calcium_filter.setCurrentIndex(2)
        self.assertEqual(self.v.calcium_component.currentData(), 1)
        self.assertIsNotNone(self.v.mini_panel.roi_path)

    def test_cursor_moves_all_views_without_changing_trace_samples(self):
        table = self.v.calcium_trace_table()
        np.testing.assert_array_equal(table.time_ms, [0, 22, 31, 54])
        np.testing.assert_allclose(table.value, self.c[0, [0, 2, 3, 5]] / 10)
        self.v.video.cap = Mock()
        self.v.video.cap.read.return_value = (False, None)
        self.v.video.count = 6
        self.v.calcium_cursor.setValue(31)
        self.assertEqual(self.v.current_t, 31)
        self.assertEqual(self.v.cursor_line.value(), 31)
        self.v.cursor_line.setValue(22)
        self.assertEqual(self.v.calcium_cursor.value(), 22)
        self.v.step_mini(1)
        self.assertEqual(self.v.current_t, 31)

    def test_plot_ranges_match_in_both_directions(self):
        self.v.plot.setXRange(12, 42, padding=0)
        np.testing.assert_allclose(self.v.calcium_plot.viewRange()[0], [12, 42])
        self.v.calcium_plot.setXRange(-10, 80, padding=0)
        np.testing.assert_allclose(self.v.plot.viewRange()[0], [-10, 80])

    def test_roi_visibility_does_not_change_trace_or_source_image(self):
        trace = self.v.calcium_trace.copy()
        reference = self.v.calcium_reference.copy()
        self.v.calcium_roi.setChecked(False)
        self.assertIsNone(self.v.mini_panel.roi_path)
        self.v.calcium_roi.setChecked(True)
        self.assertIsNotNone(self.v.mini_panel.roi_path)
        np.testing.assert_array_equal(self.v.calcium_reference, reference)
        np.testing.assert_array_equal(self.v.calcium_trace, trace)

    def test_tiff_dimension_mismatch_is_reported_without_resizing_footprints(self):
        self.v.tiff.tif = Mock()
        self.v.tiff.read = Mock(return_value=np.ones((16, 20), dtype=np.uint8))
        self.v.update_views()
        self.v.refresh_calcium_trace()
        self.assertIn("dimensions differ", self.v.calcium_status.text())
        self.assertEqual(self.v.mini_panel.roi_shape, (32, 40))
        self.assertEqual((self.v.mini_panel.pm.height(), self.v.mini_panel.pm.width()), (16, 20))

    def test_trim_and_first_frame_mapping_are_applied_to_export(self):
        self.v.calcium_first_frame.setValue(3)
        self.v.set_time(30)
        self.v.set_trim_current()
        table = self.v.calcium_trace_table()
        np.testing.assert_array_equal(table.mini2p_frame, [1, 3])
        self.assertTrue(np.isnan(table.value.iloc[0]))
        self.assertEqual(table.caiman_sample_zero_based.iloc[1], 0)
        self.assertIn("Frame counts differ", self.v.calcium_status.text())
        output = Path(self.folder.name) / "trace.csv"
        with patch("sync_viewer.QFileDialog.getSaveFileName", return_value=(str(output), "")):
            self.v.export_calcium_trace()
        pd.testing.assert_frame_equal(pd.read_csv(output), table, check_dtype=False)

    def test_empty_quality_filter_clears_trace_and_overlay(self):
        with h5py.File(self.path, "a") as file:
            del file["estimates/idx_components_bad"]
            file["estimates/idx_components_bad"] = np.array([], dtype=int)
        self.v.set_caiman_results(self.path)
        self.v.calcium_filter.setCurrentIndex(2)
        self.assertIsNone(self.v.calcium_trace)
        self.assertIsNone(self.v.mini_panel.roi_path)
        self.assertFalse(self.v.calcium_export.isEnabled())
        x, _ = self.v.calcium_curve.getData()
        self.assertTrue(x is None or len(x) == 0)

    def test_loading_before_ttls_then_rebuilding_enables_sync(self):
        other = Viewer()
        try:
            other.set_caiman_results(self.path)
            self.assertIn("TTL coverage 0/6", other.calcium_status.text())
            self.assertTrue(other.calcium_export.isEnabled())
            x, values = other.calcium_curve.getData()
            np.testing.assert_array_equal(x, np.arange(1, 7))
            np.testing.assert_allclose(values, self.c[0] / 10)
            self.assertTrue(other.calcium_trace_table().time_ms.isna().all())
            other.mini_df = self.v.mini_df.copy()
            other.rebuild()
            self.assertTrue(other.calcium_export.isEnabled())
            self.assertFalse(other.calcium_movie_mode)
            other.calcium_first_frame.setValue(100)
            self.assertFalse(other.calcium_export.isEnabled())
        finally:
            other.close()

    def test_invalid_replacement_preserves_current_results(self):
        previous = self.v.caiman
        invalid = Path(self.folder.name) / "bad.h5"
        with h5py.File(invalid, "w"):
            pass
        with self.assertRaises(ValueError):
            self.v.set_caiman_results(invalid)
        self.assertIs(self.v.caiman, previous)


if __name__ == "__main__":
    unittest.main()
