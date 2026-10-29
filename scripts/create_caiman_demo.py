#!/usr/bin/env python3
"""Build a real CNMF result plus explicitly simulated CALI companion data.

Run with a working CaImAn environment. Input is the official demoMovie.tif.
The original acquisition rate is not established here: 20 Hz is a DEMO clock.
"""
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile

# Keep generated caches and intermediate files in temporary directories.
for key, dirname in (("MPLCONFIGDIR", "cali-demo-mpl"),
                     ("NUMBA_CACHE_DIR", "cali-demo-numba"),
                     ("CAIMAN_TEMP", "cali-demo-caiman-temp")):
    cache = Path(tempfile.gettempdir()) / dirname
    cache.mkdir(exist_ok=True)
    os.environ.setdefault(key, str(cache))
os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(key, "1")

import caiman
from caiman.source_extraction.cnmf.cnmf import CNMF
from caiman.source_extraction.cnmf.params import CNMFParams
import cv2
import numpy as np
import pandas as pd
import tifffile


def create_demo(source, output):
    output.mkdir(parents=True, exist_ok=False)
    np.random.seed(0)
    calcium_path = output / "01_calcium_demo.tif"
    shutil.copy2(source, calcium_path)
    movie = np.asarray(tifffile.imread(calcium_path), dtype=np.float32)
    if movie.ndim != 3:
        raise ValueError(f"Expected frames × height × width, got {movie.shape}")
    n_frames, height, width = movie.shape
    print(f"Official CaImAn demo: {n_frames} frames, {width} × {height} pixels", flush=True)
    fps_calcium = 20.0
    fps_camera = 30.0
    origin_ms = 10000.0
    mini_times = origin_ms + np.arange(n_frames) * 1000 / fps_calcium
    camera_start = origin_ms - 250
    camera_count = int(np.ceil((mini_times[-1] + 750 - camera_start) * fps_camera / 1000)) + 1
    camera_times = camera_start + np.arange(camera_count) * 1000 / fps_camera

    def ttl_table(times):
        return pd.DataFrame({"frame": np.arange(1, len(times) + 1),
                             "timestamp_ms": times, "elapsed_ms": times - times[0]})

    ttl_table(mini_times).to_csv(output / "02_mini2p_SIMULATED.csv", index=False, float_format="%.6f")
    camera_table = ttl_table(camera_times)
    camera_table.to_csv(output / "03_camera_SIMULATED.csv", index=False, float_format="%.6f")
    missing_ttls = [600, 601, 1600]  # zero-based rows; video frames still exist.
    camera_table.drop(index=missing_ttls).to_csv(
        output / "03b_camera_missing_TTLs_SIMULATED.csv", index=False, float_format="%.6f")

    print("Fitting CNMF on all official demo frames (no motion correction)...", flush=True)
    parameters = {
        "data": {"fnames": [str(calcium_path)], "fr": fps_calcium, "decay_time": .4},
        "preprocess": {"p": 1},
        "temporal": {"p": 1},
        "init": {"K": 20, "gSig": [3, 3], "nb": 2,
                 "method_init": "greedy_roi", "ssub": 1, "tsub": 2},
        "patch": {"rf": None, "only_init": False}, "merging": {"merge_thr": .8},
        "quality": {"min_SNR": 2.0, "rval_thr": .75, "use_cnn": False},
    }
    mmap_path = caiman.save_memmap([str(calcium_path)],
                                  base_name=str(Path(os.environ["CAIMAN_TEMP"]) / "cali_demo"),
                                  order="C")
    mapped, dims, count = caiman.load_memmap(mmap_path)
    movie = np.reshape(mapped.T, (count, *dims), order="F")
    model = CNMF(1, params=CNMFParams(params_dict=parameters), dview=None)
    model.fit(movie)
    print(f"CNMF extracted {model.estimates.C.shape[0]} components; evaluating quality...", flush=True)
    model.estimates.evaluate_components(movie, model.params, dview=None)
    model.estimates.detrend_df_f(quantileMin=8, frames_window=250)
    if model.estimates.S is None or model.estimates.S.shape != model.estimates.C.shape:
        raise RuntimeError("CNMF must include a full temporal update and deconvolution, not only initialization")
    model.estimates.Cn = np.nan_to_num(caiman.local_correlations(movie, swap_dim=False))
    # Intermediate memory maps are not needed by CALI and are not shipped.
    model.mmap_file = None
    model.params.set("data", {"fnames": [calcium_path.name]})
    model_path = output / "04_caiman_demo_CNMF.hdf5"
    model.save(str(model_path))
    accepted = np.asarray(model.estimates.idx_components, dtype=int).tolist()
    rejected = np.asarray(model.estimates.idx_components_bad, dtype=int).tolist()
    print(f"Saved native CNMF: {len(accepted)} accepted / {len(rejected)} rejected", flush=True)

    print(f"Creating {camera_count}-frame simulated behavior video and tracking...", flush=True)
    arena_width, arena_height = 480, 320
    time_seconds = (camera_times - origin_ms) / 1000
    x = 240 + 150 * np.sin(time_seconds * .25)
    y = 175 + 85 * np.sin(time_seconds * .39 + .7)
    speed = np.hypot(np.gradient(x, 1 / fps_camera), np.gradient(y, 1 / fps_camera))
    angles = np.degrees(np.arctan2(np.gradient(y), np.gradient(x)))
    video_path = output / "05_behavior_SIMULATED.mp4"
    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), fps_camera,
                             (arena_width, arena_height))
    if not writer.isOpened():
        raise RuntimeError("Could not open the demo MP4 encoder")
    try:
        for i, (px, py) in enumerate(zip(x, y)):
            frame = np.full((arena_height, arena_width, 3), (225, 232, 235), dtype=np.uint8)
            cv2.rectangle(frame, (20, 55), (460, 295), (125, 140, 145), 2)
            center = (int(round(px)), int(round(py)))
            angle = float(angles[i])
            cv2.ellipse(frame, center, (17, 10), angle, 0, 360, (60, 68, 65), -1)
            cv2.circle(frame, center, 3, (90, 195, 30), -1)
            cv2.putText(frame, "SIMULATED BEHAVIOR - NO BIOLOGICAL LINK", (12, 22),
                        cv2.FONT_HERSHEY_SIMPLEX, .47, (40, 65, 85), 1, cv2.LINE_AA)
            cv2.putText(frame, f"Frame {i + 1:04d}   t={time_seconds[i]:7.3f}s", (12, 43),
                        cv2.FONT_HERSHEY_SIMPLEX, .5, (40, 65, 85), 1, cv2.LINE_AA)
            writer.write(frame)
    finally:
        writer.release()
    tracking = pd.DataFrame({"frame_index": np.arange(camera_count), "x": x, "y": y,
                             "speed_px_s": speed, "likelihood": np.ones(camera_count)})
    tracking.to_csv(output / "06_tracking_SIMULATED.csv", index=False, float_format="%.6f")
    tracking.loc[900:905, ["x", "y", "speed_px_s"]] = np.nan
    tracking.loc[900:905, "likelihood"] = 0
    tracking.to_csv(output / "06b_tracking_missing_positions_SIMULATED.csv", index=False, float_format="%.6f")

    metadata = {
        "source_url": "https://github.com/flatironinstitute/CaImAn/blob/main/example_movies/demoMovie.tif",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "caiman_version": caiman.__version__,
        "calcium_movie": "Real official CaImAn demo; unmodified, no motion correction",
        "calcium_shape_frames_height_width": list(movie.shape),
        "CNMF": "Real CaImAn fit, quality evaluation, deconvolution and detrend_df_f",
        "assumed_demo_calcium_fps": fps_calcium,
        "simulation_notice": "TTL times, 20 Hz calcium clock, behavior video and tracking are SIMULATED and not original acquisition data. No calcium/behavior biological association exists.",
        "camera_fps": fps_camera, "camera_frames": camera_count,
        "clock_origin_ms": origin_ms, "camera_start_relative_to_calcium_ms": -250,
        "video_mapping": "Timing reconstruction", "MP4_offset": 0, "first_Mini2P_frame": 1,
        "calcium_components": int(model.estimates.C.shape[0]),
        "accepted_component_ids_zero_based": accepted,
        "rejected_component_ids_zero_based": rejected,
        "missing_camera_csv_rows_zero_based_in_optional_file": missing_ttls,
        "missing_tracking_frame_indices_in_optional_file": list(range(900, 906)),
    }
    # CNMFParams includes ndarray configuration values; keep the manifest to
    # the explicit reproducible settings instead of serializing runtime state.
    metadata["CNMF_parameters"] = {key: value for key, value in parameters.items() if key != "data"}
    metadata["CNMF_parameters"]["data"] = {"fr": fps_calcium, "decay_time": .4, "fnames": [calcium_path.name]}
    (output / "demo_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    instructions = f"""# Demo completa de CALI con CaImAn

El TIFF es el demo oficial de CaImAn ({n_frames} frames, {width} × {height} px).
El HDF5 contiene un análisis CNMF REAL realizado con CaImAn {caiman.__version__}:
{model.estimates.C.shape[0]} componentes, {len(accepted)} aceptados y {len(rejected)} rechazados.
Se conservan todos los componentes para probar los filtros de calidad.

IMPORTANTE: el reloj de calcio a 20 Hz, los TTL, el vídeo de comportamiento y
el tracking son SIMULADOS. No son registros conductuales del experimento y
no permiten interpretar relaciones biológicas entre calcio y comportamiento.
La frecuencia original del TIFF no se ha establecido. Se usa 20 Hz para esta demo.
No se ha aplicado corrección de movimiento al TIFF ni al ajuste CNMF.

## Abrir los archivos en CALI

En Files, cargar:

1. Camera CSV → 03_camera_SIMULATED.csv
2. Mini2P CSV → 02_mini2p_SIMULATED.csv
3. Behavior MP4 → 05_behavior_SIMULATED.mp4
4. ScanImage TIFF → 01_calcium_demo.tif
5. CaImAn HDF5 → 04_caiman_demo_CNMF.hdf5

Mantener Video mapping en Timing reconstruction, MP4 offset en 0 y
First Mini2P frame en 1. Se muestran los {n_frames} samples de cada traza.

## Qué probar

- Calcium: elegir una ROI y alternar C, C + YrA, ΔF/F y S.
- Filtrar Accepted, Rejected y All components; los IDs son de base cero.
  Si todos pasan los criterios, Rejected estará vacío; las etiquetas no se fuerzan.
- Show ROI: mostrar/ocultar el contorno sobre el TIFF original.
- Mover los cursores, usar Frame/Gap y comparar ambos vídeos.
- Export trace: guardar el CSV con señal, frame y tiempo.
- Align tracking: cargar 06_tracking_SIMULATED.csv, seleccionar x y alinear.
  Probar los destinos Camera/Mini2P y exportar tabla o vídeo alineado.
- Crop: dibujar un recorte en el vídeo de comportamiento y exportarlo.
- Trim: Auto recorta el final extra de la cámara; Cursor permite elegir
  otro punto. Export genera copias recortadas; Reset restaura el rango.
- Alternar día/noche con el icono de la esquina superior derecha.

## Casos opcionales con huecos

- 03b_camera_missing_TTLs_SIMULATED.csv omite tres pulsos, conservando todos
  los frames en el MP4. CALI debe reconstruir los tiempos faltantes.
- 06b_tracking_missing_positions_SIMULATED.csv omite seis posiciones
  consecutivas. La alineación debe mantener vacío un hueco mayor al límite
  permitido; cambiar ese límite permite probar la interpolación controlada.

Los parámetros y la procedencia están en demo_metadata.json.
Los checksums SHA-256 están en SHA256SUMS.txt.

Fuente: https://github.com/flatironinstitute/CaImAn/blob/main/example_movies/demoMovie.tif
Pipeline: https://github.com/flatironinstitute/CaImAn/blob/main/demos/general/demo_pipeline.py
"""
    (output / "LEEME.md").write_text(instructions)
    shutil.copy2(__file__, output / "create_caiman_demo.py")
    checksum_lines = []
    for path in sorted(output.iterdir()):
        if path.is_file():
            checksum_lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    (output / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n")
    print(f"Demo ready: {output}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True,
                        help="New directory; must not exist")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    create_demo(args.source.resolve(), args.output.resolve())
