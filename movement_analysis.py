"""Descriptive calcium/movement analysis using measured, synchronized times."""
import numpy as np
import pandas as pd


def _times(values):
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or not np.all(np.isfinite(values)) or np.any(np.diff(values) <= 0):
        raise ValueError("Times must be finite and strictly increasing.")
    return values


def valid_runs(times, valid, frame_indices, max_gap_s):
    """Split at missing coordinates, skipped frames, or excessive time gaps."""
    indices = np.flatnonzero(valid)
    if not len(indices):
        return []
    breaks = ((np.diff(indices) != 1)
              | (np.diff(np.asarray(frame_indices)[indices]) != 1)
              | (np.diff(times[indices]) > max_gap_s + max(1e-9, max_gap_s*1e-9)))
    return np.split(indices, np.flatnonzero(breaks) + 1)


def prepare_speed(times_s, frame_indices, *, x=None, y=None, speed=None,
                  confidence=None, min_confidence=.9, max_gap_s=.1, smoothing_s=.2):
    """Estimate speed only within contiguous valid runs; never bridge holes.

    `times_s` may have NaN outside camera TTL coverage. Returned segments are
    used again during interpolation, so rejected tracking stays rejected.
    """
    times = np.asarray(times_s, dtype=float)
    frame_indices = np.asarray(frame_indices)
    if times.ndim != 1 or frame_indices.shape != times.shape or len(times) < 2:
        raise ValueError("Tracking needs at least two matching times and frame indices.")
    if np.any(np.diff(frame_indices) <= 0):
        raise ValueError("Tracking frame indices must be ordered and unique.")
    if not np.isfinite(max_gap_s) or max_gap_s <= 0 or not np.isfinite(smoothing_s) or smoothing_s < 0:
        raise ValueError("Maximum gap must be positive and smoothing must be non-negative.")
    finite_t = times[np.isfinite(times)]
    _times(finite_t)
    valid = np.isfinite(times)
    coordinates = []
    if speed is not None:
        supplied = np.asarray(speed, dtype=float)
        if supplied.shape != times.shape:
            raise ValueError("Speed and tracking times have different lengths.")
        valid &= np.isfinite(supplied) & (supplied >= 0)
    else:
        if x is None or y is None:
            raise ValueError("Choose both X and Y coordinates, or a speed column.")
        for coordinate in (x, y):
            coordinate = np.asarray(coordinate, dtype=float)
            if coordinate.shape != times.shape:
                raise ValueError("Coordinates and tracking times have different lengths.")
            valid &= np.isfinite(coordinate)
            coordinates.append(coordinate)
    if confidence is not None:
        confidence = np.asarray(confidence, dtype=float)
        if confidence.shape != times.shape:
            raise ValueError("Confidence and tracking times have different lengths.")
        valid &= np.isfinite(confidence) & (confidence >= min_confidence)
    output = np.full(len(times), np.nan)
    segments = []
    for run in valid_runs(times, valid, frame_indices, max_gap_s):
        if len(run) < 2:
            continue
        if speed is None:
            dx = np.gradient(coordinates[0][run], times[run])
            dy = np.gradient(coordinates[1][run], times[run])
            values = np.hypot(dx, dy)
        else:
            values = supplied[run].copy()
        if smoothing_s > 0:
            series = pd.Series(values, index=pd.to_timedelta(times[run], unit="s"))
            values = series.rolling(pd.Timedelta(smoothing_s, unit="s"), center=True,
                                    min_periods=1).median().to_numpy()
        output[run] = values
        segments.append(run)
    if not segments:
        raise ValueError("No continuous tracking coverage remains. Check columns, confidence and maximum gap.")
    return output, segments


def align_speed(source_times, speed, segments, target_times, return_segments=False):
    """Interpolate within each valid segment only, without extrapolation."""
    target_times = np.asarray(target_times, dtype=float)
    aligned = np.full(len(target_times), np.nan)
    segment_ids = np.full(len(target_times), -1, dtype=int)
    for segment, run in enumerate(segments):
        covered = ((target_times >= source_times[run[0]])
                   & (target_times <= source_times[run[-1]]))
        aligned[covered] = np.interp(target_times[covered], source_times[run], speed[run])
        segment_ids[covered] = segment
    return (aligned, segment_ids) if return_segments else aligned


def duration_weights(times_s, max_gap_s, valid=None, segment_ids=None):
    """Observed duration per sample: half of each valid adjacent interval.

    No extra recording duration is invented at the endpoints or across gaps.
    """
    times = _times(times_s)
    weights = np.zeros(len(times))
    intervals = np.diff(times)
    observed = intervals <= max_gap_s + max(1e-9, max_gap_s*1e-9)
    if valid is not None:
        observed &= valid[:-1] & valid[1:]
    if segment_ids is not None:
        observed &= (segment_ids[:-1] >= 0) & (segment_ids[:-1] == segment_ids[1:])
    intervals = np.where(observed, intervals, 0)
    weights[:-1] += intervals / 2
    weights[1:] += intervals / 2
    return weights


def pearson(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    x, y = x[valid], y[valid]
    if len(x) < 3:
        return np.nan
    x, y = x - x.mean(), y - y.mean()
    norm_x, norm_y = np.linalg.norm(x), np.linalg.norm(y)
    if norm_x == 0 or norm_y == 0:
        return np.nan
    return float(np.clip(np.dot(x / norm_x, y / norm_y), -1, 1))


def summarize_cell(values, speed, weights, threshold):
    values = np.asarray(values, dtype=float)
    valid = np.isfinite(values) & np.isfinite(speed) & (weights > 0)
    moving = valid & (speed >= threshold)
    resting = valid & (speed < threshold)
    def mean(mask):
        return float(np.average(values[mask], weights=weights[mask])) if mask.any() else np.nan
    movement_mean, rest_mean = mean(moving), mean(resting)
    return {
        "valid_frames": int(valid.sum()), "moving_frames": int(moving.sum()),
        "rest_frames": int(resting.sum()),
        "moving_duration_s": float(weights[moving].sum()),
        "rest_duration_s": float(weights[resting].sum()),
        "mean_moving": movement_mean, "mean_rest": rest_mean,
        "moving_minus_rest": movement_mean - rest_mean,
        "pearson_speed": pearson(values[valid], speed[valid]),
    }


def analyze_cells(results, signal, component_ids, mini_frames, times_s,
                  aligned_speed, threshold, first_frame=1, max_gap_s=.1,
                  progress=None, segment_ids=None):
    if not np.isfinite(threshold) or threshold < 0:
        raise ValueError("Movement threshold must be finite and non-negative.")
    times = _times(times_s)
    if len(times) < 3 or np.shape(aligned_speed) != times.shape or len(mini_frames) != len(times):
        raise ValueError("At least three matching Mini2P frames, times and speeds are required.")
    if not np.isfinite(aligned_speed).any():
        raise ValueError("No tracking overlaps these Mini2P frames.")
    ids = list(component_ids)
    if not ids:
        raise ValueError("No CaImAn components in this quality filter.")
    weights = duration_weights(times, max_gap_s, np.isfinite(aligned_speed), segment_ids)
    rows = []
    for number, component in enumerate(ids):
        if progress:
            progress(number, len(ids))
        values, _ = results.mapped_trace(results.trace(int(component), signal), mini_frames, first_frame)
        cell_weights = duration_weights(times, max_gap_s,
                                        np.isfinite(aligned_speed) & np.isfinite(values), segment_ids)
        rows.append({"roi_id_zero_based": int(component), "quality": results.quality(int(component)),
                     "signal": signal, **summarize_cell(values, aligned_speed, cell_weights, threshold)})
    if not any(row["valid_frames"] for row in rows):
        raise ValueError("No covered calcium/tracking intervals remain. Check frame mapping and maximum frame gap.")
    return pd.DataFrame(rows), weights


def lag_correlations(values, target_times, source_times, speed, segments, lags_s):
    """Positive lag means calcium follows behavior: calcium(t) vs speed(t-lag)."""
    return np.array([pearson(values, align_speed(source_times, speed, segments, target_times - lag))
                     for lag in lags_s])
