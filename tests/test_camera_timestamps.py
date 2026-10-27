import unittest

import numpy as np
import pandas as pd

from sync_viewer import fill_camera_timestamps, virtual_camera_indices


class CameraTimestampTests(unittest.TestCase):
    def camera(self, times):
        return pd.DataFrame({
            "frame": np.arange(1, len(times) + 1),
            "timestamp_ms": times,
            "elapsed_ms": np.asarray(times) - times[0],
        })

    def test_fills_single_and_multiple_missing_frames(self):
        source = self.camera([100., 110., 130., 140., 180., 190., 200.])
        original = source.copy(deep=True)
        result = fill_camera_timestamps(source)
        np.testing.assert_allclose(result.timestamp_ms, np.arange(100., 201., 10.))
        np.testing.assert_array_equal(result.frame, np.arange(1, 12))
        np.testing.assert_allclose(result.elapsed_ms, np.arange(0., 101., 10.))
        pd.testing.assert_frame_equal(source, original)

    def test_uses_measured_endpoints_with_jitter(self):
        source = self.camera([100., 110., 130.4, 140.4, 150.4])
        result = fill_camera_timestamps(source)
        self.assertAlmostEqual(result.timestamp_ms.iloc[2], 120.2)
        original_indices = virtual_camera_indices(source.timestamp_ms.to_numpy())
        np.testing.assert_array_equal(result.timestamp_ms.iloc[original_indices], source.timestamp_ms)

    def test_regular_or_single_frame_data_is_unchanged(self):
        for times in ([100.], [100., 110., 120., 130.]):
            source = self.camera(times)
            pd.testing.assert_frame_equal(fill_camera_timestamps(source), source)

    def test_repeated_repair_does_not_insert_more_rows(self):
        source = self.camera([100., 110., 130., 140., 150.])
        result = fill_camera_timestamps(source)
        pd.testing.assert_frame_equal(fill_camera_timestamps(result), result)
        np.testing.assert_array_equal(virtual_camera_indices(result.timestamp_ms.to_numpy()),
                                      np.arange(len(result)))

    def test_preserves_columns_and_does_not_extend_recording(self):
        source = self.camera([100., 110., 130., 140., 150.]).drop(columns="elapsed_ms")
        source["frame"] += 9
        result = fill_camera_timestamps(source)
        self.assertEqual(list(result.columns), list(source.columns))
        self.assertEqual(result.timestamp_ms.iloc[0], 100.)
        self.assertEqual(result.timestamp_ms.iloc[-1], 150.)
        np.testing.assert_array_equal(result.frame, np.arange(10, 16))


if __name__ == "__main__":
    unittest.main()
