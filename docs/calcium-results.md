# CaImAn CNMF results

[Back to CALI](../README.md)


Load **CaImAn HDF5** to open a `.hdf5` or `.h5` result saved with
`cnm.save(...)`. CALI reads the file directly with `h5py`; installing or
running the CaImAn analysis pipeline is not required. NWB and pickle results
are not supported by this importer.

In the **Calcium** tab:

- Select an original, zero-based component ID and filter by the quality labels
  saved by CaImAn. Files without quality evaluation show all components.
- Choose `C` (denoised temporal component), `C + YrA` (including residuals),
  `F_dff` (ΔF/F), or `S` (deconvolved activity), when present in the file.
  CALI displays saved results without recalculating normalization or
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

The earlier validation reported below is separate from the
[detailed processing validation record](processing-validation.md).

Validation includes synthetic CNMF-layout fixtures and a full CaImAn 1.12.1
CNMF fit of the official `demoMovie.tif` (2,000 frames, 15 components), with
trace, tracking, crop, trim and aligned-video exports checked in CALI.
The demo's timestamps, behavior and tracking are explicitly simulated;
synchronization with real acquisition clocks remains to be validated.

To regenerate the demonstration with a working CaImAn installation:

```bash
python scripts/create_caiman_demo.py --source /path/to/demoMovie.tif --output /path/to/new_demo_folder
```

The output directory must not already exist. The package contains a Spanish
loading guide, provenance, SHA-256 checksums, and optional missing-data cases.
