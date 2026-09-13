#!/usr/bin/env bash
# Minimal live-provider smoke test. Loads .env from the repo root if present.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if command -v python3 >/dev/null 2>&1; then
  python3 scripts/check_env.py .env || exit 1
fi

if [[ -t 1 ]]; then
  C_GREEN=$'\033[32m'
  C_RED=$'\033[31m'
  C_RESET=$'\033[0m'
else
  C_GREEN=""
  C_RED=""
  C_RESET=""
fi

PASS=0
FAIL=0
declare -a FAIL_REASONS

ok() {  echo "${C_GREEN}[ok]${C_RESET}   $*"; PASS=$((PASS+1)); }
err() { echo "${C_RED}[fail]${C_RESET} $*" >&2; FAIL=$((FAIL+1)); FAIL_REASONS+=("$*"); }

require_var() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    err "${name} not set in environment (expected from .env)"
    return 1
  fi
}

check_sarvam() {
  require_var SARVAM_API_KEY || return 1
  local model resp
  for model in sarvam-105b-conversations sarvam-105b; do
    resp=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 30 \
      -X POST https://api.sarvam.ai/v1/chat/completions \
      -H "api-subscription-key: ${SARVAM_API_KEY}" \
      -H "Content-Type: application/json" \
      -d "{\"model\":\"${model}\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":1}")
    if [[ "$resp" =~ ^2 ]]; then
      ok "Sarvam ${model} (SARVAM_API_KEY) → HTTP ${resp}"
    else
      err "Sarvam ${model} → HTTP ${resp}"
    fi
  done
}

check_anthropic() {
  require_var ANTHROPIC_API_KEY || return 1
  local resp
  resp=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 30 \
    -X POST https://api.anthropic.com/v1/messages \
    -H "x-api-key: ${ANTHROPIC_API_KEY}" \
    -H "anthropic-version: 2023-06-01" \
    -H "Content-Type: application/json" \
    -d '{"model":"claude-sonnet-4-6","max_tokens":1,"messages":[{"role":"user","content":"hi"}]}')
  if [[ "$resp" =~ ^2 ]]; then
    ok "Anthropic (ANTHROPIC_API_KEY) → HTTP ${resp}"
  else
    err "Anthropic → HTTP ${resp}"
  fi
}

check_google() {
  require_var GOOGLE_API_KEY || return 1
  local resp
  resp=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 30 \
    -X POST "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent?key=${GOOGLE_API_KEY}" \
    -H "Content-Type: application/json" \
    -d '{"contents":[{"role":"user","parts":[{"text":"hi"}]}],"generationConfig":{"maxOutputTokens":1}}')
  if [[ "$resp" =~ ^2 ]]; then
    ok "Google (GOOGLE_API_KEY) → HTTP ${resp}"
  else
    err "Google → HTTP ${resp}"
  fi
}

echo "=== HealthEval Eval Harness — API-key smoke test ==="
check_sarvam
check_anthropic
check_google
echo "==="
echo "Pass: ${PASS}   Fail: ${FAIL}"

if (( FAIL > 0 )); then
  echo ""
  echo "Failed checks:"
  for r in "${FAIL_REASONS[@]}"; do
    echo "  - ${r}"
  done
  exit 1
fi
exit 0
