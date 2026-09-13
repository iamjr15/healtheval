#!/usr/bin/env bash
# The source catalog uses web publications rather than a mandatory PDF bundle.
set -euo pipefail
exec uv run python scripts/download_health_sources.py "$@"
