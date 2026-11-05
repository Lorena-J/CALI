# CALI context

Initial review: 2026-10-27. This file records the behaviour observed in the
code of the working tree, including features not yet tracked in Git. Update it
when formats, synchronization, the workflow or decisions confirmed by the
project maintainer change.

## Purpose and scope

Rename (2026-10-27): the project changes from MINISYNC to CALI, matching the
logo in `cali/assets/icons/logo/`. The old `minisync*` paths that appear below
and in `docs/` are historical validation records; do not rename them. The
interface Conda environment changed from `mini2p-sync` to `cali` on 2026-10-29,
at the maintainer's request. The project folder becomes
`/Users/lorena/Developer/CALI`.

Confirmed look and feel (2026-10-29): the header uses
`cali/assets/icons/logo/cali_logo_horizontal.svg` in light mode and
`cali/assets/icons/logo/cali_logo_horizontal_dark.svg` in dark mode. The
horizontal SVG includes the name and replaces the previous icon and the
adjacent title. The right column is top-aligned with the sidebar; the theme
selector is integrated into the Mini2P header. Accents for controls, legends
and indicators use violet/magenta in day mode and yellow/peach in night mode,
derived from the logo. Dark mode must keep all interface backgrounds dark,
including controls, disabled states and dialogs. Light accents are used as
text or indicators on dark surfaces, including action buttons.
The Timeline header places Align tracking, Movement analysis and Calcium
analysis on the right, using the colours previously used by the Camera, Mini2P
and Gap labels, respectively; those three labels have been removed.
Calcium analysis reuses the Viewer accent palette in both themes; Add TIFF
uses violet/yellow; Run analysis uses lavender, with a dark violet background
and light lavender text at night (confirmed preference).
Controls, drop-downs and advanced options keep dark backgrounds at night.


CALI (CAlcium LInked Behavior explorer; formerly MINISYNC) is a local Python
desktop application for inspecting and aligning Mini2P acquisition and
behaviour video using TTL pulse CSVs. It can display images, align a tracking
coordinate, browse CaImAn CNMF results and describe associations between
calcium activity and movement. It can launch motion correction and CNMF
through CaImAn from the interface; it does not generate behaviour tracking.

Goal confirmed by the maintainer (2026-10-27): that anyone working in calcium
imaging can use it. The current implementation is centred on Mini2P. The
maintainer confirms that Mini2P must be solved well first; compatibility with
other systems is left for a later phase, with no defined scope or validation
yet. Do not broaden requirements now to cover other acquisitions.

Desired order of work:

1. Check the timestamps.
2. Align the tracking.
3. Define and discuss the downstream analysis, with CaImAn as the initial
   reference.

Confirmed decision: integrate CaImAn as CALI's background processing engine
for motion correction and component extraction via CNMF, with its results
accessible from the application. Use CaImAn as a library or computation
process; do not reimplement its algorithms. The first integration is
implemented through QProcess and a simplified configuration window.
The scope and configuration of the pipeline and of downstream analyses still
need to be defined; the existing movement analysis is therefore not considered
a final solution.

Confirmed real input: original Mini2P TIFFs coming straight out of ScanImage.
Do not assume prior motion correction. Confirmed requirement: support one or
several channels, without tying the reader to a particular acquisition
configuration; this does not change the initial Mini2P priority.
Number of planes, page organization, files per session and acquisition
metadata are still pending inspection or confirmation. Do not assume that each
TIFF page equals a single-plane/single-channel calcium frame.
The maintainer does not currently have an example recording. Public data will
be sought; do not ask her again for a recording as a requirement to progress.

### Public data located for testing (2026-10-27)

- CaImAn `example_movies/demoMovie.tif` (18.6 MB according to GitHub):
  https://github.com/flatironinstitute/CaImAn/blob/main/example_movies/demoMovie.tif
  Candidate for testing processing, already used by the project's demo
  generator. Does not demonstrate compatibility with multichannel
  Mini2P/ScanImage.
- Real ScanImage examples from NeuroConv/RoiExtractors:
  https://gin.g-node.org/CatalystNeuro/ophys_testing_data
  Provenance documented at
  https://neuroconv.readthedocs.io/en/stable/developer_guide/testing_suite.html
  and reading examples at
  https://neuroconv.readthedocs.io/en/main/conversion_examples_gallery/imaging/scanimage.html
  The documentation covers multichannel and multiple files. The search could
  not open the GIN listing: specific files, sizes, content and access still
  need to be confirmed before declaring a multichannel case validated.
- M-MINI2P, the authors' data on Dryad:
  https://doi.org/10.5061/dryad.kd51c5bkp
  Calcium TIFFs from miniaturized microscopy; calcium packages of 4.44, 7.57
  and 15.25 GB. Part of it is demultiplexed by field of view/depth. Do not
  confuse multiple FOVs or planes with fluorescence channels, nor assume they
  are original ScanImage TIFFs. Inspect before using them to validate the
  reader. The 430 MB package is voltage, not calcium.

`demoMovie.tif` has been downloaded to `/private/tmp/minisync-demoMovie.tif`
to validate processing. SHA-256:
`6f1dca4ac3329cded72c6f3ac90a725be32265db16cc6f681b522a2dd825682b`.
The other data have not been downloaded yet. Record provenance, licence and
transformations when preparing fixtures. Synthetic multichannel tests can
complement real ones but do not replace validating an authentic multichannel
ScanImage file.

Requested local test pack: `datos_prueba_minisync/`, excluded from Git via
`.gitignore`. It contains the original demo TIFF (2,000 frames), a SIMULATED
behaviour video (3,030 frames), both SIMULATED TTL CSVs, a `LEEME.md` guide,
worker configuration, provenance, hashes and a `resultados/` folder.
It contains no tracking or precomputed CNMF results. It can be regenerated with
`scripts/create_processing_test_pack.py --source /path/demoMovie.tif --output /path/new_folder`.
The video is not a real recording of an animal; there is no biological
association with the calcium. The TIFF alone is enough for processing;
synchronized viewing also uses the video and both TTL CSVs; tracking is only
needed for its specific analyses.

The timestamp problem has been left pending. The conversation moved from
reviewing features to defining the CaImAn integration. Do not interpret the
order of work above as authorization to start fixing timestamps now.

The interface, README and docs are in English. This file was translated from
Spanish to English at the maintainer's request on 2026-11-04. The language for
future interface changes has not been explicitly confirmed.

## Repository reorganization (2026-11-04, branch `reorganize-repo`)

Code moves into the `cali/` package (`cali.py` → `cali/viewer.py`), icons into
`cali/assets/icons/`, the CaImAn Conda environment into `envs/`, and `datasets/` is
created (ignored except for its README). Launch: the `cali` command (or
`python -m cali`). The worker is launched by file path
(`<engine python> cali/calcium_pipeline.py`), not with `-m`, so the engine does
not import the viewer's packages. Tests import `cali.viewer`, etc., and mocks use those names.
Not committed.

## Repository maintenance (2026-10-29)

The maintainer authorized fixing the launch/imports to `cali.py`, untracking
caches and `.DS_Store` without deleting them from disk, and preparing
installation and documentation for new users. The README is reorganized in
English with guides in `docs/` and empty screenshots of both themes, without
experimental data.
Licence chosen (2026-11-04): MIT, © 2026 Lorena Jiménez and Anna
Teruel-Sanchis (`LICENSE` at the root). Do not make commits or publish.
Names and paths in historical reports are preserved.

## Code map

| File | Responsibility |
| --- | --- |
| `cali/viewer.py` (formerly `cali.py`) | `Viewer` window, TTL loading and reconstruction, navigation, images, visual theme, trimming and exports; also contains `TrackingAlignmentDialog`. |
| `cali/caiman_results.py` | `CaImAnResults`: HDF5 reader that does not import CaImAn, matrix validation, component quality, traces, footprints and mapping of samples to Mini2P frames. |
| `cali/calcium_pipeline.py` | Qt-free worker/CLI: TIFF validation, channel separation, motion correction, CNMF, deconvolution, quality, ΔF/F and provenance. Imports CaImAn only when running the computation. |
| `cali/processing_dialog.py` | `CalciumProcessingDialog`: reuses the loaded TIFF, basic/advanced controls, internal engine detection, QProcess, per-channel jobs and automatic loading into the viewer. |
| `envs/environment-caiman.yml` | Optional engine environment, separate from the interface: Python 3.11, CaImAn 1.12.1, setuptools<81 and scipy<1.17. |
| `cali/movement_analysis.py` | Numerical computation separated from Qt: speed, valid segments, interpolation, time weights, per-cell summary and lagged correlation. |
| `cali/movement_dialog.py` | `MovementAnalysisDialog`: configuration, per-cell table, plots, ROI selection, result invalidation and export. Receives the tracking class as a factory to reuse its reader and mapping. |
| `scripts/create_caiman_demo.py` | Generator for a demo with a real CNMF fit and simulated auxiliary data. Requires a separate CaImAn environment. |
| `tests/` | `unittest` tests with synthetic data, plus Qt workflow and export tests. |
| `cali/assets/icons/` | Icons and logos loaded at runtime (includes `logo/mini2p_logo_mark.png`, currently unused). |
| `cali/__init__.py`, `cali/__main__.py` | Package with no imports (the CaImAn worker has no Qt) and `python -m cali` launch. |
| `pyproject.toml`, `uv.lock` | Package metadata, `cali` command (`cali.viewer:main`), pins (`[tool.uv] constraint-dependencies`) and uv lock. |
| `datasets/` | Local test data; only `README.md` is versioned. |
| `README.md` | Launch instructions and detailed description of CaImAn and movement. |

There is no application packaging, server or database. A local GitHub Actions
workflow was added for the Qt suite on macOS/Python 3.11; it has not run on
GitHub yet. `requirements-lock.txt` pins interface dependency versions, without
locking system libraries or the CaImAn environment. Session state lives in
memory; no session save/restore has been found.
Navigation is manual via the cursor, clicks and frame controls.

## Launch and environment

Dependencies in `requirements.txt`: PySide6, pyqtgraph, opencv-python,
tifffile, pandas, numpy and h5py, with pinned versions. `requirements-lock.txt`
adds the transitive dependencies.

Installation preference confirmed by the maintainer (2026-11-04): install the
viewer with uv, not Conda. The viewer Conda recipe `envs/environment.yml` was
removed. CaImAn stays on Conda (`envs/environment-caiman.yml`) because it is
distributed through conda-forge; the `caiman` package on PyPI is an unrelated
MicroPython tool, so never install CaImAn with `pip`/`uv pip install caiman`.

Confirmed (2026-11-04): typing `cali` in a terminal must open the app. It is
installed as a uv tool, editable from the repository:

```bash
uv tool install --python 3.11 --editable . -c requirements-lock.txt
cali
```

Development: `uv sync`, then `uv run cali` / `uv run python -m unittest ...`.
`uv run` regenerates `uv.lock` from `pyproject.toml`; the `[tool.uv]`
constraints keep it on the tested pins.

Run from an environment that contains those dependencies. Do not assume that
`python`, `python3` and the Conda interpreter are equivalent.

Environment observed during this review, not established as a requirement:

- macOS machine; repository at `/Users/lorena/Developer/mini2p_sync_viewer`.
- `python3`: Homebrew Python 3.13.2, without numpy or h5py.
- `/Users/lorena/miniconda3/bin/python`: Python 3.11.5; none of the seven
  dependencies detected; empty Conda environments directory.
- The usual runtime environment and the location of recordings or of the
  prepared demo have not been identified yet.

**Usual environment, later confirmed by the maintainer and located:**
`cali` (formerly `mini2p-sync`) in the Homebrew Conda installation.
Use this environment in future sessions; the initial inspection above only
covered another Conda installation and does not describe the active one.

- Interface: `/opt/homebrew/Caskroom/miniconda/base/envs/cali/bin/python`
  (Python 3.11.17 ARM64, PySide6 6.11.2, pyqtgraph 0.14.0, NumPy 2.4.6,
  tifffile 2026.3.3, pandas 3.0.6 and h5py 3.16.0).
- Pre-existing engine: `/opt/homebrew/Caskroom/miniconda/base/envs/caiman/bin/python`
  (Python 3.11.12 ARM64, CaImAn 1.12.1, SciPy 1.15.2, NumPy 1.26.4,
  setuptools 80.1.0). No packages have been changed in these existing
  environments.
- Usual launch before the switch to uv: `conda activate cali` and
  `python -m cali` from the repository root. The existing `cali` Conda
  environment still works; new installations use the `cali` uv tool.
- The dialog detects the `caiman` environment as the engine Python, if it
  exists, as a sibling of the viewer environment or in the Conda `envs/` folders
  (via `CONDA_EXE` or the usual Conda roots in `CONDA_ROOTS`, needed when the
  viewer runs from a uv `.venv`); it does not show the path or a Python selector. It also recognizes
  the sibling `cali-caiman` (and the old `minisync-caiman`) and the
  `CALI_CAIMAN_PYTHON` variable (and the old `MINISYNC_CAIMAN_PYTHON`) for
  deployment. Do not import CaImAn inside Qt.

**Temporary validation** environments were created during implementation:
`/private/tmp/minisync-viewer-env` (Python 3.13, requirements dependencies)
and `/private/tmp/minisync-caiman-env` (Python 3.11 Intel/Rosetta, CaImAn
1.12.1). Do not assume they will survive system cleanup or that they are the
maintainer's usual environment. The engine Python is resolved by internal
logic.

Compatibility issues found at runtime: CaImAn 1.12.1 imports `pkg_resources`
(requires setuptools<81) and its deconvolution fails with SciPy 1.17's batched
Toeplitz (use scipy<1.17; validated with 1.16.3). Do not fix this by modifying
CaImAn's algorithms or silently removing deconvolution.

## Inputs and time conventions

### TTL and common clock

- Both TTL CSVs require `frame` and `timestamp_ms`. They may contain
  additional columns, such as `elapsed_ms`.
- `load_csv` converts frames to integers and times to floats; it rejects empty
  tables and decreasing times. It does not exhaustively validate finiteness,
  time uniqueness or ID integrity before converting them. Some downstream
  functions require strictly increasing times.
- `Viewer.rebuild()` sets `t0` to the first Mini2P `timestamp_ms` and
  subtracts **that same origin** from both series. The main axis is in
  milliseconds. The camera may start at a negative relative time.
- The maintainer confirms that both TTL CSVs are recorded by the same
  Arduino/device. The code assumes timestamps comparable on a common clock; it
  does not estimate offsets between independent clocks or correct drift.
  Hardware model, firmware, source units and possible counter resets or
  overflows are still pending confirmation.

### Camera reconstruction and mapping to video

- `median_period` takes the median of positive intervals.
- `virtual_camera_indices` estimates jumps with
  `max(1, round(interval / median_period))` and accumulates them from zero.
- `load_camera` always calls `fill_camera_timestamps`: if it detects jumps, it
  inserts rows between the recorded TTLs, interpolates their times between the
  measured endpoints and rebuilds consecutive IDs from the first `frame`.
  If `elapsed_ms` exists, it is recomputed relative to the first camera TTL.
  Other columns in the new rows may be left empty.
- It does not add times before the first TTL or after the last one. It keeps
  the measured endpoint times; inserted times are estimates.
  There is no explicit column marking each row as measured or reconstructed.
- This operation happens **before** the mapping mode is selected. Both modes
  work on the already processed CSV; `TTL index` does not recover the raw rows.
- Internal video index, zero-based:
  - `Timing reconstruction`: `offset + camera_virtual[TTL index]`.
  - `TTL index`: `offset + TTL index`.
- Default offset: zero; negative and positive values are allowed. It is not a
  time shift in milliseconds but a shift in frames.
- The reconstruction hypothesis is that TTL records are missing from an
  approximately periodic camera. This alone does not prove that all the
  corresponding frames exist in the video. Validate with a real acquisition.
- Gaps are detected as intervals longer than 1.5 times the median period, on
  the working series; reconstruction may remove visible gaps.

### Images and navigation

- Mini2P `frame` is used as a one-based ID: TIFF page = `frame - 1`.
  One multipage TIFF is opened at a time; there is no assembly of multiple
  files.
- Video read by OpenCV, TIFF by tifffile; LRU caches of 80 and 40 frames.
- For the chosen time, each viewer selects the nearest TTL via `nearest`. It
  may show an endpoint even when the cursor is outside coverage; this is not
  the same as the analyses' coverage policy.
- Left/right arrows: previous/next Mini2P frame.
  PageUp/PageDown: previous/next camera gap.
- Images are fitted to the panel; greyscale rendering uses `gray8`.
  Display transformations do not redefine CaImAn signals.

## Tracking

`TrackingAlignmentDialog` accepts plain CSV and three-header DeepLabCut CSV.
For DLC it combines the body part/coordinate labels and keeps the original
index as `frame_index`.

- `frame_index`, `frame_idx`, `index` and `Unnamed: 0` are interpreted as
  zero-based.
- `frame`, `frame_number` and `frame_id` are interpreted as one-based, unless
  an explicit zero appears, which identifies zero-based.
- Indices must be finite, integer, unique and increasing. With a video, they
  must fit within it. Without a frame column, consecutive rows are assigned;
  with a video, the number of rows must equal the number of frames.
- `build_video_times` applies mode and offset; interpolates times between
  covered TTLs, respects the trim and leaves NaN outside the available
  endpoints.
- The window aligns **one selected numeric column**, usually X.
  It offers camera times or one row per Mini2P frame.
- Positions are interpolated linearly within the configured gap limits; no
  extrapolation. By default two missing frames are allowed. This dialog's gap
  policy differs from that of the movement analysis.
- In Mini2P mode it keeps the rows of the full series; positions outside the
  trim/coverage are left empty.
- Exports a CSV with interpolation neighbours, alpha, nearest real video frame
  and time difference. The aligned video uses that nearest frame; it repeats
  frames where appropriate and writes blank images without coverage.
- The aligned MP4 has a constant FPS estimated from the median of target
  intervals; exact times are kept in the associated `.mapping.csv`.

## CaImAn

### Implemented processing

- `Calcium analysis` button in Timeline, next to Align tracking and Movement
  analysis; not in Files. It does not need TTLs to compute; later
  synchronization still needs the real TTLs.
- Reuses the TIFF open in the viewer (use `tif.filehandle.path`, since
  `tif.filename` returns only the name). Add TIFF adds files; the trash button
  clears the selection without deleting files from disk. There is no path
  whitelist and no text reorder/remove buttons.
- Basic interface: Frame rate (Hz), Channels and Planes, More options and Run
  analysis. Keep it simple at the maintainer's explicit request: no
  introduction, no configuration/before-after tabs, no technical file
  information, no Python paths and no visible log/steps panel.
- Labelled Frame rate, not Firing rate: it is the acquisition rate per
  channel, not neuronal firing. Prefers ScanImage metadata, then the median of
  Mini2P TTL intervals; it is editable, and without that data it is left empty
  to be filled in.
- Processes one channel or Both channels as independent sequential jobs.
  Supports several TIFFs with compatible dimensions/layout and complete cycles.
  Saves automatically next to the TIFF in `cali_results/calcium_*` (formerly
  `minisync_results/`); both channels produce subfolders and `batch.json`.
  Results are opened only when all jobs complete; failure/cancellation stops
  the sequence and keeps partial outputs.
- Detects ScanImage saved channels or an explicit C axis; without metadata, it
  asks for the number of interleaved channels. Planes is a drop-down with 1
  available and the others disabled: the engine does not yet support
  volume/flyback.
- Rejects known multiple planes, flyback, RGB and incompatible axes. An
  ambiguous 3D ZYX stack (such as CaImAn's ImageJ demo) is interpreted
  according to the single-plane selection. Do not claim volumetric support or
  validated real multichannel support without an authentic file.
- CaImAn performs rigid or piecewise motion correction, initializes patch-based
  CNMF with p=0 and refines with AR(1), evaluates quality without CNN and
  computes ΔF/F.
- One headless worker, limited to one native thread and no external cluster;
  do not block Qt with synchronous computation calls. Cancellation with
  terminate and a delayed kill; closing the application is prevented while a
  computation is running.
- Each run creates a new folder; originals are preserved. Saves the TIFF of
  the selected channel and the corrected TIFF used for CNMF, HDF5, shifts, a
  mapping of each sample to TIFF/page/channel/Mini2P frame, source hashes,
  resolved parameters and status. Keeps intermediate memory maps; plan space
  for several float32 copies. Failures/cancellation keep partial outputs.
- Automatically loads the corrected TIFF and the configured first frame
  (`tiff_first_frame`) into the viewer, closes the configuration window and
  activates Calcium on the main screen. ROI, signal, channel, Play and frame
  controls are on that screen; do not force going back to the dialog to view
  results. When both channels are processed it offers a channel selector in
  Calcium. The relationship with TTL IDs is declared by the user, not derived
  from the number of pages.
- Processed results are shown in full by Movie frame (one-based), even without
  TTLs or with partial coverage. Play/slider/frame field/cursor select the same
  sample and corrected page; ROIs and signals are kept. Behaviour is
  synchronized only if a measured TTL time exists for that sample; outside
  coverage the behaviour viewer is cleared, without inventing times. The Movie
  frame axis is not linked to the Arduino ms axis in the Timing tab.
- If Accepted is empty, start in All components and explain that none passed
  quality. Do not modify the saved labels or call those candidates accepted.
  Avoid an empty screen caused only by the initial filter.
- CaImAn HDF5 also allows reopening processing.json/batch.json; selecting an
  HDF5 with an associated manifest loads the corrected TIFF, not just the
  traces.
- Export of the processed result: all samples, measured TTL times where they
  exist and NaN outside coverage; the trim limits the exported rows.
  Playback is a preview at the configured rate, capped at 60 fps. The engine
  rejects rates outside 0.001–1000 Hz.
- For now it does not transfer shifts from a structural channel to a
  functional one; each chosen channel is processed independently.

### Reading results

- Accepts `.h5`/`.hdf5` saved with `cnm.save(...)`; requires `estimates/C`, a
  components × samples matrix. NWB and pickle are not supported.
- Reads selected trace rows and spatial columns via h5py.
  CaImAn does not need to be installed to browse results.
- Signals: `C`, `C+YrA`, `F_dff`, `S`, depending on availability. Does not
  recompute normalization or deconvolution. `C` is the denoised signal; `S` is
  deconvolved activity, not a record of measured spikes.
- CaImAn component and sample IDs are zero-based, even after filtering
  accepted/rejected. Absence of evaluation is not the same as rejection.
- CaImAn sample = `mini2p_frame - first_mini2p_frame`, with the configured
  first frame one-based and an initial value of 1. No calcium interpolation;
  outside coverage the value is NaN. Downsampling, reordering or temporal
  concatenation are not handled by that single parameter.
- Footprints `A`: dense or CSC, pixels × components, Fortran reshape.
  2D spatial dimensions are optional; traces alone can be browsed.
- ROI drawn at 20% of the maximum. Requiring matching dimensions does not
  guarantee spatial registration: it must correspond to the same field and
  coordinate system.
- Without a TIFF frame it shows `Cn` or the footprint as a labelled static
  reference.
- Trace export applies the time trim and keeps IDs and relative time.

## Movement and activity

Requires both TTL CSVs, CaImAn and tracking referred to the original behaviour
video that matches the loaded mapping. Do not use tracking already resampled to
Mini2P as input. It can work without video; use explicit indices to avoid
ambiguity. Reuses the tracking from the alignment dialog if it was open when
the movement window was first created.

- Speed from X/Y of the same body point, with `np.gradient` with respect to
  measured times in seconds, or from a non-negative speed column.
- The selected units describe the file; they do not calibrate or convert px.
- Optional confidence filtering, configurable temporal median and a limit on
  the inter-frame interval. Zero smoothing disables the filter.
- NaN, low confidence, skipped frames and excessive times split segments; do
  not interpolate speed across those gaps or outside coverage.
- Speed >= threshold: movement; below: rest. No coverage: unknown.
- Applies the CaImAn first frame and the time trim. Per-state means weighted
  by observed duration: each valid adjacent interval contributes half to each
  endpoint, without adding duration at the ends or between segments.
- Pearson uses paired finite samples, without time weighting. Fewer than three
  pairs or a constant signal gives NaN. Without both states, the difference of
  means is undefined. These are descriptive statistics, without p-values.
- Positive lag: `calcium(t)` versus `speed(t - lag)`; calcium follows
  movement. Coverage may vary between lags. It is exploratory.
- Selecting a row focuses that ROI in the viewer. Clicks on time plots
  synchronize the viewers; the dialog's axes show seconds.
- Changing parameters/sources/mapping/trim invalidates results and blocks
  their export until recomputed. A generation counter prevents accepting stale
  results if parameters change during the computation.
- Exports a new `movement_*` folder with `per_cell_summary.csv`,
  `aligned_movement.csv`, `roi_<id>_aligned.csv`, `roi_<id>_lag.csv` and
  `analysis_settings.json` with provenance and parameters.

## Trimming and exports

- Time trim: end selected by camera TTL; automatically up to the last camera
  TTL not later than the last Mini2P one. It is not a start trim.
- Exporting the trim creates `trimmed_*` with `camera_trimmed.csv`,
  `behavior_trimmed.mp4`, `trim_info.json`. Keeps the video prefix up to the
  mapped frame; the CSV comes from the already reconstructed camera table.
- Rectangular spatial crop on the video: original coordinates, even dimensions
  for encoding. Exports `cropped_*` with `behavior_cropped.mp4` and
  `crop_info.json`. It is also applied to the time export or aligned video.
- Video exports use OpenCV and the `mp4v` codec; audio is not preserved.
  By design they do not replace the originals. There is no general transaction
  that rolls back all files if an export fails; check the outputs.

## Validation and limits of what has been checked

```bash
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
```

Existing coverage: TTL reconstruction and jitter; tracking and DLC, indices,
gaps, trim and aligned video; HDF5 reading, ROI orientation, signal types and
cursor; speed, duration, confidence, lags, invalidation and movement export.
Tests create temporary fixtures.

The initial review with the system Python failed because of missing
dependencies. After creating the interface environment, the tests were run,
including engine failure and cancellation of a real process. The processing
window was rendered and inspected in offscreen Qt. Validation details are in
`docs/processing-validation.md`: a real 2,000-frame demo with rigid correction
(12 candidate components), and a synthetic multichannel/multi-file QProcess
flow with piecewise correction (300 frames, 9 candidates). Both completed CNMF
and loaded compatible results. This is not equivalent to validating an
authentic multichannel ScanImage TIFF or cell identities.
With the usual `mini2p-sync` environment, before simplification: 64 tests
passed, exit code 0 and no QObject destruction warnings. The temporary test
environments showed intermittent Qt shutdown problems (also with earlier
tests); do not use them as a reference instead of the usual environment.
Opening/loading/closing through the normal QApplication loop was also checked
in the usual environment, with exit code 0; details and limits of the test
scripts are in the report.

After simplifying the interface: the suite grew to 66 tests, with reuse of the
TIFF/TTL rate and the Both channels sequence. A real Qt/QProcess test with two
synthetic 300-sample channels completed both CNMF runs (10 candidates per
channel), automatic loading and channel switching, with exit code 0.

The README states an earlier validation with CaImAn 1.12.1 on `demoMovie.tif`
(2,000 frames, 15 components); it was not reproduced here. The script
generates a real CNMF, but the TTL clocks, behaviour video and tracking are
simulated, with no biological relationship to the calcium. Its 20 Hz clock is
a demo assumption, not the documented rate of the original acquisition.
Synchronization with real acquisition clocks is still pending according to
the README. The generator requires `--source` and a new, non-existing
`--output`.

## Criteria for future changes

- Distinguish facts from the code, validations performed and decisions still
  pending. Do not turn demo assumptions into facts about the experiment.
- Keep index bases, units, measured/reconstructed times and coverage explicit.
  Avoid filling missing activity with zero or calling unknown tracking rest.
- When changing synchronization, review its effects on the viewer, tracking,
  CaImAn, movement, trimming and exported provenance information.
- Preserve other people's local changes. In the initial review only README,
  requirements and sync_viewer were in Git; the CaImAn/movement modules, tests,
  scripts and resources were untracked. Do not delete them for that reason.
- Do not add experimental data, heavy results or environments to the
  repository without an explicit decision. Do not commit/publish as part of
  this review.
- Possible improvements identified, not tasks already authorized: validate TTL
  inputs more rigorously, distinguish reconstructed TTL rows, clarify the two
  modes after reconstruction and make the environment reproducible.

## Information pending from the maintainer

1. Specific experiment and scientific goal; features used with real data
   versus features still experimental. The general audience and the order
   timestamps → tracking → analysis are already confirmed above.
2. Hardware/firmware of the shared Arduino/device, CSV generation, usual
   losses (TTL, video frames or both), possible resets or overflows and the
   method for determining the offset.
3. Usual runtime environment and location of authorized test data.
4. Original ScanImage TIFFs, single/multi-channel support and the lack of an
   own example are already confirmed: specify planes, dimensions, files per
   session, metadata and correspondence with TTLs; inspect a real acquisition
   before defining pipeline preparation.
5. Tracking tool/format, body point and unit calibration; how confidence,
   movement threshold and tolerated gap are chosen.
6. Upcoming priorities and collaboration preferences, interface language,
   distribution to other users and versioning strategy.

These questions are pending; do not assume answers or an approved roadmap.
