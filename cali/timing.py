"""TTL input and camera timestamp reconstruction, in milliseconds (no Qt)."""
import numpy as np
import pandas as pd


def load_csv(path, label):
    df = pd.read_csv(path).copy()
    for col in ("frame", "timestamp_ms"):
        if col not in df.columns:
            raise ValueError(f"{label}: missing column '{col}'")
    df["frame"] = pd.to_numeric(df["frame"], errors="raise").astype(int)
    df["timestamp_ms"] = pd.to_numeric(df["timestamp_ms"], errors="raise").astype(float)
    if len(df) == 0:
        raise ValueError(f"{label}: empty CSV")
    if np.any(np.diff(df["timestamp_ms"].to_numpy()) < 0):
        raise ValueError(f"{label}: timestamps are not ordered")
    return df


def median_period(times):
    if times is None or len(times) < 2:
        return np.nan
    d = np.diff(times)
    d = d[d > 0]
    return float(np.median(d)) if len(d) else np.nan


def virtual_camera_indices(times):
    n = len(times)
    out = np.arange(n, dtype=int)
    if n < 2:
        return out
    p = median_period(times)
    if not np.isfinite(p) or p <= 0:
        return out
    steps = np.maximum(1, np.rint(np.diff(times) / p).astype(int))
    out = np.zeros(n, dtype=int)
    for i, step in enumerate(steps, start=1):
        out[i] = out[i - 1] + int(step)
    return out


def fill_camera_timestamps(df):
    """Fill missing camera periods between recorded TTLs, in Arduino time."""
    times = df.timestamp_ms.to_numpy(float)
    indices = virtual_camera_indices(times)
    if len(indices) < 2 or indices[-1] == len(indices) - 1:
        return df.copy()

    frame_indices = np.arange(indices[-1] + 1)
    filled = df.set_axis(indices).reindex(frame_indices).copy()
    # Keep measured endpoints and distribute missing frames evenly between them.
    filled["timestamp_ms"] = np.interp(frame_indices, indices, times)
    filled["frame"] = int(df.frame.iloc[0]) + frame_indices
    if "elapsed_ms" in filled.columns:
        filled["elapsed_ms"] = filled.timestamp_ms - times[0]
    return filled.reset_index(drop=True)
