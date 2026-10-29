import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import csv
from dataclasses import asdict
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
import h5py
import tifffile
from PySide6.QtCore import QEvent, QEventLoop, QProcess, QTimer
from PySide6.QtWidgets import QApplication

from calcium_pipeline import PipelineSettings, inspect_sources, inspect_tiff, prepare_movie, run_pipeline
from processing_dialog import CalciumProcessingDialog
from cali import Viewer
from test_caiman_results import write_cnmf_fixture


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def source(self, name, offset=0, channels=2):
        path = self.root / name
        data = np.arange(100 * channels, dtype=np.int16)[:, None, None] + np.zeros((32, 40), dtype=np.int16) + offset
        tifffile.imwrite(path, data, photometric="minisblack", metadata=None)
        return path, data

    def settings(self, sources, **kwargs):
        return PipelineSettings(sources=list(map(str, sources)), output=str(self.root / "run"),
                                frame_rate=20, single_plane_confirmed=True, **kwargs)

    def test_two_channel_multifile_selection_preserves_source_values_and_provenance(self):
        one, a = self.source("one.tif", offset=-40)
        two, b = self.source("two.tif", offset=1000)
        settings = self.settings([one, two], channels=2, channel_index=1, first_mini_frame=11)
        layouts, count = inspect_sources(settings)
        self.assertEqual(count, 200)
        out = self.root / "prepared"
        out.mkdir()
        prepared = prepare_movie(settings, layouts, out)
        np.testing.assert_array_equal(tifffile.imread(prepared), np.concatenate([a[1::2], b[1::2]]))
        with (out / "frame_mapping.csv").open() as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[100]["source_tiff"], str(two.resolve()))
        self.assertEqual(rows[100]["source_page_zero_based"], "1")
        self.assertEqual(rows[100]["mini2p_frame"], "111")
        np.testing.assert_array_equal(tifffile.imread(one), a)

    def test_rejects_incomplete_channel_cycles_and_unconfirmed_plane(self):
        path, _ = self.source("one.tif")
        settings = self.settings([path], channels=3)
        with self.assertRaisesRegex(ValueError, "complete channel cycles"):
            inspect_sources(settings)
        settings.channels = 2
        settings.single_plane_confirmed = False
        with self.assertRaisesRegex(ValueError, "single imaging plane"):
            inspect_sources(settings)

    def test_explicit_tcyx_axes_are_supported_but_channel_count_must_match(self):
        path = self.root / "channels.tif"
        tifffile.imwrite(path, np.zeros((100, 2, 32, 40), np.int16),
                         photometric="minisblack", metadata={"axes": "TCYX"})
        self.assertEqual(inspect_sources(self.settings([path], channels=2))[1], 100)
        with self.assertRaisesRegex(ValueError, "channel axis"):
            inspect_sources(self.settings([path]))

    def test_rgb_and_multiplane_axes_are_rejected(self):
        rgb = self.root / "rgb.tif"
        tifffile.imwrite(rgb, np.zeros((32, 40, 3), np.uint8), photometric="rgb")
        with self.assertRaises(ValueError):
            inspect_tiff(rgb)
        volume = self.root / "volume.tif"
        tifffile.imwrite(volume, np.zeros((100, 2, 32, 40), np.int16),
                         photometric="minisblack", metadata={"axes": "TZYX"})
        with self.assertRaises(ValueError):
            inspect_tiff(volume)

    def test_scanimage_channel_metadata_and_multiplane_guards(self):
        path, _ = self.source("scanimage.tif")
        metadata = {"FrameData": {"SI.hChannels.channelSave": [1, 3],
                                  "SI.hRoiManager.scanFrameRate": 15,
                                  "SI.hStackManager.numSlices": 1}}
        with patch.object(tifffile.TiffFile, "is_scanimage", True, create=True), \
             patch.object(tifffile.TiffFile, "scanimage_metadata", metadata):
            settings = self.settings([path], channels=2)
            layouts, _ = inspect_sources(settings)
            self.assertEqual(layouts[0]["channel_ids"], [1, 3])
            metadata["FrameData"]["SI.hStackManager.numSlices"] = 2
            with self.assertRaisesRegex(ValueError, "multiple imaging planes"):
                inspect_tiff(path)

    def test_existing_output_is_not_overwritten(self):
        path, _ = self.source("one.tif", channels=1)
        settings = self.settings([path])
        out = Path(settings.output)
        out.mkdir()
        (out / "keep.txt").write_text("keep")
        with self.assertRaises(FileExistsError):
            run_pipeline(settings)
        self.assertEqual((out / "keep.txt").read_text(), "keep")

    def test_missing_engine_leaves_failed_manifest_with_source_checksum(self):
        path, original = self.source("one.tif", channels=1)
        settings = self.settings([path])
        with patch.dict(sys.modules, {"caiman": None}):
            with self.assertRaises(ImportError):
                run_pipeline(settings, progress=lambda _: None)
        manifest = json.loads((Path(settings.output) / "processing.json").read_text())
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(len(manifest["sources"][0]["sha256"]), 64)
        self.assertEqual(manifest["outputs"], {})
        np.testing.assert_array_equal(tifffile.imread(path), original)


class ProcessingWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.viewer = Viewer()
        self.dialog = CalciumProcessingDialog(self.viewer)

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        self.viewer.close()
        self.viewer.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.temp.cleanup()

    def complete_result(self, prefix=""):
        result_path = self.root / f"{prefix}result.hdf5"
        write_cnmf_fixture(result_path)
        movie_path = self.root / f"{prefix}corrected.tif"
        tifffile.imwrite(movie_path, np.ones((6, 32, 40), np.float32), photometric="minisblack")
        return {"status": "complete", "settings": {"first_mini_frame": 7},
                "frames": 6, "components": 3, "accepted": 2,
                "outputs": {"results": str(result_path), "prepared_tiff": str(movie_path), "corrected_tiff": str(movie_path)}}

    def test_open_result_uses_corrected_coordinates_and_frame_origin(self):
        data = self.complete_result()
        self.viewer.open_processing_result(data)
        self.assertEqual(self.viewer.tiff_first_frame, 7)
        self.assertEqual(self.viewer.calcium_first_frame.value(), 7)
        self.assertEqual(self.viewer.caiman.n_frames, 6)
        np.testing.assert_array_equal(self.viewer.tiff.read(0), np.ones((32, 40)))

    def test_complete_job_loads_results_automatically_but_failure_does_not(self):
        data = self.complete_result()
        self.dialog.output = self.root
        self.dialog.show()
        (self.root / "processing.json").write_text(json.dumps(data))
        self.dialog.worker_finished(0, QProcess.NormalExit)
        self.assertIsNotNone(self.dialog.result)
        self.assertEqual(self.viewer.caiman.n_frames, 6)
        self.assertEqual(self.viewer.tiff_first_frame, 7)
        self.assertFalse(self.dialog.isVisible())
        self.assertEqual(self.viewer.timeline_tabs.currentIndex(), 1)
        with patch.object(self.viewer, "open_processing_result") as load:
            self.dialog.worker_finished(1, QProcess.NormalExit)
        load.assert_not_called()
        self.assertIsNone(self.dialog.result)

    def test_cancel_marks_partial_result_and_never_enables_load(self):
        self.dialog.output = self.root
        (self.root / "processing.json").write_text(json.dumps({"status": "running"}))
        self.dialog.cancelled = True
        self.dialog.worker_finished(15, QProcess.CrashExit)
        self.assertEqual(json.loads((self.root / "processing.json").read_text())["status"], "cancelled")
        self.assertIsNone(self.dialog.result)

    def test_real_subprocess_can_be_cancelled_without_blocking_qt(self):
        self.dialog.output = self.root
        (self.root / "processing.json").write_text(json.dumps({"status": "running"}))
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        self.dialog.process.finished.connect(loop.quit)
        self.dialog.process.started.connect(self.dialog.cancel)
        self.dialog.process.start(sys.executable, ["-u", "-c", "import time; time.sleep(30)"])
        timer.start(5000)
        loop.exec()
        timer.stop()
        if self.dialog.is_running():
            self.dialog.process.kill()
            self.dialog.process.waitForFinished(1000)
            self.fail("Cancellation did not stop the worker within five seconds.")
        self.assertTrue(self.dialog.cancelled)
        self.assertTrue(self.dialog.inputs.isEnabled())
        self.assertEqual(self.dialog.run_button.text(), "Run analysis")
        self.assertIsNone(self.dialog.result)
        self.assertEqual(json.loads((self.root / "processing.json").read_text())["status"], "cancelled")

    def test_loaded_tiff_and_ttl_rate_are_reused_without_file_picker(self):
        path = self.root / "loaded.tif"
        tifffile.imwrite(path, np.zeros((100, 32, 40), np.uint16), photometric="minisblack")
        self.viewer.tiff.open(path)
        self.viewer.mini_t = np.arange(100) * 50.
        self.dialog.sync_source_from_viewer()
        self.assertEqual(self.dialog.sources, [str(path.resolve())])
        self.assertEqual(self.dialog.settings("unused").frame_rate, 20)
        self.assertTrue(self.dialog.run_button.isEnabled())
        self.dialog.remove_sources()
        self.assertEqual(self.dialog.sources, [])
        self.assertFalse(self.dialog.run_button.isEnabled())

    @patch.object(CalciumProcessingDialog, "default_engine_python", return_value=sys.executable)
    def test_both_channels_schedule_separate_jobs_and_do_not_merge_results(self, engine_python):
        path = self.root / "two_channels.tif"
        tifffile.imwrite(path, np.zeros((100, 2, 32, 40), np.uint16),
                         photometric="minisblack", metadata={"axes": "TCYX"})
        self.dialog.sources = [str(path)]
        self.dialog.refresh_sources()
        self.dialog.frame_rate.setCurrentText("20")
        self.dialog.channel.setCurrentIndex(self.dialog.channel.findData(-1))
        with patch.object(self.dialog, "launch_job") as launch:
            self.dialog.start()
        launch.assert_called_once_with(sys.executable)
        self.assertEqual([job.channel_index for job in self.dialog.jobs], [0, 1])
        self.assertTrue(all(job.channels == 2 for job in self.dialog.jobs))
        one = self.complete_result("one_")
        one["settings"]["channel_index"] = 0
        one_out = Path(self.dialog.jobs[0].output)
        one_out.mkdir()
        (one_out / "processing.json").write_text(json.dumps(one))
        self.dialog.output = one_out
        with patch.object(self.dialog, "launch_job") as launch:
            self.dialog.worker_finished(0, QProcess.NormalExit)
        launch.assert_called_once()
        self.assertEqual(self.dialog.job_index, 1)
        self.assertEqual(len(self.dialog.completed_results), 1)
        two = self.complete_result("two_")
        two["settings"]["channel_index"] = 1
        two_out = Path(self.dialog.jobs[1].output)
        two_out.mkdir()
        (two_out / "processing.json").write_text(json.dumps(two))
        self.dialog.output = two_out
        self.dialog.worker_finished(0, QProcess.NormalExit)
        self.assertEqual(self.dialog.result_channel.count(), 2)
        self.dialog.result_channel.setCurrentIndex(1)
        self.assertEqual(self.dialog.result["settings"]["channel_index"], 1)
        self.assertEqual(self.viewer.calcium_channel.count(), 2)
        self.viewer.calcium_channel.setCurrentIndex(0)
        self.assertEqual(self.viewer.caiman.path, Path(one["outputs"]["results"]).resolve())
        self.viewer.calcium_channel.setCurrentIndex(1)
        self.assertEqual(self.viewer.caiman.path, Path(two["outputs"]["results"]).resolve())
        batch = json.loads((self.dialog.run_root / "batch.json").read_text())
        self.assertEqual(batch["status"], "complete")
        self.assertEqual(len(batch["completed_results"]), 2)

    def test_processed_movie_and_all_signals_are_visible_without_ttls(self):
        data = self.complete_result()
        self.viewer.show_processing_results([data])
        self.assertIn("motion corrected", self.viewer.mini_panel.title_label.text())
        self.assertIsNotNone(self.viewer.mini_panel.pm)
        self.assertIsNotNone(self.viewer.mini_panel.roi_path)
        self.assertEqual(self.viewer.calcium_frame.maximum(), 6)
        for signal in self.viewer.caiman.trace_types:
            self.viewer.calcium_signal.setCurrentIndex(self.viewer.calcium_signal.findData(signal))
            frames, values = self.viewer.calcium_curve.getData()
            np.testing.assert_array_equal(frames, np.arange(1, 7))
            np.testing.assert_allclose(values, self.viewer.caiman.trace(0, signal))
        with patch.object(self.viewer.tiff, "read", wraps=self.viewer.tiff.read) as read:
            self.viewer.calcium_slider.setValue(5)
            read.assert_called_with(5)
        self.assertEqual(self.viewer.calcium_frame.value(), 6)
        self.assertEqual(self.viewer.calcium_cursor.value(), 6)
        self.assertIsNone(self.viewer.cam_panel.pm)
        self.assertTrue(self.viewer.calcium_trace_table().time_ms.isna().all())
        with patch.object(self.viewer.tiff, "read", wraps=self.viewer.tiff.read) as read:
            self.viewer.calcium_first_frame.setValue(50)
            read.assert_called_with(5)

    def test_partial_ttls_do_not_hide_movie_samples_or_invent_behavior_times(self):
        data = self.complete_result()
        self.viewer.mini_df = pd.DataFrame({"frame": [7, 8], "timestamp_ms": [1000., 1050.]})
        self.viewer.camera_df = self.viewer.mini_df.copy()
        self.viewer.rebuild()
        self.viewer.show_processing_results([data])
        frames, values = self.viewer.calcium_curve.getData()
        self.assertEqual(len(frames), 6)
        self.viewer.set_calcium_sample(1)
        self.assertEqual(self.viewer.current_t, 50)
        self.viewer.set_calcium_sample(5)
        self.assertEqual(self.viewer.calcium_sample_index, 5)
        self.assertIn("Movie frame 6/6", self.viewer.mini_panel.image.toolTip())
        self.assertIn("No synchronized behavior time", self.viewer.cam_panel.image.toolTip())
        times = self.viewer.calcium_trace_table().time_ms.to_numpy()
        np.testing.assert_allclose(times[:2], [0, 50])
        self.assertTrue(np.isnan(times[2:]).all())
        self.viewer.calcium_cursor.setValue(3)
        self.assertEqual(self.viewer.calcium_sample_index, 2)
        self.viewer.trim_idx = 1
        trimmed = self.viewer.calcium_trace_table()
        np.testing.assert_array_equal(trimmed.mini2p_frame, [7, 8])
        np.testing.assert_allclose(trimmed.time_ms, [0, 50])

    def test_zero_accepted_components_show_candidates_with_their_actual_quality(self):
        data = self.complete_result()
        with h5py.File(data["outputs"]["results"], "a") as file:
            del file["estimates/idx_components"]
            del file["estimates/idx_components_bad"]
            file["estimates/idx_components"] = np.array([], dtype=int)
            file["estimates/idx_components_bad"] = np.arange(3)
        self.viewer.show_processing_results([data])
        self.assertEqual(self.viewer.calcium_filter.currentData(), "all")
        self.assertEqual(self.viewer.calcium_component.count(), 3)
        self.assertEqual(self.viewer.caiman.quality(0), "rejected")
        self.assertIn("No components passed", self.viewer.calcium_status.text())
        self.assertIsNotNone(self.viewer.calcium_trace)

    def test_movie_playback_updates_frame_and_stops_at_end(self):
        self.viewer.show_processing_results([self.complete_result()])
        self.viewer.calcium_play.setChecked(True)
        self.assertTrue(self.viewer.playback_timer.isActive())
        self.viewer.advance_calcium_movie()
        self.assertEqual(self.viewer.calcium_sample_index, 1)
        self.viewer.set_calcium_sample(5)
        self.viewer.advance_calcium_movie()
        self.assertFalse(self.viewer.playback_timer.isActive())
        self.assertFalse(self.viewer.calcium_play.isChecked())

    def test_saved_result_can_reopen_corrected_movie_from_its_hdf5(self):
        data = self.complete_result()
        (self.root / "processing.json").write_text(json.dumps(data))
        with patch.object(self.viewer, "choose", return_value=data["outputs"]["results"]):
            self.viewer.load_caiman()
        self.assertEqual(self.viewer.processing_manifest["status"], "complete")
        self.assertIn("motion corrected", self.viewer.mini_panel.title_label.text())

    def test_acquisition_rate_typo_is_rejected_before_starting_a_job(self):
        settings = PipelineSettings(sources=["source.tif"], output="unused", frame_rate=20000,
                                    single_plane_confirmed=True)
        with self.assertRaisesRegex(ValueError, "acquisition rate"):
            settings.validate()


if __name__ == "__main__":
    unittest.main()
