# MINISYNC

Desktop viewer for aligning Mini2P imaging and behavior-camera TTL streams.

Run:

```bash
pip install -r requirements.txt
python sync_viewer.py
```

The bundled `mini2p_logo_mark.png` is used by the application header and window icon.

## Motion correction and CNMF

Choose **Calcium analysis** beside Align tracking and Movement analysis in the Timeline to process TIFFs with
CaImAn in a separate process. The viewer remains usable during computation.
CaImAn is optional for viewing existing results; processing requires its own
installation. Create an environment with:

```bash
conda env create -f environment-caiman.yml
```

The environment pins CaImAn 1.12.1 and constrains `setuptools<81` and
`scipy<1.17`: newer versions respectively remove `pkg_resources` or change
Toeplitz matrix handling used by this CaImAn release's deconvolution.

The viewer and worker use separate Python environments when needed. The engine
is located automatically in the current environment or a sibling Conda environment
named `caiman` or `minisync-caiman`; interpreter paths are not exposed in the UI.
For custom installations, set the `MINISYNC_CAIMAN_PYTHON` environment variable.
For the current development
machine, launch the viewer with `conda activate mini2p-sync`; its existing
`caiman` environment already contains the processing engine.
See the [CaImAn installation guide](https://caiman.readthedocs.io/en/latest/Installation.html)
for platform requirements, including Intel/Rosetta environments on Apple Silicon.

1. Load your TIFF in Files, then open **Calcium analysis** in the Timeline.
   The loaded TIFF is reused. **Add TIFF** adds source files in selection order;
   the trash icon clears the analysis selection without deleting any files.
2. Check **Frame rate (Hz)**. It is prefilled from ScanImage metadata, or estimated
   from the loaded Mini2P TTL intervals, and stays editable. Without either source,
   enter it yourself. This is acquisition frame rate, not neuronal firing rate.
3. Choose **Channels** and **Planes**. Saved-channel metadata is used when available.
   For two channels, choose Channel 1, Channel 2 or **Both channels**. Both runs
   separate jobs sequentially; signals and footprints are not merged. Each channel
   is corrected independently, without transferring reference-channel shifts.
   Only one plane is currently supported; unsupported plane counts are disabled.
4. **More options** reveals motion correction, shifts, patch settings, first Mini2P
   frame, neuron size, decay time and quality thresholds. These are starting
   parameters, not validated Mini2P presets. At least 100 selected-channel samples
   are required; multiplane/flyback, RGB and incomplete channel cycles are rejected.
5. Choose **Run analysis**. A new `minisync_results/calcium_*` folder is created
   beside the source TIFF. Originals and previous runs are preserved. For both
   channels, outputs are stored in separate `channel_*` subfolders with `batch.json`.
6. Completed results open automatically in the main viewer, using the corrected
   TIFF and configured frame origin. The setup window closes and **Calcium** is
   selected. Choose ROI and signal (`C`, `C + YrA`, ΔF/F or `S`) there; **Play**,
   the movie-frame field and slider navigate the corrected movie. The channel
   selector in the main Calcium tab switches between completed channel results.
   Detailed logs are saved to disk rather than displayed in a panel.

If no components passed the configured quality criteria, the initial filter
falls back to **All components** so the candidates remain inspectable. Their
saved accepted/rejected labels are preserved; visibility does not validate a cell.
To reopen an existing run, use **CaImAn HDF5** in Files and select its
`cnmf_results.hdf5` or `processing.json` (or `batch.json` for both channels).
When the accompanying manifest exists, the corrected TIFF is loaded as well.

No behavior video or tracking is needed to calculate CNMF. Both TTL CSVs and the
behavior video are used by the existing synchronized viewer. The TTL frame
convention must match one time sample per selected channel; the worker does not
resolve unknown TTL/page/volume relationships.

Processed results display the full trace against **Movie frame**, including
samples outside TTL coverage. Only samples with a measured Mini2P TTL have a
synchronized behavior time; other movie frames leave the behavior viewer empty.
No acquisition times are invented. The Timing tab keeps its independent Arduino
time axis. Preview playback uses the configured frame rate, capped at 60 fps.
The frame-rate input accepts 0.001–1000 Hz to catch unit/typing mistakes.

Processing follows the [official two-photon CaImAn pipeline](https://github.com/flatironinstitute/CaImAn/blob/main/demos/general/demo_pipeline.py):
rigid or piecewise-rigid motion correction, patch CNMF initialization, full
refinement with AR(1) deconvolution, component quality evaluation (SNR/spatial
correlation, CNN disabled), and saved ΔF/F. Quality labels identify candidate
components; inspect motion and cells before interpreting biological results.
The worker uses one CaImAn process and limits native threads to one.

Outputs include `cnmf_results.hdf5`, `selected_channel.tif`,
`motion_corrected.tif`, `motion_shifts.npz`, `frame_mapping.csv`,
`processing.json` (settings, source layout and SHA-256, versions, status and output paths),
`caiman_parameters.json` (resolved CNMF parameters)
and intermediate CaImAn memory maps. The GUI also saves `processing.log`.
The mapping records each sample's source TIFF and page, selected channel and
user-supplied Mini2P frame ID. No temporal resampling is applied. Correction
can add a constant intensity offset for non-negativity; copied borders are
excluded from CNMF using the maximum observed displacement. Allow disk space
for multiple float32 copies of the selected movie and intermediate maps.

While running, the bottom button becomes **Cancel analysis**, which terminates
the active worker and stops any remaining channel jobs.
Partial files are retained, with cancelled status when a manifest exists.
On failure, inspect the log and manifest; rerun in a new output folder. Cancel
an active job before closing the application.

For scripted runs, save a JSON object with the fields of
`calcium_pipeline.PipelineSettings` and run the worker directly:

```bash
/path/to/caiman/python calcium_pipeline.py --config /path/to/settings.json
```

The configured output directory must not exist. No example data or TTLs are
silently substituted. ScanImage multichannel metadata handling has synthetic
tests; validation on an authentic multichannel ScanImage acquisition remains
pending.

## CaImAn CNMF results

Load **CaImAn HDF5** to open a `.hdf5` or `.h5` result saved with
`cnm.save(...)`. MINISYNC reads the file directly with `h5py`; installing or
running the CaImAn analysis pipeline is not required. NWB and pickle results
are not supported by this importer.

In the **Calcium** tab:

- Select an original, zero-based component ID and filter by the quality labels
  saved by CaImAn. Files without quality evaluation show all components.
- Choose `C` (denoised temporal component), `C + YrA` (including residuals),
  `F_dff` (ΔF/F), or `S` (deconvolved activity), when present in the file.
  MINISYNC displays saved results without recalculating normalization or
  deconvolution; `C` is not labelled as raw fluorescence, and `S` is not a
  measured spike train.
- Traces can be inspected without TTLs using movie frames. Load the Mini2P TTL CSV to synchronize traces with both image viewers.
  Drag either plot's cursor, click a plot, or use the existing frame controls.
  Horizontal plot ranges follow each other in the synchronized-time view;
  the processed movie-frame view has its own axis.
- **First Mini2P frame** identifies the 1-based Mini2P frame corresponding to
  CaImAn sample zero. Leave it at 1 for a full movie. For a temporally cropped
  movie, enter its actual starting frame. Mapping uses frame IDs and measured
  TTL times, without estimating a frame rate or interpolating calcium values.
  Missing/out-of-range samples remain empty, and count differences are shown.
  Temporally downsampled, reordered, or concatenated movies need an explicit
  frame mapping and are not supported by the single starting-frame setting.
- **Show ROI** outlines the selected spatial footprint at 20% of its maximum.
  Footprints use CaImAn's Fortran pixel ordering. Overlay requires matching
  image dimensions and coordinates: use the same field of view and motion
  corrected movie used for CNMF. A matching size alone does not establish
  spatial registration. Without a TIFF frame, a saved correlation image `Cn`
  or the selected footprint is displayed and labelled as a static reference.
- **Export trace** saves the selected signal with Mini2P frame IDs, measured
  relative times in milliseconds, zero-based CaImAn sample/component IDs,
  and empty values outside coverage. Processed movie results export all samples
  with empty `time_ms` where a measured TTL is absent; no-TTL imports also leave
  times empty. The current temporal trim applies to exports.

The importer supports 2D dense or CSC spatial footprints, and trace-only
viewing if spatial footprints or 2D dimensions are unavailable. It loads
selected trace rows and footprint columns instead of loading all components.

Format references: [CaImAn CNMF persistence](https://caiman.readthedocs.io/en/latest/core_functions.html),
[Estimates fields](https://github.com/flatironinstitute/CaImAn/blob/main/caiman/source_extraction/cnmf/estimates.py),
and [HDF5 serialization](https://github.com/flatironinstitute/CaImAn/blob/main/caiman/utils/utils.py).

Validation includes synthetic CNMF-layout fixtures and a full CaImAn 1.12.1
CNMF fit of the official `demoMovie.tif` (2,000 frames, 15 components), with
trace, tracking, crop, trim and aligned-video exports checked in MINISYNC.
The demo's timestamps, behavior and tracking are explicitly simulated;
synchronization with real acquisition clocks remains to be validated.

To regenerate the demonstration with a working CaImAn installation:

```bash
python scripts/create_caiman_demo.py --source /path/to/demoMovie.tif --output /path/to/new_demo_folder
```

The output directory must not already exist. The package contains a Spanish
loading guide, provenance, SHA-256 checksums, and optional missing-data cases.

## Calcium and movement analysis

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
