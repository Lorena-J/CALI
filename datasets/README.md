# Datasets

Local folder for test and demonstration data. Everything here except this
README is ignored by Git: do not commit recordings, videos, TTL tables or
processing results.

Suggested contents:

- `datos_prueba_cali/`: processing test pack created with
  `python scripts/create_processing_test_pack.py --source /path/to/demoMovie.tif --output datasets/datos_prueba_cali`
- `caiman_demo/`: demonstration created with `scripts/create_caiman_demo.py`
  (requires a separate CaImAn environment).

Public sources, licences and checksums for each dataset should be recorded in
the dataset's own folder (the scripts above write a provenance file).
