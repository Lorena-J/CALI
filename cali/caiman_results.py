"""Read CaImAn CNMF HDF5 results without importing the analysis pipeline.

CaImAn stores temporal arrays as components x frames and spatial footprints
as pixels x components, flattened in Fortran order. Only selected rows and
columns are read, keeping large result files out of memory.
"""
from pathlib import Path

import numpy as np


class CaImAnResults:
    TRACE_LABELS = {
        "C": "C · denoised",
        "C+YrA": "C + YrA · with residuals",
        "F_dff": "ΔF/F · CaImAn",
        "S": "S · deconvolved activity",
    }

    def __init__(self, path):
        try:
            import h5py
        except ImportError as exc:
            raise RuntimeError("CaImAn import requires h5py. Install requirements.txt first.") from exc
        self._h5py = h5py
        self.path = Path(path).resolve()
        self.dims = None
        self.spatial = False
        self.accepted = self.rejected = None
        with h5py.File(self.path, "r") as file:
            if "estimates" not in file or not isinstance(file["estimates"], h5py.Group):
                raise ValueError("Expected a CaImAn CNMF .hdf5/.h5 file with an estimates group.")
            estimates = file["estimates"]
            c = estimates.get("C")
            if not self._matrix(c) or not all(c.shape):
                raise ValueError("CaImAn estimates/C must contain a non-empty components × frames matrix.")
            self.n_components, self.n_frames = c.shape
            self.trace_types = ["C"]
            for key in ("YrA", "F_dff", "S"):
                value = estimates.get(key)
                if self._matrix(value):
                    if value.shape != c.shape:
                        raise ValueError(f"estimates/{key} shape does not match estimates/C.")
                    self.trace_types.append("C+YrA" if key == "YrA" else key)
            self.accepted = self._indices(estimates.get("idx_components"))
            self.rejected = self._indices(estimates.get("idx_components_bad"))
            if self.accepted is not None and self.rejected is not None:
                if np.intersect1d(self.accepted, self.rejected).size:
                    raise ValueError("Accepted and rejected component IDs overlap.")
            for key in ("dims", "estimates/dims", "params/data/dims"):
                value = file.get(key)
                if isinstance(value, h5py.Dataset) and value.dtype.kind in "iuf":
                    dims = np.asarray(value[()]).ravel()
                    if dims.size == 2 and np.all(np.isfinite(dims)) and np.all(dims > 0) and np.all(dims == np.floor(dims)):
                        self.dims = tuple(map(int, dims))
                        break
            a = estimates.get("A")
            if self.dims is not None and isinstance(a, h5py.Group):
                if not all(key in a for key in ("data", "indices", "indptr", "shape")):
                    raise ValueError("Incomplete CaImAn spatial CSC matrix.")
                shape = tuple(a["shape"][()])
                if shape != (int(np.prod(self.dims)), self.n_components):
                    raise ValueError("CaImAn footprint dimensions do not match dims and C.")
                ptr = np.asarray(a["indptr"][()])
                if (ptr.dtype.kind not in "iu" or len(ptr) != self.n_components + 1
                        or ptr[0] != 0 or np.any(np.diff(ptr.astype(np.int64)) < 0)
                        or ptr[-1] != a["data"].size or a["indices"].size != a["data"].size):
                    raise ValueError("Invalid CaImAn spatial CSC column pointers.")
                self.spatial = True
            elif self.dims is not None and self._matrix(a):
                if a.shape != (int(np.prod(self.dims)), self.n_components):
                    raise ValueError("CaImAn footprint dimensions do not match dims and C.")
                self.spatial = True

    def _matrix(self, value):
        return (isinstance(value, self._h5py.Dataset)
                and value.ndim == 2 and value.dtype.kind in "biuf")

    def _indices(self, value):
        if not isinstance(value, self._h5py.Dataset) or value.dtype.kind in "OSU":
            return None  # CaImAn serializes None as the string "NoneType".
        ids = np.asarray(value[()]).ravel()
        if (ids.dtype.kind not in "iuf" or not np.all(np.isfinite(ids))
                or np.any(ids != np.floor(ids)) or np.any(ids < 0)
                or np.any(ids >= self.n_components) or len(np.unique(ids)) != len(ids)):
            raise ValueError("Invalid CaImAn component quality indices.")
        return ids.astype(int)

    def component_ids(self, quality="all"):
        if quality == "accepted":
            return self.accepted if self.accepted is not None else np.array([], dtype=int)
        if quality == "rejected":
            return self.rejected if self.rejected is not None else np.array([], dtype=int)
        return np.arange(self.n_components)

    def quality(self, component):
        if self.accepted is not None and component in self.accepted:
            return "accepted"
        if self.rejected is not None and component in self.rejected:
            return "rejected"
        return "unreviewed"

    def trace(self, component, kind):
        if kind not in self.trace_types or not 0 <= component < self.n_components:
            raise ValueError("Unknown CaImAn component or trace type.")
        with self._h5py.File(self.path, "r") as file:
            estimates = file["estimates"]
            if kind == "C+YrA":
                return estimates["C"][component, :].astype(float) + estimates["YrA"][component, :]
            return estimates[kind][component, :].astype(float)

    def footprint(self, component):
        if not self.spatial:
            return None
        if not 0 <= component < self.n_components:
            raise ValueError("Unknown CaImAn component.")
        with self._h5py.File(self.path, "r") as file:
            a = file["estimates/A"]
            if isinstance(a, self._h5py.Group):
                start, stop = map(int, a["indptr"][component:component + 2])
                indices = a["indices"][start:stop]
                if indices.dtype.kind not in "iu" or np.any(indices < 0) or np.any(indices >= np.prod(self.dims)):
                    raise ValueError("Invalid CaImAn footprint pixel indices.")
                flat = np.zeros(int(np.prod(self.dims)), dtype=np.float32)
                np.add.at(flat, indices, a["data"][start:stop])
            else:
                flat = a[:, component].astype(np.float32)
        if not np.all(np.isfinite(flat)):
            raise ValueError("CaImAn footprint contains non-finite pixel weights.")
        return flat.reshape(self.dims, order="F")

    def reference_image(self):
        with self._h5py.File(self.path, "r") as file:
            for key in ("estimates/Cn", "Cn"):
                value = file.get(key)
                if self._matrix(value) and value.shape == self.dims:
                    return value[()].astype(np.float32)
        return None

    def mapped_trace(self, trace, mini_frames, first_frame=1):
        """Map sample 0 to a stated 1-based Mini2P frame; never interpolate."""
        frames = np.asarray(mini_frames, dtype=float)
        if (not np.isfinite(first_frame) or first_frame < 1 or int(first_frame) != first_frame
                or np.asarray(trace).shape != (self.n_frames,)):
            raise ValueError("Invalid CaImAn trace length or first Mini2P frame.")
        if (frames.ndim != 1 or not np.all(np.isfinite(frames))
                or np.any(frames < 1) or np.any(frames != np.floor(frames))
                or np.any(np.diff(frames) <= 0) or first_frame < 1):
            raise ValueError("Mini2P frame IDs must be positive, ordered, unique integers.")
        indices = frames.astype(np.int64) - int(first_frame)
        valid = (indices >= 0) & (indices < self.n_frames)
        values = np.full(len(frames), np.nan)
        values[valid] = trace[indices[valid]]
        return values, valid
