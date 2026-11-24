"""Check frame/crop correspondence across the extracted video export boundary."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from cali.video_exports import write_video_prefix, write_aligned_video


class VideoExportTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.source = self.root / "source.mp4"
        writer = cv2.VideoWriter(str(self.source), cv2.VideoWriter_fourcc(*"mp4v"),
                                 20, (64, 48))
        self.assertTrue(writer.isOpened())
        try:
            for level in (30, 80, 130, 180):
                frame = np.full((48, 64, 3), level, dtype=np.uint8)
                frame[:, :16] = 0
                writer.write(frame)
        finally:
            writer.release()

    def frames(self, path):
        cap = cv2.VideoCapture(str(path))
        self.assertTrue(cap.isOpened())
        try:
            frames = []
            while True:
                ok, frame = cap.read()
                if not ok:
                    return frames
                frames.append(frame)
        finally:
            cap.release()

    def test_trim_and_crop_keep_source_prefix_and_coordinates(self):
        for crop in (None, (16, 8, 32, 24)):
            with self.subTest(crop=crop):
                destination = self.root / ("crop.mp4" if crop else "trim.mp4")
                written, cancelled = write_video_prefix(
                    self.source, destination, 3, crop=crop, progress=lambda _: False)
                self.assertEqual((written, cancelled), (3, False))
                frames = self.frames(destination)
                self.assertEqual(len(frames), 3)
                self.assertEqual(frames[0].shape, (24, 32, 3) if crop else (48, 64, 3))
                # MP4 is lossy; compare a uniform source region with tolerance.
                for frame, level in zip(frames, (30, 80, 130)):
                    self.assertAlmostEqual(float(frame[:, 20:].mean()), level, delta=12)
                if crop:
                    self.assertGreater(float(frames[0][:, :8].mean()), 15)

    def test_prefix_reports_early_eof_and_cancellation(self):
        written, cancelled = write_video_prefix(
            self.source, self.root / "short.mp4", 10, progress=lambda _: False)
        self.assertEqual((written, cancelled), (4, False))
        written, cancelled = write_video_prefix(
            self.source, self.root / "cancelled.mp4", 4, progress=lambda _: True)
        self.assertEqual((written, cancelled), (4, True))

    def test_aligned_video_repeats_frames_and_preserves_blank_coverage(self):
        destination = self.root / "aligned.mp4"
        cancelled = write_aligned_video(
            self.source, destination, np.arange(4) * 50., np.array([2, 2, -1, 0]),
            source_fps=20, crop=(16, 8, 32, 24), progress=lambda _: False)
        self.assertFalse(cancelled)
        frames = self.frames(destination)
        self.assertEqual(len(frames), 4)
        self.assertEqual(frames[0].shape, (24, 32, 3))
        self.assertAlmostEqual(float(frames[0].mean()), 130, delta=12)
        np.testing.assert_allclose(frames[0], frames[1], atol=5)
        self.assertLess(float(frames[2][:10].mean()), 5)
        self.assertAlmostEqual(float(frames[3].mean()), 30, delta=12)

    def test_aligned_read_error_releases_capture_and_writer(self):
        cap, writer = Mock(), Mock()
        cap.get.return_value = 32
        cap.read.return_value = (False, None)
        with patch("cali.video_exports.cv2.VideoCapture", return_value=cap), \
             patch("cali.video_exports.cv2.VideoWriter", return_value=writer):
            with self.assertRaisesRegex(RuntimeError, "Could not read source frame 3"):
                write_aligned_video(self.source, self.root / "bad.mp4", [0], [2],
                                    source_fps=20, progress=lambda _: False)
        cap.release.assert_called_once()
        writer.release.assert_called_once()
