#!/usr/bin/env bash
# Run the current project's checks. Optional flags require live credentials/evidence.
set -euo pipefail
exec uv run python scripts/preflight_check.py "$@"
