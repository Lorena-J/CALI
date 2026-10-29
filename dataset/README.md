# CALI example files

These four files were explicitly selected for publication by the maintainer.
They are unchanged copies from the local `datos_prueba_minisync/` folder.
Original files remain in that folder. SHA-256 checksums are in `SHA256SUMS.txt`.

| File | Contents and provenance |
| --- | --- |
| `mini2p_20261005_095130.csv` | 200 timing rows with `frame`, `timestamp_ms` and `elapsed_ms`; supplied from the local project folder. Acquisition provenance has not been independently verified. |
| `camera_20261005_095130.csv` | 730 timing rows with the same columns; supplied from the local project folder. Acquisition provenance has not been independently verified. |
| `02_conducta_SIMULADA.mp4` | Simulated behavior video produced for local interface testing, not a recording of an animal. |
| `scanimage.tif` | Byte-identical to the official CaImAn `demoMovie.tif`; the local filename does not establish that it is an original Mini2P/ScanImage acquisition. |

TIFF source: [CaImAn example movie](https://github.com/flatironinstitute/CaImAn/blob/main/example_movies/demoMovie.tif).
SHA-256: `6f1dca4ac3329cded72c6f3ac90a725be32265db16cc6f681b522a2dd825682b`.
No transformations were applied while copying these files into `dataset/`.

These files have not been validated as one synchronized acquisition. The TIFF
and simulated behavior have no established biological relationship, and the
CSV row counts differ from the demo movie length. Do not infer synchronization
or biological associations merely from their presence in this folder.

Licensing of this bundle has not been declared. The external CaImAn example
movie retains its upstream terms; project code/logo licensing is also pending.
