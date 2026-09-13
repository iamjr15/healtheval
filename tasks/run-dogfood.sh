#!/bin/zsh
# Optional local QA runner. The prompt performs local review; hosting is separate.
set -eu

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="${HEALTHEVAL_QA_LOG_DIR:-$PROJECT_DIR/tasks/dogfood-output/logs}"
PROMPT_FILE="$SCRIPT_DIR/dogfood-prompt.md"
CLAUDE_BIN="${HEALTHEVAL_CLAUDE_BIN:-claude}"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/run-$(date +%Y%m%d-%H%M%S).log"
ln -sfn "$LOG" "$LOG_DIR/latest.log"

cd "$PROJECT_DIR"
if ! command -v "$CLAUDE_BIN" >/dev/null 2>&1; then
  echo "Claude Code is required for this optional QA runner." >&2
  exit 1
fi

# Preserve the CLI exit status so scheduled callers can detect a failed review.
"$CLAUDE_BIN" -p "$(cat "$PROMPT_FILE")" > "$LOG" 2>&1
