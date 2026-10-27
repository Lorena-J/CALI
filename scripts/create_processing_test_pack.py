#!/usr/bin/env python3
"""Prepare raw inputs for testing MINISYNC without tracking or precomputed CNMF.

The calcium TIFF is copied unchanged. Behavior and acquisition clocks are
explicitly simulated and have no biological association with the calcium.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import sys

import cv2
import numpy as np
import pandas as pd
import tifffile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from calcium_pipeline import PipelineSettings


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_pack(source, output):
    source, output = source.resolve(), output.resolve()
    with tifffile.TiffFile(source) as tif:
        count = len(tif.pages)
        height, width = tif.pages[0].shape
    output.mkdir(parents=True, exist_ok=False)
    calcium = output / "01_calcio_demo_CaImAn.tif"
    video = output / "02_conducta_SIMULADA.mp4"
    mini_csv = output / "03_ttl_mini2p_SIMULADO.csv"
    camera_csv = output / "04_ttl_camara_SIMULADO.csv"
    shutil.copy2(source, calcium)
    # Demonstration assumptions only, not the acquisition rate of the TIFF.
    calcium_fps, camera_fps, origin_ms = 20.0, 30.0, 10000.0
    mini_times = origin_ms + np.arange(count) * 1000 / calcium_fps
    camera_start = origin_ms - 250
    camera_count = int(np.ceil((mini_times[-1] + 750 - camera_start) * camera_fps / 1000)) + 1
    camera_times = camera_start + np.arange(camera_count) * 1000 / camera_fps
    for times, path in ((mini_times, mini_csv), (camera_times, camera_csv)):
        pd.DataFrame({"frame": np.arange(1, len(times) + 1), "timestamp_ms": times,
                      "elapsed_ms": times - times[0]}).to_csv(path, index=False, float_format="%.6f")

    arena_w, arena_h = 640, 400
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), camera_fps, (arena_w, arena_h))
    if not writer.isOpened():
        raise RuntimeError("Could not create simulated behavior MP4.")
    try:
        for index, time_ms in enumerate(camera_times):
            t = (time_ms - origin_ms) / 1000
            x, y = 320 + 220 * np.sin(t * .25), 230 + 110 * np.sin(t * .39 + .7)
            angle = np.degrees(np.arctan2(110 * .39 * np.cos(t * .39 + .7),
                                         220 * .25 * np.cos(t * .25)))
            frame = np.full((arena_h, arena_w, 3), (225, 232, 235), dtype=np.uint8)
            cv2.rectangle(frame, (35, 90), (605, 365), (125, 140, 145), 2)
            cv2.ellipse(frame, (round(x), round(y)), (23, 14), angle, 0, 360, (60, 68, 65), -1)
            cv2.circle(frame, (round(x), round(y)), 4, (90, 195, 30), -1)
            for text, at, scale in (
                ("SIMULATED BEHAVIOR - NOT A REAL ANIMAL RECORDING", (14, 24), .55),
                ("NO BIOLOGICAL LINK TO CALCIUM", (14, 48), .55),
                (f"Camera frame {index + 1:04d}  |  t = {t:+8.3f} s", (14, 73), .55),
            ):
                cv2.putText(frame, text, at, cv2.FONT_HERSHEY_SIMPLEX, scale, (40, 65, 85), 1, cv2.LINE_AA)
            writer.write(frame)
    finally:
        writer.release()
    cap = cv2.VideoCapture(str(video))
    try:
        if not cap.isOpened() or int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) != camera_count:
            raise RuntimeError("Output video does not match camera TTL count.")
        for index in (0, camera_count // 2, camera_count - 1):
            cap.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = cap.read()
            if not ok or frame.shape[:2] != (arena_h, arena_w):
                raise RuntimeError(f"Output video frame {index} is not readable.")
    finally:
        cap.release()

    (output / "resultados").mkdir()
    settings = PipelineSettings(sources=[str(calcium)],
        output=str(output / "resultados" / "primer_procesamiento"), frame_rate=calcium_fps,
        single_plane_confirmed=True, neuron_half_size=3, cnmf_patch_half_size=15, rval_thr=.75)
    settings.validate()
    (output / "parametros_procesamiento.json").write_text(json.dumps(asdict(settings), indent=2) + "\n")
    metadata = {
        "source_url": "https://github.com/flatironinstitute/CaImAn/blob/main/example_movies/demoMovie.tif",
        "original_filename": "demoMovie.tif", "source_sha256": checksum(source),
        "copied_tiff_sha256": checksum(calcium), "calcium_frames": count,
        "image_height": height, "image_width": width, "saved_channels": 1, "imaging_planes": 1,
        "calcium_notice": "Real CaImAn example movie, copied unchanged; not an authenticated Mini2P or ScanImage acquisition.",
        "simulation_notice": "Behavior video and BOTH TTL CSVs are generated, not original acquisition data. No biological association between calcium and behavior.",
        "assumed_calcium_fps": calcium_fps, "simulated_camera_fps": camera_fps,
        "camera_frames": camera_count, "camera_start_relative_ms": -250,
        "original_acquisition_rate_verified": False,
        "tracking_included": False, "precomputed_cnmf_included": False,
        "generator": "scripts/create_processing_test_pack.py",
    }
    (output / "procedencia.json").write_text(json.dumps(metadata, indent=2) + "\n")
    guide = f"""# Prueba de corrección de movimiento y CNMF en MINISYNC

## Qué contiene esta carpeta

- `01_calcio_demo_CaImAn.tif`: película real de ejemplo de CaImAn, copiada
  sin cambios. {count} frames, {width} × {height} píxeles, un canal y un plano.
  No es una grabación Mini2P propia ni valida cabeceras ScanImage.
- `02_conducta_SIMULADA.mp4`: dibujo animado de una trayectoria, NO un vídeo
  real de un animal. {camera_count} frames a 30 Hz.
- `03_ttl_mini2p_SIMULADO.csv` y `04_ttl_camara_SIMULADO.csv`: tiempos
  generados para probar la interfaz sincronizada. No proceden de un Arduino.
- `parametros_procesamiento.json`: configuración opcional para el worker CLI.
- `resultados/`: carpeta donde puedes guardar las nuevas ejecuciones.

No hay tracking ni análisis CNMF precalculado: la idea es ejecutar el cálculo.
El vídeo y los tiempos son simulados, sin relación biológica con el calcio.
Los 20 Hz del calcio son una suposición para la demo; la frecuencia original
de adquisición no está verificada. Fuente y hashes: `procedencia.json` y
`SHA256SUMS.txt`. Datos descargados para pruebas locales, no para redistribución
sin comprobar las condiciones de la fuente.

## 1. Abrir la aplicación

Desde el directorio del proyecto:

```bash
conda activate mini2p-sync
python sync_viewer.py
```

## 2. Probar corrección de movimiento y CNMF (solo necesita el TIFF)

1. Carga `01_calcio_demo_CaImAn.tif` en **ScanImage TIFF** (Files).
2. Pulsa **Calcium analysis** junto a los controles del Timeline: reutiliza el TIFF.
   También puedes añadirlo desde **Add TIFF**; la papelera solo quita la selección.
3. Mantén **Channels = 1 channel** y **Planes = 1 plane**.
4. Pon **Frame rate (Hz) = 20**. Solo es el reloj de demo.
5. Abre **More options** y usa **First Mini2P frame = 1**, **Motion correction = Rigid**,
   **Maximum shift = 6**, **Calcium decay time = 0.4**,
   **Neuron half-size = 3**, **Initial components / patch = 4**,
   **CNMF patch half-size = 15**, **Minimum SNR = 2**,
   **Spatial correlation threshold = 0.75**.
6. Pulsa **Run analysis**. El motor CaImAn se localiza automáticamente.
   Se crea `minisync_results/calcium_*` junto al TIFF; no hay que crearla antes.
7. Al terminar, TIFF corregido y resultados se cargan automáticamente en el visor.
   Durante el cálculo, el botón permite **Cancel analysis**.

Obtendrás HDF5 con componentes/trazas, TIFF corregido, desplazamientos,
correspondencia de frames y parámetros. El número de componentes es un
resultado del ajuste, no una garantía de cuántas células reales hay.

## 3. Probar además la visualización sincronizada de conducta

En Files, carga:

1. **Camera CSV** → `04_ttl_camara_SIMULADO.csv`.
2. **Mini2P CSV** → `03_ttl_mini2p_SIMULADO.csv`.
3. **Behavior MP4** → `02_conducta_SIMULADA.mp4`.

Mantén **Video mapping = Timing reconstruction**, **MP4 offset = 0** y
**First Mini2P frame = 1**. Estos archivos se pueden cargar antes o después
del procesamiento. En **Calcium**, selecciona componente y señal; mueve el
cursor para recorrer imágenes, conducta y trazas. No vuelvas a cargar el TIFF
original después de abrir los resultados si quieres inspeccionar las ROI
sobre la película corregida usada para CNMF.

El tracking NO hace falta para estos pasos. Solo se necesita para alinear
coordenadas o analizar movimiento/reposo, funciones que no cubre este paquete.

## Repetir por terminal (opcional)

Con el Python de CaImAn, ejecutar desde el directorio del proyecto:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/caiman/bin/python calcium_pipeline.py --config "{output / 'parametros_procesamiento.json'}"
```

El JSON usa rutas absolutas de esta carpeta. Si la mueves, actualiza esas rutas.
El destino `resultados/primer_procesamiento` no debe existir; para repetir,
cambia el destino por otro nuevo. En la interfaz cada ejecución recibe un nombre nuevo.
"""
    (output / "LEEME.md").write_text(guide, encoding="utf-8")
    (output / "SHA256SUMS.txt").write_text("\n".join(
        f"{checksum(path)}  {path.name}" for path in sorted(output.iterdir()) if path.is_file()) + "\n")
    print(json.dumps({"folder": str(output), "calcium_frames": count,
                      "camera_frames": camera_count, "source_unchanged": metadata["source_sha256"] == metadata["copied_tiff_sha256"]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    create_pack(args.source, args.output)
