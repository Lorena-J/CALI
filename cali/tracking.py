"""Tracking CSV readers, frame indices and timestamp-based alignment (no Qt)."""
import csv

import numpy as np
import pandas as pd


def is_frame_column(name):
    key = str(name).lower().strip().replace(" ", "_")
    return key in {"frame", "frame_index", "frame_idx", "frame_number", "frame_id", "index", "unnamed:_0"}


def load_tracking_table(path):
    # Detect DLC headers before looking for numeric columns: its coordinate
    # rows otherwise pass the flat-CSV heuristic and shift frames by two.
    with open(path, newline="", encoding="utf-8-sig") as handle:
        header = [next(csv.reader(handle), []) for _ in range(3)]
    is_dlc = (len(header[2]) > 1 and len(header[1]) > 0 and header[2][0].strip().lower() == "coords"
              and header[1][0].strip().lower() == "bodyparts")
    if is_dlc:
        table = pd.read_csv(path, header=[0, 1, 2], index_col=0)
        table.columns = [".".join(str(part) for part in col[1:]) for col in table.columns]
        table = table.reset_index(names="frame_index")
    else:
        table = pd.read_csv(path)
    numeric = {}
    for col in table.columns:
        if is_frame_column(col):
            continue
        vals = pd.to_numeric(table[col], errors="coerce")
        if vals.notna().sum() >= 2:
            numeric[str(col)] = vals.to_numpy(float)
    return table, numeric


def tracking_indices(table, n_video=None):
    columns = [col for col in table.columns if is_frame_column(col)]
    if columns:
        col = columns[0]
        values = pd.to_numeric(table[col], errors="raise").to_numpy(float)
        if not np.all(np.isfinite(values)) or not np.all(values == np.floor(values)):
            raise ValueError("Tracking frame indices must be finite integers.")
        key = str(col).lower().strip().replace(" ", "_")
        # Index columns (including DLC) are zero-based; frame numbers start
        # at one unless an explicit zero identifies a zero-based export.
        zero_based = key in {"frame_index", "frame_idx", "index", "unnamed:_0"} or np.any(values == 0)
        indices = values.astype(int) - (0 if zero_based else 1)
        if np.any(indices < 0) or np.any(np.diff(indices) <= 0):
            raise ValueError("Tracking frame indices must be non-negative, unique and increasing.")
        if n_video is not None and np.any(indices >= n_video):
            raise ValueError("Tracking frame indices exceed the loaded MP4. Load the video used for tracking.")
        return indices
    if n_video is not None and len(table) != n_video:
        raise ValueError(
            f"Tracking has {len(table)} rows but the MP4 has {n_video} frames. "
            "Load the matching video or include a frame_index (zero-based) or frame (one-based) column."
        )
    return np.arange(len(table))


def interpolation_map(source_times, target_times):
    source_times = np.asarray(source_times, dtype=float)
    target_times = np.asarray(target_times, dtype=float)
    left = np.full(len(target_times), -1, dtype=int)
    right = left.copy()
    nearest = left.copy()
    alpha = np.full(len(target_times), np.nan)
    if not len(source_times):
        return left, right, alpha, nearest
    if not np.all(np.isfinite(source_times)) or np.any(np.diff(source_times) <= 0):
        raise ValueError("Interpolation timestamps must be finite and strictly increasing.")
    covered = (target_times >= source_times[0]) & (target_times <= source_times[-1])
    times = target_times[covered]
    r = np.searchsorted(source_times, times, side="left")
    l = np.maximum(r - 1, 0)
    exact = source_times[r] == times
    l[exact] = r[exact]
    denom = source_times[r] - source_times[l]
    weights = np.divide(times - source_times[l], denom,
                        out=np.zeros(len(times)), where=denom > 0)
    left[covered], right[covered], alpha[covered] = l, r, weights
    nearest[covered] = np.where(weights <= .5, l, r)
    return left, right, alpha, nearest


def build_video_times(n_frames, camera_times, mapped_indices):
    """Interpolate only within camera TTL coverage, using the caller's trim/mapping."""
    if n_frames <= 0:
        raise RuntimeError("No behavior frames are available.")
    camera_t = np.asarray(camera_times, dtype=float)
    known_idx = np.asarray(mapped_indices, dtype=int)
    valid = (known_idx >= 0) & (known_idx < n_frames) & np.isfinite(camera_t)
    known_idx, known_t = known_idx[valid], camera_t[valid]
    if len(known_idx) < 2:
        raise ValueError("Not enough camera timestamps map onto behavior frames within the trim.")
    if np.any(np.diff(known_idx) <= 0) or np.any(np.diff(known_t) <= 0):
        raise ValueError("Camera frame indices and timestamps must be strictly increasing.")
    # No video times are invented before the first or after the last TTL.
    return np.interp(np.arange(n_frames), known_idx, known_t, left=np.nan, right=np.nan)


def align_coordinate(x, indices, video_times, *, camera_times, camera_frames,
                     mini_times, mini_frames, mini_end, camera_period,
                     mode_index, max_missing_frames):
    """Align one coordinate and retain interpolation/video provenance without Qt."""
    source_times = video_times[indices]
    n_video = len(video_times)
    finite = np.isfinite(x) & np.isfinite(source_times)
    if finite.sum() < 2:
        raise ValueError("Not enough valid tracking positions within camera timestamp coverage and trim.")
    interp_times, interp_x = source_times[finite], x[finite]
    interp_frames = indices[finite]

    raw_window = (source_times >= 0.0) & (source_times <= mini_end)
    if mode_index == 0:
        # Preserve actual camera times, including reconstructed missing TTLs.
        camera_t = camera_times
        mask = (camera_t >= 0.0) & (camera_t <= mini_end)
        mask &= (camera_frames >= 0) & (camera_frames < n_video)
        target_times = camera_t[mask].copy()
        target_frame = camera_frames[mask] + 1
        mode_name = "camera_timestamps"
    else:
        # Keep one row per calcium frame; unavailable positions stay empty.
        target_times = np.asarray(mini_times, dtype=float).copy()
        target_frame = np.asarray(mini_frames, dtype=int).copy()
        mode_name = "mini2p_1to1"
    if not len(target_times):
        raise ValueError("No camera frames overlap the Mini2P recording and trim.")

    left, right, alpha, _ = interpolation_map(interp_times, target_times)
    target_x = np.full(len(target_times), np.nan)
    usable = left >= 0
    covered = np.flatnonzero(usable)
    period = camera_period
    max_span = (max_missing_frames + 1) * period * 1.05
    spans = interp_times[right[covered]] - interp_times[left[covered]]
    missing = interp_frames[right[covered]] - interp_frames[left[covered]] - 1
    usable[covered] &= (spans <= max_span) & (missing <= max_missing_frames)
    usable &= target_times <= mini_end
    positions = np.flatnonzero(usable)
    target_x[positions] = ((1 - alpha[positions]) * interp_x[left[positions]]
                           + alpha[positions] * interp_x[right[positions]])
    source_left = np.full(len(target_times), np.nan)
    source_right = source_left.copy()
    source_left[usable] = interp_frames[left[usable]] + 1
    source_right[usable] = interp_frames[right[usable]] + 1
    alpha[~usable] = np.nan

    # Video correspondence is independent of missing tracking coordinates.
    available = np.flatnonzero(np.isfinite(video_times))
    _, _, _, near = interpolation_map(video_times[available], target_times)
    near[target_times > mini_end] = -1
    video_indices = np.full(len(target_times), -1, dtype=int)
    has_frame = near >= 0
    video_indices[has_frame] = available[near[has_frame]]
    nearest_frames = np.full(len(target_times), np.nan)
    nearest_times = nearest_frames.copy()
    nearest_frames[has_frame] = video_indices[has_frame] + 1
    nearest_times[has_frame] = video_times[video_indices[has_frame]]

    result = pd.DataFrame({
        "target_frame": target_frame,
        "target_time_ms": target_times,
        "x_aligned": target_x,
        "source_left_frame": source_left,
        "source_right_frame": source_right,
        "interpolation_alpha": alpha,
        "nearest_behavior_frame": nearest_frames,
        "nearest_behavior_time_ms": nearest_times,
        "delta_to_nearest_behavior_ms": target_times - nearest_times,
    })
    if mode_name == "mini2p_1to1":
        result.insert(0, "mini2p_frame", target_frame)
    return result, video_indices, raw_window, usable, has_frame, mode_name
