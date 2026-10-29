# Motion correction and CNMF

[Back to CALI](../README.md)


Choose **Calcium analysis** in the Timeline header to process TIFFs with
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
named `caiman` or `cali-caiman` (the older `minisync-caiman` name is still
detected); interpreter paths are not exposed in the UI. For custom installations,
set the `CALI_CAIMAN_PYTHON` environment variable (`MINISYNC_CAIMAN_PYTHON` is
still accepted).
See the [CaImAn installation guide](https://caiman.readthedocs.io/en/latest/Installation.html)
for platform-specific requirements. The existing native ARM64 engine used for
local validation is recorded in [the validation report](processing-validation.md);
Rosetta is not a general requirement for CALI.

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
5. Choose **Run analysis**. A new `cali_results/calcium_*` folder is created
   beside the source TIFF (runs made before the rename are in `minisync_results/`).
   Originals and previous runs are preserved. For both
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
