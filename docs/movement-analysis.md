# Calcium and movement analysis

[Back to CALI](../README.md)


After loading both TTL CSVs and CaImAn results, open **Movement analysis** in
the timeline header, then load the tracking CSV associated with the behavior
video. The video is optional if tracking has explicit frame indices; the camera
TTLs establish the time mapping. A tracking file already open in **Align
tracking** is reused automatically when the analysis window is first opened.

Use **Position X/Y** to calculate speed from two coordinates of the same body
part, or **Speed column** to use an existing non-negative speed measurement.
Flat CSV and DeepLabCut multi-header CSV are supported, with the same frame ID
conventions as tracking alignment (`frame_index`: zero-based; `frame`: one-based).
The input must refer to the loaded behavior video, not an already resampled
Mini2P tracking export. X/Y are differentiated using measured time in seconds.
Speed is median filtered within the configurable temporal window; setting the
window to zero disables smoothing. Input units identify the units already in
the file; selecting cm or mm does **not** calibrate or rescale pixel data.

Choose a confidence/likelihood column when available, its minimum value,
the maximum permitted inter-frame time, the movement threshold, signal and
component filter. Samples at or above the speed threshold are moving; lower
speeds are rest. Missing coordinates, rejected confidence, skipped tracking
frames and excessive time gaps split the tracking into independent runs.
Speed is interpolated to Mini2P times only inside these runs. Missing coverage
is unknown, not rest. The current temporal trim and CaImAn first-frame mapping
apply to the analysis.

**Analyze** produces one row per cell with mean activity during movement and
rest, their difference, Pearson correlation with speed, paired frame counts
and observed duration in each state. Means are duration weighted using half
of each adjacent covered interval at each endpoint. Gaps and acquisition time
beyond the observed endpoints are excluded. Cells without both states have
an undefined difference; correlations for constant signals or fewer than
three paired samples are undefined. These values are descriptive, with no
p-values, independence assumptions or significance classifications.

Select a row to inspect synchronized time plots, activity versus speed,
state means and lagged correlation. The selection also focuses that ROI in
the main viewer. Time plots use seconds; clicking them updates both image
viewers. A positive lag compares `calcium(t)` to `speed(t − lag)`, meaning
calcium follows movement. Lagged correlations use available paired samples
at each lag and are exploratory, not corrected statistical tests. Their
sample coverage can differ between lags.

**Export analysis** creates a new folder with `per_cell_summary.csv`,
`aligned_movement.csv`, selected-ROI aligned samples and lag curve, and an
`analysis_settings.json` recording sources, mapping, thresholds, units and
processing choices. Changes to input settings, TTLs, video mapping, trim or
CaImAn source invalidate the result and disable export until recalculation.

For the prepared demo, use `06_tracking_SIMULATED.csv`, X=`x`, Y=`y`, units=px,
confidence=`likelihood`, threshold=20 px/s, median window=0.2 s and maximum gap
100 ms. The behavioral trajectory is simulated independently of the calcium;
any associations in that demo have no biological interpretation.

Method references: [NumPy gradients on uneven time spacing](https://numpy.org/doc/stable/reference/generated/numpy.gradient.html)
and [Pearson correlation definition and constant-input limits](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.pearsonr.html).
