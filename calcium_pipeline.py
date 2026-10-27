"""TIFF preparation and an isolated, reproducible CaImAn processing job.

Importing this module does not import CaImAn. Run the CLI with the Python
interpreter of a CaImAn environment; the viewer can use a different environment.
"""
import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import hashlib
from importlib.metadata import version
import math
import os
from pathlib import Path
import re
import sys
import traceback

# Must precede NumPy as well as CaImAn imports in the worker process.
if __name__ == "__main__":
    for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[_name] = "1"
    os.environ.setdefault("MPLBACKEND", "Agg")

import numpy as np
import tifffile


@dataclass
class PipelineSettings:
    sources: list
    output: str
    frame_rate: float = 0.0
    channels: int = 1
    channel_index: int = 0
    single_plane_confirmed: bool = False
    first_mini_frame: int = 1
    pw_rigid: bool = False
    max_shift: int = 6
    patch_stride: int = 48
    patch_overlap: int = 24
    decay_time: float = .4
    neuron_half_size: int = 4
    components_per_patch: int = 4
    cnmf_patch_half_size: int = 25
    min_snr: float = 2.0
    rval_thr: float = .85

    def validate(self):
        if not self.sources or len(set(map(str, self.sources))) != len(self.sources):
            raise ValueError("Choose distinct TIFF files in acquisition order.")
        for field in ("frame_rate", "decay_time", "min_snr"):
            if not math.isfinite(getattr(self, field)) or getattr(self, field) <= 0:
                raise ValueError(f"{field} must be finite and positive.")
        if not .001 <= self.frame_rate <= 1000:
            raise ValueError("Frame rate must be between 0.001 and 1000 Hz (acquisition rate, not neuronal firing rate).")
        for field in ("channels", "first_mini_frame", "max_shift", "patch_stride",
                      "patch_overlap", "neuron_half_size", "components_per_patch", "cnmf_patch_half_size"):
            value = getattr(self, field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{field} must be a positive integer.")
        if (not isinstance(self.channel_index, int) or isinstance(self.channel_index, bool)
                or not 0 <= self.channel_index < self.channels):
            raise ValueError("Selected channel is outside the saved channel range.")
        if not math.isfinite(self.rval_thr) or not -1 <= self.rval_thr <= 1:
            raise ValueError("Spatial correlation threshold must be between -1 and 1.")
        if not self.single_plane_confirmed:
            raise ValueError("Confirm a single imaging plane. Volumetric acquisitions are not supported yet.")
        if self.cnmf_patch_half_size <= self.neuron_half_size:
            raise ValueError("CNMF patch half-size must exceed the expected neuron half-size.")


def _numbers(value):
    if isinstance(value, str):
        return [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", value)]
    return np.asarray(value).ravel().astype(float).tolist()


def inspect_tiff(path):
    """Read layout only; never infer an unknown channel order from image content."""
    path = Path(path).resolve()
    with tifffile.TiffFile(path) as tif:
        series = tif.series[0]
        shape, axes = tuple(series.shape), series.axes
        pages = len(tif.pages)
        # ScanImage may expose a C axis, but each saved channel is still a
        # separate grayscale page. Reject RGB/volumetric axes, not the C axis.
        if (len(tif.series) != 1 or axes[-2:] != "YX" or len(shape) < 2
                or (axes != "ZYX" and any(axis not in "TIQC" for axis in axes[:-2]))
                or len(tif.pages[0].shape) != 2):
            raise ValueError(f"{path.name}: expected 2D grayscale pages in a single time series; got {axes} {shape}.")
        if series.dtype.kind not in "biuf":
            raise ValueError(f"{path.name}: unsupported pixel type {series.dtype}.")
        # ImageJ labels CaImAn's demo as ZYX although it is a time movie.
        # An ambiguous 3D stack requires the explicit single-plane confirmation
        # enforced by settings.validate; known ScanImage Z metadata still wins.
        if pages != int(np.prod(shape[:-2])):
            raise ValueError(f"{path.name}: TIFF pages do not match the time dimension.")
        if "C" in axes and axes[-3] != "C":
            raise ValueError(f"{path.name}: channels must be interleaved, not stored as separate channel blocks.")
        metadata = tif.scanimage_metadata if tif.is_scanimage else None
        data = (metadata or {}).get("FrameData", {})
        saved = data.get("SI.hChannels.channelSave")
        channels = _numbers(saved) if saved is not None else None
        if channels is not None and (not channels or len(set(channels)) != len(channels)
                                     or any(not math.isfinite(x) or x < 1 or x != int(x) for x in channels)):
            raise ValueError(f"{path.name}: invalid ScanImage channelSave metadata.")
        for key in ("SI.hStackManager.numSlices", "SI.hStackManager.actualNumSlices"):
            if key in data and any(x > 1 for x in _numbers(data[key])):
                raise ValueError(f"{path.name}: multiple imaging planes are not supported in this first pipeline.")
        if any(x > 0 for x in _numbers(data.get("SI.hFastZ.numDiscardFlybackFrames", 0))):
            raise ValueError(f"{path.name}: flyback frames require an explicit plane/frame mapping.")
        rate = data.get("SI.hRoiManager.scanFrameRate")
        rate_values = _numbers(rate) if rate is not None else []
        if rate_values and (len(rate_values) != 1 or not math.isfinite(rate_values[0]) or rate_values[0] <= 0):
            raise ValueError(f"{path.name}: invalid ScanImage sampling rate metadata.")
        return {"path": str(path), "pages": pages, "height": shape[-2], "width": shape[-1],
                "dtype": str(series.dtype), "scanimage": bool(tif.is_scanimage),
                "axis_channels": shape[axes.index("C")] if "C" in axes else None,
                "channel_ids": [int(x) for x in channels] if channels else None,
                "frame_rate": rate_values[0] if len(rate_values) == 1 else None}


def inspect_sources(settings):
    settings.validate()
    layouts = [inspect_tiff(path) for path in settings.sources]
    first = layouts[0]
    for layout in layouts:
        if (layout["height"], layout["width"]) != (first["height"], first["width"]):
            raise ValueError("All source TIFFs must have matching image dimensions.")
        if layout["channel_ids"] != first["channel_ids"]:
            raise ValueError("Source TIFFs have different or missing ScanImage channel metadata.")
        if (layout["frame_rate"] is not None and first["frame_rate"] is not None
                and not np.isclose(layout["frame_rate"], first["frame_rate"], rtol=1e-4)):
            raise ValueError("Source TIFFs have different ScanImage acquisition rates.")
        if layout["channel_ids"] is not None and len(layout["channel_ids"]) != settings.channels:
            raise ValueError("Saved channel count disagrees with ScanImage metadata.")
        if layout["axis_channels"] is not None and layout["axis_channels"] != settings.channels:
            raise ValueError("Saved channel count disagrees with the TIFF channel axis.")
        if layout["pages"] % settings.channels:
            raise ValueError("Each TIFF must contain complete channel cycles; split cycles are not supported.")
    count = sum(layout["pages"] // settings.channels for layout in layouts)
    if count < 100:
        raise ValueError("At least 100 time samples in the selected channel are required for this pipeline.")
    if settings.max_shift * 2 >= min(first["height"], first["width"]):
        raise ValueError("Maximum motion shift is too large for these image dimensions.")
    if settings.pw_rigid and settings.patch_stride + settings.patch_overlap > min(first["height"], first["width"]):
        raise ValueError("Motion patch stride + overlap exceeds image dimensions. Reduce these settings.")
    return layouts, count


def prepare_movie(settings, layouts, output):
    """Stream one selected interleaved channel; preserve order and pixel values."""
    prepared = output / "selected_channel.tif"
    with tifffile.TiffWriter(prepared, bigtiff=True) as writer, (output / "frame_mapping.csv").open("w", newline="") as handle:
        mapping = csv.writer(handle)
        mapping.writerow(["caiman_sample_zero_based", "mini2p_frame", "source_tiff", "source_page_zero_based", "channel_index_zero_based", "channel_id"])
        sample = 0
        for layout in layouts:
            with tifffile.TiffFile(layout["path"]) as tif:
                for page in range(settings.channel_index, layout["pages"], settings.channels):
                    frame = tif.pages[page].asarray().astype(np.float32)
                    if not np.all(np.isfinite(frame)):
                        raise ValueError(f"Non-finite pixels in {layout['path']}, page {page}.")
                    writer.write(frame, photometric="minisblack", contiguous=True, metadata=None)
                    channel_id = layout["channel_ids"][settings.channel_index] if layout["channel_ids"] else ""
                    mapping.writerow([sample, settings.first_mini_frame + sample, layout["path"], page, settings.channel_index, channel_id])
                    sample += 1
    return prepared


def write_manifest(path, manifest):
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_pipeline(settings, progress=print):
    """Run in a dedicated process, serial CaImAn workers, no GUI imports."""
    layouts, expected_count = inspect_sources(settings)
    output = Path(settings.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    manifest_path = output / "processing.json"
    manifest = {"status": "running", "started_utc": datetime.now(timezone.utc).isoformat(),
                "settings": asdict(settings), "sources": layouts, "python": sys.version,
                "numpy_version": np.__version__, "tifffile_version": tifffile.__version__,
                "random_seed": 0,
                "mapping": "Single plane, interleaved saved channels in declared order; no temporal resampling. Mini2P frame association is user supplied.",
                "border_policy": "Copy border pixels during correction; CNMF excludes a border equal to the maximum applied displacement.",
                "intensity_policy": "Selected source pixels are converted to float32; CaImAn may add a constant offset to ensure a nonnegative corrected movie.",
                "outputs": {}}
    def stage(message):
        progress(message)
        manifest["stage"] = message
        write_manifest(manifest_path, manifest)
    try:
        stage("Recording source checksums")
        for layout in layouts:
            digest = hashlib.sha256()
            with open(layout["path"], "rb") as handle:
                for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                    digest.update(chunk)
            layout["sha256"] = digest.hexdigest()
        stage("Preparing selected channel")
        prepared = prepare_movie(settings, layouts, output)
        # Keep intermediate/cache writes local to this run, never beside originals.
        os.environ["CAIMAN_TEMP"] = str(output)
        for key, directory in (("MPLCONFIGDIR", "matplotlib"), ("NUMBA_CACHE_DIR", "numba"),
                               ("XDG_CACHE_HOME", "xdg")):
            cache = output / ".cache" / directory
            cache.mkdir(parents=True, exist_ok=True)
            os.environ[key] = str(cache)
        stage("Loading CaImAn engine (first import may take several minutes)")
        if version("caiman") == "1.12.1" and tuple(map(int, version("scipy").split(".")[:2])) >= (1, 17):
            raise RuntimeError("CaImAn 1.12.1 requires scipy<1.17 for this pipeline. Use environment-caiman.yml.")
        np.random.seed(0)
        import caiman as cm
        from caiman.motion_correction import MotionCorrect
        from caiman.source_extraction.cnmf.cnmf import CNMF
        from caiman.source_extraction.cnmf.params import CNMFParams
        from caiman.summary_images import local_correlations_movie_offline
        manifest["caiman_version"] = cm.__version__
        stage("Correcting motion (piecewise rigid)" if settings.pw_rigid else "Correcting motion (rigid)")
        motion = MotionCorrect([str(prepared)], dview=None, max_shifts=(settings.max_shift,) * 2,
                               pw_rigid=settings.pw_rigid, strides=(settings.patch_stride,) * 2,
                               overlaps=(settings.patch_overlap,) * 2, border_nan="copy")
        motion.motion_correct(save_movie=True)
        if settings.pw_rigid:
            x, y = np.asarray(motion.x_shifts_els), np.asarray(motion.y_shifts_els)
            np.savez(output / "motion_shifts.npz", x_shifts=x, y_shifts=y)
            border = int(np.ceil(max(np.max(np.abs(x)), np.max(np.abs(y)))))
        else:
            shifts = np.asarray(motion.shifts_rig)
            np.savez(output / "motion_shifts.npz", shifts_rig=shifts)
            border = int(np.ceil(np.max(np.abs(shifts))))
        stage("Preparing corrected movie for CNMF")
        mapped_path = cm.save_memmap(motion.mmap_file, base_name=str(output / "cnmf_"), order="C", border_to_0=border)
        mapped, dims, count = cm.load_memmap(mapped_path)
        if count != expected_count:
            raise RuntimeError("Motion correction changed the expected frame count.")
        images = mapped.T.reshape((count, *dims), order="F")
        corrected_path = output / "motion_corrected.tif"
        # This is the exact movie used for CNMF, including its excluded border.
        with tifffile.TiffWriter(corrected_path, bigtiff=True) as writer:
            for frame in images:
                writer.write(np.asarray(frame), photometric="minisblack", contiguous=True, metadata=None)
        params = CNMFParams(params_dict={
            "data": {"fnames": [str(corrected_path)], "fr": settings.frame_rate, "decay_time": settings.decay_time},
            "preprocess": {"p": 0}, "temporal": {"p": 0},
            "init": {"K": settings.components_per_patch, "gSig": [settings.neuron_half_size] * 2,
                     "nb": 2, "method_init": "greedy_roi", "ssub": 1, "tsub": 1},
            "patch": {"rf": settings.cnmf_patch_half_size, "stride": max(1, settings.cnmf_patch_half_size // 2),
                      "only_init": True, "border_pix": border},
            "merging": {"merge_thr": .8},
            "quality": {"min_SNR": settings.min_snr, "rval_thr": settings.rval_thr, "use_cnn": False}})
        stage("Fitting CNMF patches")
        initial = CNMF(1, params=params, dview=None)
        initial.fit(images)
        if initial.estimates.C is None or initial.estimates.C.shape[0] == 0:
            raise RuntimeError("CNMF found no components. Review neuron size and patch settings.")
        stage("Refining CNMF and deconvolving activity")
        initial.params.change_params({"preprocess": {"p": 1}, "temporal": {"p": 1}})
        model = initial.refit(images, dview=None)
        stage("Evaluating components and calculating delta F/F")
        model.estimates.evaluate_components(images, model.params, dview=None)
        model.estimates.detrend_df_f(quantileMin=8, frames_window=min(250, count))
        correlations = local_correlations_movie_offline(mapped_path, window=min(500, count), stride=min(500, count), dview=None)
        model.estimates.Cn = np.nan_to_num(np.max(correlations, axis=0))
        model.params.to_jsonfile(str(output / "caiman_parameters.json"))
        model.mmap_file = mapped_path
        result_path = output / "cnmf_results.hdf5"
        stage("Saving CaImAn results")
        model.save(str(result_path))
        from caiman_results import CaImAnResults
        result = CaImAnResults(result_path)
        if result.n_frames != expected_count or not {"S", "F_dff"}.issubset(result.trace_types):
            raise RuntimeError("Saved CNMF result is missing expected frames or temporal signals.")
        manifest.update(status="complete", finished_utc=datetime.now(timezone.utc).isoformat(),
                        frames=count, components=result.n_components, accepted=len(result.component_ids("accepted")),
                        border_pixels=border,
                        outputs={"results": str(result_path), "corrected_tiff": str(corrected_path),
                                 "prepared_tiff": str(prepared), "frame_mapping": str(output / "frame_mapping.csv"),
                                 "motion_shifts": str(output / "motion_shifts.npz")})
        stage("Complete")
        return manifest
    except BaseException as exc:
        manifest.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        write_manifest(manifest_path, manifest)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    # Limit native threads before importing CaImAn; a single job stays cancellable.
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[name] = "1"
    os.environ.setdefault("MPLBACKEND", "Agg")
    settings = PipelineSettings(**json.loads(args.config.read_text(encoding="utf-8")))
    run_pipeline(settings, progress=lambda message: print(f"MINISYNC_STAGE {message}", flush=True))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
