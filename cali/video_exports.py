"""Video encoding and export metadata, independent of Qt.

The progress callback receives the number of written frames and returns True
to cancel. Callers own progress dialogs and the existing partial-output policy.
"""
import json
from pathlib import Path

import cv2
import numpy as np


class VideoExportOpenError(RuntimeError):
    """The source or output video could not be opened."""


def write_video_prefix(source, destination, count, *, crop=None, progress,
                       open_error="Could not open source/output MP4 for trimming"):
    """Encode the first count frames, optionally cropping in source coordinates.

    Return (written, cancelled); the caller checks early end-of-file and
    removes cancelled outputs according to its export policy.
    """
    cap = cv2.VideoCapture(str(source))
    writer = None
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        if crop is None:
            x, y = 0, 0
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        else:
            x, y, width, height = crop
        writer = cv2.VideoWriter(str(destination), cv2.VideoWriter_fourcc(*"mp4v"),
                                 fps, (width, height))
        if not cap.isOpened() or not writer.isOpened():
            raise VideoExportOpenError(open_error)
        written = 0
        cancelled = False
        while written < count:
            ok, frame = cap.read()
            if not ok:
                break
            if crop is not None:
                frame = frame[y:y + height, x:x + width]
            writer.write(frame)
            written += 1
            if written % 10 == 0 or written == count:
                cancelled = progress(written)
            if cancelled:
                break
        return written, cancelled
    finally:
        cap.release()
        if writer is not None:
            writer.release()


def write_aligned_video(source, destination, target_times, target_video_indices,
                        *, source_fps, crop=None, progress):
    """Encode nearest source frames and blank images outside video coverage.

    Preserve the constant-FPS preview convention; exact sample times belong
    to the mapping CSV. Return True on cancellation.
    """
    cap = cv2.VideoCapture(str(source))
    writer = None
    try:
        if not cap.isOpened():
            raise VideoExportOpenError("Could not open source behavior video.")
        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        out_w, out_h = crop[2:] if crop is not None else (src_w, src_h)
        if len(target_times) >= 2:
            dt = np.median(np.diff(target_times))
            fps = 1000.0 / dt if dt > 0 else float(source_fps)
        else:
            fps = float(source_fps)
        writer = cv2.VideoWriter(str(destination), cv2.VideoWriter_fourcc(*"mp4v"),
                                 float(fps), (int(out_w), int(out_h)))
        if not writer.isOpened():
            raise VideoExportOpenError("Could not create output MP4.")
        cache = {}
        cancelled = False
        for out_i, src_i in enumerate(target_video_indices):
            src_i = int(src_i)
            if src_i < 0:
                frame = np.zeros((int(out_h), int(out_w), 3), dtype=np.uint8)
                cv2.putText(frame, "No behavior frame", (20, max(30, int(out_h) // 2)),
                            cv2.FONT_HERSHEY_SIMPLEX, .7, (220, 220, 220), 1)
                writer.write(frame)
                if progress(out_i + 1):
                    return True
                continue
            frame = cache.get(src_i)
            if frame is None:
                cap.set(cv2.CAP_PROP_POS_FRAMES, src_i)
                ok, frame = cap.read()
                if not ok:
                    raise RuntimeError(f"Could not read source frame {src_i + 1}.")
                cache[src_i] = frame.copy()
                if len(cache) > 24:
                    cache.pop(next(iter(cache)))
            else:
                frame = frame.copy()
            if crop is not None:
                cx, cy, cw, ch = crop
                frame = frame[cy:cy + ch, cx:cx + cw]
            writer.write(frame)
            if out_i % 10 == 0 or out_i == len(target_video_indices) - 1:
                cancelled = progress(out_i + 1)
            if cancelled:
                break
        return cancelled
    finally:
        cap.release()
        if writer is not None:
            writer.release()


def write_export_metadata(path, metadata):
    """Write the crop/trim provenance using the existing JSON format."""
    Path(path).write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def write_aligned_mapping(video_path, result):
    """Keep exact target times and source correspondence beside the MP4."""
    mapping_path = str(Path(video_path).with_suffix(".mapping.csv"))
    result.to_csv(mapping_path, index=False)
    return mapping_path
