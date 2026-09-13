# Development

[Documentation](../README.md) · [Contributing](../../CONTRIBUTING.md)

## Reproducible setup

Use Python 3.11 or 3.12, uv, Git and Node 22.22 or newer. `.python-version`
selects Python 3.12; `.node-version` selects Node 24 for optional JavaScript tools.
The uv version used in CI and the container is pinned explicitly.

```bash
make setup
make check
make run
```

`make setup` runs `uv sync --locked --extra dev` and `npm ci`. `--locked` rejects
an outdated Python lockfile instead of silently changing dependencies. No `.env`
is needed for tests or saved-evidence browsing. After setup, commands can also
be run directly:

```bash
uv run --locked --extra dev pytest -q
uv run --locked --extra dev ruff check .
npm run test:worker
npm run build:worker
uv run --locked python scripts/check_repository.py
```

This is an application run from a repository checkout. It does not publish an
empty wheel or require a separate Streamlit requirements file. Run commands from
the repository root so runtime code and versioned data resolve consistently.

## What the quality gate checks

| Check | Coverage |
|---|---|
| Python tests | All tests under `tests/`, including workbench tests and the isolated four-model pipeline. Provider boundaries are mocked. Missing core modules, schemas or fixtures fail the suite; only the optional CLI-presence probe may skip in a Python-only environment. |
| Worker tests | Request validation, model dispatch, response parsing and sanitized upstream failures, using Node's built-in test runner. |
| Correctness lint | Ruff rules `E9`, `F63`, `F7`, `F82`: syntax, undefined names and invalid control flow. This is a scoped correctness baseline, not a full formatting or typing audit. |
| Repository checks | Relative documentation file links, common credential patterns, generated asset consistency and current published evidence. The credential check prints filenames, never matching values; it is not a comprehensive secret scanner. |
| Worker build | Wrangler compiles the Pages Functions into ignored `var/worker-build/`. No deployment or provider calls. |
| Container checks | Build the locked runtime; verify non-root execution, configured port, health endpoint and current evidence with a read-only filesystem. |

GitHub Actions runs Python on 3.11 and 3.12, JavaScript on Node 24, and the
container on Ubuntu. Actions use commit pins and read-only repository permission;
PR jobs receive no provider keys. Workflow logs are the current check status.
Historical API and browser measurements live in the validation reports.

## Where to make changes

- Candidate API behavior: `eval/panel_clients.py` and, for the response-only demo,
  `functions/api/chat.js`. Check both when updating shared provider behavior.
- Main scoring policy: `eval/final_method.py`, the judge helpers and versioned
  data under `data/`. Keep patient urgency separate from answer-review routing.
- Workbench behavior: `streamlit_app/`; regression tests belong in
  `tests/workbench/`.
- Benchmark generation and batch execution: `scripts/`; pipeline tests belong in
  `tests/integration/` and parsing/schema checks in `tests/smoke/`.
- Published usage and operating instructions: `README.md` and `docs/`.

## Change the benchmark deliberately

1. Review primary sources and edit `data/health_case_blueprints.json`.
2. If revising generated policy, personas or anchors, update
   `scripts/build_health_assets.py` as well. Direct edits to generated YAML can
   be overwritten.
3. Run `uv run --locked python scripts/build_health_assets.py`, inspect the diff
   and run the offline tests. The current contracts assume 30 reference cases;
   expansion requires updating those contracts.
4. Obtain independent clinical and language review. Keep draft review status
   until an actual review is recorded.
5. Run new live evidence in `results/runs/<run-name>/`. Changed benchmark inputs
   invalidate the old fingerprint; do not relabel old measurements.
6. To publish a replacement, review all outputs for provenance and private data,
   archive the prior run, replace the canonical artifacts coherently and rebuild
   the aggregate. `make check` intentionally rejects stale published evidence.

The generator check rebuilds into a temporary directory and compares bytes; it
never overwrites benchmark inputs while checking them.

## Dependency changes

Update Python constraints in `pyproject.toml`, run `uv lock`, then sync and test.
For Node, update `package.json` with the intended package version, regenerate the
lockfile and verify with `npm ci`. Commit the manifest and lockfile together.
Dependabot opens weekly Python, npm, Docker and GitHub Actions update proposals;
review changes and CI results before merging. It does not automatically deploy.

For browser changes, follow the [QA guide](browser-qa.md), check affected screens
and refresh [README captures](../screenshots/README.md) when their visible state
changes. For a release, record the Git commit, dependency locks, benchmark
fingerprint, actual jury and validation scope. Avoid recording credentials or
private user inputs in issues, fixtures, logs or screenshots.
