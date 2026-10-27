# Motion correction and CNMF validation

Date: 2026-10-27. This records software validation, not validation of biological
cell identities or synchronization with an actual Mini2P acquisition.

## Environment

- Project viewer environment `mini2p-sync`: Python 3.11.17 ARM64, PySide6
  6.11.2, pyqtgraph 0.14.0, NumPy 2.4.6 and tifffile 2026.3.3.
- Existing project worker environment `caiman`: Python 3.11.12 ARM64,
  CaImAn 1.12.1, SciPy 1.15.2, NumPy 1.26.4 and setuptools 80.1.0.
- Initial temporary viewer: Python 3.13.2, PySide6 6.12.0, pyqtgraph 0.14.0,
  NumPy 2.5.4 and tifffile 2026.10.15; Qt offscreen on macOS Apple Silicon.
- Initial temporary worker: Python 3.11.14 Intel/Rosetta, CaImAn 1.12.1, NumPy 1.26.4,
  SciPy 1.16.3, tifffile 2024.12.12, setuptools 80.10.2.
- CaImAn 1.12.1 with SciPy 1.17 failed in deconvolution because Toeplitz
  treats multidimensional input as batches. The environment constrains
  scipy<1.17. setuptools<81 preserves the required pkg_resources import.

## Real CaImAn demonstration movie

Source: [official demoMovie.tif](https://github.com/flatironinstitute/CaImAn/blob/main/example_movies/demoMovie.tif).
SHA-256: `6f1dca4ac3329cded72c6f3ac90a725be32265db16cc6f681b522a2dd825682b`.
Downloaded for local testing, not redistributed in this repository. The
repository license and any data-specific terms should be checked before
redistribution. This file does not establish ScanImage multichannel support.

Processed all 2,000 frames (60 × 80 pixels), rigid motion correction, max
shift 6 px, gSig=3, CNMF patch half-size=15, initial K=4 per patch,
decay_time=0.4 s, SNR threshold=2, spatial correlation threshold=0.75.
**20 Hz is an assumed demonstration rate, not a verified acquisition rate.**

The worker completed correction, patch initialization, full CNMF refinement,
AR(1) deconvolution, quality evaluation and ΔF/F. Output contained 12 candidate
components (12 accepted by the configured automatic quality criteria),
`C`, `C+YrA`, `F_dff`, `S`, and matching 2,000-frame corrected TIFF and
displacement arrays. All saved C values were finite; dimensions matched the
spatial footprints. These counts are results of this configuration, not a
ground-truth cell count. No TTL or behavioral data were used in this test.

Local temporary artifacts:
`/private/tmp/minisync-pipeline-demo-rigid-v3` and
`/private/tmp/minisync-pipeline-demo-v3.log`.

## Synthetic multichannel/multifile workflow

Constructed two TIFFs from the first 300 frames of the same demo. Each TIFF
contains two interleaved channels: channel 1 constant, channel 2 the movie
with known added integer translations. These are **synthetic test files,
not original multichannel ScanImage recordings**. The chosen first Mini2P
frame, 5, is also a test setting, not a measured TTL association.

Used the actual Qt processing dialog and QProcess worker, selected channel 2,
piecewise-rigid correction (stride=24, overlap=12, max shift=6), then CNMF
with the demonstration parameters above. The worker completed with 300 frames,
9 candidate components and 7 automatically accepted components. The dialog
enabled comparison and result loading; the viewer loaded the corrected TIFF,
HDF5 and frame origin 5. The comparison window was rendered and inspected.

As an independent check of translation recovery, compared each source demo
frame with its corresponding prepared/corrected frame using OpenCV phase
correlation, a central 40 × 60 pixel crop and Hanning window. After removing
the median offset, RMS displacement fell from 1.883 px to 0.237 px. This is a
check on this constructed case, not an accuracy guarantee for real recordings.

Local temporary artifacts:
`/private/tmp/minisync-gui-validation`, including provenance, source fixtures,
the completed `calcium_*` run, `motion_validation.json` and `before_after.png`.
Temporary artifacts/environments may be removed by system cleanup.

Repeated the complete Qt/QProcess smoke test with the existing native ARM64
`mini2p-sync` viewer and `caiman` engine environments: same 300-frame fixture,
9 candidates, 7 automatically accepted, successful comparison and viewer
loading with frame origin 5. Artifacts are in
`/private/tmp/minisync-project-env-validation/calcium_20261027_151814_828587`.
The nested-event-loop smoke harness encountered a shutdown crash after printing
all successful assertions. A separate check using the application's normal
QApplication event loop verified engine auto-detection, corrected movie/result
loading, rendered comparison and clean application shutdown with exit code 0.

## Automated checks and remaining coverage

The unittest suite covers existing TTL/tracking/calcium/movement behavior plus
channel separation, source order and frame provenance, layout validation,
preservation of originals/previous outputs, failed manifests, result loading,
image comparison framing and cancellation of an actual subprocess through Qt.
In the project's existing `mini2p-sync` environment: 64 tests, all passed,
process exit code 0, without QObject shutdown warnings. The initial temporary
environments had intermittent crashes at Qt shutdown after all test assertions
passed; the same occurred with the pre-existing 53 tests alone and also with
PySide6 6.8.3. The project environment is the reference for validation; existing
project environments were inspected and used without changing their packages.

```bash
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
```

Remaining: authentic ScanImage multichannel and Mini2P TIFF validation;
multiplane/flyback support; transfer of motion shifts between channels;
scientific validation of neuron extraction on representative Mini2P data.
The current implementation processes a single chosen channel and plane per run.

## Simplified interface and two-channel sequence

The processing entry now lives in the Timeline as **Calcium analysis**. The
compact dialog reuses the loaded TIFF and metadata/TTL acquisition rate;
advanced parameters are collapsed. Engine paths, logs and comparison tabs
are removed from the user flow. Results open automatically, and selecting
**Both channels** schedules separate workers sequentially and saves a batch
manifest. Plane counts above one remain disabled.

Added tests for prefilled TIFF/rate and the two-channel job/result sequence.
The expanded suite contains 66 tests. An actual native Qt/CaImAn smoke test
processed a synthetic two-channel fixture (300 frames/channel) derived from
the demo, completed both jobs (10 candidate components each), automatically
loaded the corrected result, switched channels and exited with code 0.
The second channel was `0.9 * first_channel + 30`, not an independent biological
recording. Outputs:
`/private/var/folders/yj/_q_jvb3s223180cwln0mfmc40000gn/T/minisync-simple-1tspcsgm/minisync_results/calcium_20261027_155001_444302`.
Authentic multichannel ScanImage validation and multiplane support remain pending.

## Main-window result inspection

Added movie-frame browsing and playback, full traces without TTLs, corrected
movie rendering and a channel selector in the main Calcium tab. Successful
processing closes the setup dialog and focuses the results; saved runs reopen
with their corrected TIFF through their HDF5/manifest. Zero automatically
accepted components now select All components without altering saved quality.

The suite now includes 72 tests, covering these flows, all saved signals,
partial/absent TTL coverage, preservation of missing measured times, playback,
channel selection, saved-run reopening and invalid acquisition-rate input.
Also inspected the user's existing 2,000-frame run with 7 candidates, 0 accepted
and 200 loaded Mini2P TTL frames: all candidates and 2,000 trace samples were
visible; frame 1,501 displayed a corrected image with empty behavior coverage.
That existing run was configured at 20,000 Hz; it was inspected without changing
or recalculating it. This is a display/regression check, not scientific validation
of that parameter choice. The demo's earlier assumed processing rate was 20 Hz.
