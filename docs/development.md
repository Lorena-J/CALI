# Development

[Back to CALI](../README.md)

## Viewer environment

The supported local test target is Python 3.11 on macOS Apple Silicon. Create a
new `cali` Conda environment with `environment.yml`, or a fresh virtual environment
and install `requirements-lock.txt`, as described in the README. Keep CaImAn in
its separate environment. Do not update an existing working environment merely
to test a proposed dependency change.

`requirements.txt` pins direct viewer dependencies; `requirements-lock.txt`
includes those pins plus the runtime dependencies resolved for this stack.
When updating dependencies, resolve in a clean environment, run `python -m pip
check`, execute the full suite, and inspect both UI themes. Update both files
and record the tested platform. These are version pins, not a hash-verified or
platform-complete lock for Conda, system libraries or the CaImAn environment.

## Tests

From the repository root, with the viewer environment active:

```bash
python -m pip check
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
```

Tests create temporary fixtures and include Qt processing orchestration,
failed-worker handling and cancellation of an actual subprocess. The standard
suite does not require a CaImAn installation and does not prove a complete CNMF
run or compatibility with real multichannel ScanImage recordings. See the
[processing validation record](processing-validation.md) for separate engine runs.

The application entry point and test imports are `cali.py` / `cali`.
Run `python cali.py` for a normal interactive launch. Offscreen tests do not
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

The code and logo license decision is pending; do not add a license without the
maintainer's explicit selection.
