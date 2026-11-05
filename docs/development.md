# Development

[Back to CALI](../README.md)

## Viewer environment

The supported local test target is Python 3.11 on macOS Apple Silicon. Users
install the `cali` command with `uv tool install` (see the README). For
development, run `uv sync` in the repository: it creates `.venv/` from
`uv.lock` with an editable install of the package, and `uv run cali` or
`uv run python -m unittest ...` use it. Keep CaImAn in its separate Conda
environment (`envs/environment-caiman.yml`). Do not update an existing working
environment merely to test a proposed dependency change.

Dependency pins live in four places that must agree: `pyproject.toml`
(`dependencies` for direct pins, `[tool.uv] constraint-dependencies` for
transitive ones), `uv.lock` (regenerate with `uv lock`), `requirements.txt`
(direct) and `requirements-lock.txt` (direct plus transitive; used by CI and
as `-c` constraints for `uv tool install`). When updating dependencies, resolve
in a clean environment, run `uv pip check`, execute the full suite, and inspect
both UI themes. Update all four and record the tested platform. These are version pins, not a hash-verified or
platform-complete lock for Conda, system libraries or the CaImAn environment.

## Repository layout

| Path | Contents |
| --- | --- |
| `cali/` | Application package: `viewer.py` (main window, TTL, tracking alignment), `caiman_results.py`, `calcium_pipeline.py` (CaImAn worker), `processing_dialog.py`, `movement_analysis.py`, `movement_dialog.py`. |
| `cali/assets/icons/` | Interface icons and logos loaded at runtime. |
| `tests/` | `unittest` suite with synthetic fixtures. |
| `scripts/` | Generators for the CaImAn demo and the processing test pack. |
| `docs/` | User and developer guides, validation records and screenshots. |
| `envs/` | Conda recipe for the optional CaImAn engine (`cali-caiman`). The viewer is installed with uv into `.venv/`. |
| `datasets/` | Local test data; contents are ignored by Git. |
| `pyproject.toml`, `uv.lock` | Package metadata, the `cali` command (`cali.viewer:main`) and the uv lock. |
| `requirements*.txt` | Pinned viewer dependencies (kept at the root for pip and CI). |

`cali/__init__.py` must stay free of imports. The viewer starts the CaImAn
worker by file path (`<engine python> cali/calcium_pipeline.py`), not with
`-m`: that way only the `cali/` folder joins the worker's `sys.path` and the
engine never imports the viewer's own NumPy or Qt. `calcium_pipeline.py`
therefore falls back to a plain `from caiman_results import ...`.

## Tests

From the repository root:

```bash
uv sync
uv pip check
QT_QPA_PLATFORM=offscreen uv run python -m unittest discover -s tests -v
```

Tests create temporary fixtures and include Qt processing orchestration,
failed-worker handling and cancellation of an actual subprocess. The standard
suite does not require a CaImAn installation and does not prove a complete CNMF
run or compatibility with real multichannel ScanImage recordings. See the
[processing validation record](processing-validation.md) for separate engine runs.

The application code is the `cali/` package. The `cali` command and
`python -m cali` (`cali/__main__.py`) both start `cali.viewer.main`. Tests import modules as
`cali.viewer`, `cali.caiman_results`, and so on, and mock targets use those
names (for example `cali.viewer.QMessageBox`). Run `uv run cali` from the
repository root for a normal interactive launch. Offscreen tests do not
replace visual inspection or a normal-event-loop startup/shutdown check.

## GitHub Actions

`.github/workflows/tests.yml` installs the pinned viewer stack on a macOS runner
with Python 3.11, checks dependencies and runs the same offscreen unittest suite.
It has read-only repository permissions and does not install the CaImAn engine,
publish artifacts or deploy the application. A workflow file is not evidence of
a successful GitHub run until it has been pushed and actually executed.

Action setup references: [checkout](https://github.com/actions/checkout) and
[setup-python](https://github.com/actions/setup-python).

## Repository contents

Keep source, small UI assets, documentation and synthetic test generators in Git.
Do not version Python bytecode, `.DS_Store`, local environments, experimental
recordings or generated processing outputs. `.gitignore` covers the current
local demo folder and the standard generated-directory names; keep new datasets
outside the checkout or add a specific local exclusion before using them.

Removing previously tracked caches from Git uses `git rm --cached`: this keeps
the files on disk. The current cleanup does not rewrite repository history.
The older validation report intentionally retains the environment names and
paths used at the time.

The repository is released under the MIT License (see [LICENSE](../LICENSE)),
© 2026 Lorena Jiménez and Anna Teruel-Sanchis.
