# Synchronization, tracking and exports

[Back to CALI](../README.md)

## Timing inputs

Both CSV files need numeric `frame` and `timestamp_ms` columns; additional
columns such as `elapsed_ms` are allowed. For example, this illustrates syntax
only, not measured acquisition data:

```csv
frame,timestamp_ms
1,1000.0
2,1050.0
3,1100.0
```

The two CSVs must come from a common acquisition clock. CALI subtracts the first
Mini2P timestamp from both series; camera times can therefore be negative.
It does not estimate an offset or drift between independent clocks. Check
finite, ordered timestamps and frame IDs before interpretation; input validation
is not exhaustive. Real-clock synchronization remains pending validation.

## Camera reconstruction and video mapping

Camera loading fills apparent missing TTL periods between measured endpoints,
using the median positive period and interpolating the inserted timestamps.
It neither adds times before the first TTL nor after the last, and it does not
currently label reconstructed rows explicitly. Reconstruction assumes missing
TTL records; it cannot establish that the video actually contains every frame.

Both mapping modes use this already reconstructed table:

- **Timing reconstruction**: zero-based video index = offset + virtual camera index.
- **TTL index**: zero-based video index = offset + row index.

The **MP4 offset** is a signed frame count. Changing it does not shift timestamps
in milliseconds. TTL index does not restore the original unfilled camera CSV.
Verify the mapping against an acquisition event visible in the actual video.

Raw Mini2P browsing interprets frame IDs in base one: TIFF page = frame − 1.
The viewer opens one TIFF at a time; processing has its own channel-aware,
multifile workflow. The nearest-frame image view can show an endpoint outside
its timing coverage; this should not be confused with analysis coverage.
Processed CaImAn movies instead use their full movie-frame axis and synchronize
behavior only where a measured Mini2P TTL is available.

## Align existing tracking

Open **Align tracking** in the Timeline header. Load a flat CSV or a DeepLabCut
CSV with its three header rows, choose one numeric coordinate (typically X),
and choose camera times or one sample per Mini2P frame.

- `frame_index`, `frame_idx`, `index` and `Unnamed: 0` identify zero-based frames.
- `frame`, `frame_number` and `frame_id` are treated as one-based unless a zero
  explicitly identifies zero-based indexing.
- Indices must be finite, integral, unique and increasing, and fit the video
  when it is loaded. Without an index column, rows are consecutive; with a
  loaded video, row and video frame counts must match.

Alignment interpolates positions within the configured missing-frame limit
(default: two absent frames), without extrapolating outside coverage. Missing
positions stay empty. The CSV includes interpolation neighbors, weights, the
nearest real video frame and its timing difference.

An aligned MP4 uses the nearest real frame, repeating it where necessary and
writing blank images without coverage. It has a constant estimated FPS; exact
target timestamps are kept in its accompanying `.mapping.csv`. Keep that mapping
when using an aligned video downstream.

Movement analysis expects tracking from the **original behavior video**, not
this resampled export. Its gap and coverage policy differs from alignment;
see [the movement guide](movement-analysis.md).

## Trims and spatial crops

Temporal trimming selects an end at a camera TTL; there is no start-time trim.
The automatic end is the last camera TTL not later than the last Mini2P TTL.
Export creates a new `trimmed_*` folder containing `camera_trimmed.csv`,
`behavior_trimmed.mp4` and `trim_info.json`. The camera CSV includes any rows
reconstructed during loading; the video preserves its prefix through the mapped
end frame.

A rectangular crop uses original video coordinates and even output dimensions
for encoding. Export creates `cropped_*` with `behavior_cropped.mp4` and
`crop_info.json`. An active crop also applies to temporal/aligned-video exports.
Video exports use OpenCV's `mp4v` codec and do not preserve audio. Check the output
files if an export fails: partial files are not automatically rolled back.
