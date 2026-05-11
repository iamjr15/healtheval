#!/usr/bin/env bash
# Submission preflight. Exits non-zero on any failed required check.
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"
WITH_KEYS=0
WITH_FINDINGS=0
for arg in "$@"; do
  case "$arg" in
    --with-keys)     WITH_KEYS=1 ;;
    --with-findings) WITH_FINDINGS=1 ;;
    -h|--help)
      printf 'Usage: bash scripts/preflight_check.sh [--with-keys] [--with-findings]\n'
      exit 0 ;;
    *) echo "preflight: unknown flag: $arg" >&2; exit 2 ;;
  esac
done
declare -a ROWS=()        # "STATUS\t#NN\tname\tdetail"
PASS_N=0; FAIL_N=0; SKIP_N=0

record() {  # status name detail
  local status=$1 name=$2 detail=${3:-}
  ROWS+=("$status"$'\t'"$name"$'\t'"$detail")
  case "$status" in
    PASS) PASS_N=$((PASS_N+1)) ;;
    FAIL) FAIL_N=$((FAIL_N+1)) ;;
    SKIP) SKIP_N=$((SKIP_N+1)) ;;
  esac
}

# Keep running after failures so reviewers get the full table.
run_check() {  # name fn
  local name=$1 fn=$2
  set +e
  $fn
  set -e
}
check_01_repo_state() {
  if ! git rev-parse --git-dir >/dev/null 2>&1; then
    record FAIL "01 repo state" "not a git repository"
    return
  fi
  local branch
  if branch=$(git symbolic-ref --short -q HEAD 2>/dev/null); then
    :
  elif git rev-parse --verify -q HEAD >/dev/null 2>&1; then
    branch="(detached)"
  else
    branch="(no-commits)"
  fi
  local dirty
  dirty=$(git status --porcelain 2>/dev/null | wc -l | awk '{print $1+0}')
  if [[ "$dirty" -ne 0 ]]; then
    record FAIL "01 repo state" \
      "branch=${branch}, ${dirty} uncommitted change(s) — commit before submission"
  else
    record PASS "01 repo state" "branch=${branch}, working tree clean"
  fi
}
check_02_docker_compose() {
  if [[ ! -f docker-compose.yml ]]; then
    record FAIL "02 docker compose" "docker-compose.yml missing"
    return
  fi
  # Avoid requiring Docker for the basic structure check.
  set +e
  uv run python - <<'PY' >/tmp/preflight_compose.log 2>&1
import sys, yaml
doc = yaml.safe_load(open("docker-compose.yml"))
assert isinstance(doc, dict), "compose top-level must be a mapping"
svcs = doc.get("services") or {}
required = {
    "env-check",
    "smoke",
    "workbench",
    "preflight",
    "promptfoo-saved",
    "promptfoo-live",
    "panel-eval",
}
missing = required - set(svcs)
assert not missing, f"missing services: {sorted(missing)}"
print("ok")
PY
  local rc=$?
  set -e
  if [[ "$rc" -ne 0 ]]; then
    record FAIL "02 docker compose" \
      "structural lint failed: $(head -1 /tmp/preflight_compose.log)"
    return
  fi
  local detail="docker-compose.yml parses; reviewer services present"
  if command -v docker >/dev/null 2>&1 && [[ -f .env ]]; then
    if docker compose config >/dev/null 2>&1; then
      detail+=" (docker compose config OK)"
    else
      detail+=" (warning: docker compose config rejected the file — investigate before submission)"
    fi
  fi
  record PASS "02 docker compose" "$detail"
}
check_03_dep_pinning() {
  if [[ ! -f uv.lock ]]; then
    record FAIL "03 dep pinning" "uv.lock missing — run 'uv lock'"
    return
  fi
  local bad
  bad=$(awk '/^version = "/ && /[<>~^]/' uv.lock | wc -l | tr -d ' ')
  if [[ "$bad" -ne 0 ]]; then
    record FAIL "03 dep pinning" "$bad uv.lock entries contain a range operator instead of an exact version"
  else
    local n
    n=$(grep -c '^version = "' uv.lock || true)
    record PASS "03 dep pinning" "$n packages pinned to exact versions"
  fi
}
check_04_env_example() {
  if [[ ! -f .env.example ]]; then
    record FAIL "04 .env.example" "missing"; return
  fi
  local required=(
    SARVAM_API_KEY ANTHROPIC_API_KEY GOOGLE_API_KEY
  )
  local missing=()
  for k in "${required[@]}"; do
    grep -qE "^${k}=" .env.example || missing+=("$k")
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    record FAIL "04 .env.example" "missing keys: ${missing[*]}"
  else
    record PASS "04 .env.example" "${#required[@]}/${#required[@]} live-provider keys present"
  fi
}
check_05_test_data() {
  local files=(
    data/prompts.yaml data/personas.yaml data/constitution.yaml
    data/model_panel.yaml data/system_prompt_mnh.yaml data/reference_set.yaml
    data/equity_subset_hindi.yaml data/safety_subset_hindi.yaml
  )
  local missing=() invalid=()
  for f in "${files[@]}"; do
    if [[ ! -f "$f" ]]; then missing+=("$f"); continue; fi
    if ! uv run python -c "import yaml,sys; yaml.safe_load(open('$f'))" >/dev/null 2>&1; then
      invalid+=("$f")
    fi
  done
  if [[ ${#missing[@]} -gt 0 || ${#invalid[@]} -gt 0 ]]; then
    record FAIL "05 test data" "missing: ${missing[*]:-none} | invalid: ${invalid[*]:-none}"
  else
    record PASS "05 test data" "${#files[@]} YAML files present and parseable"
  fi
}
check_06_smoke_gate() {
  local t0 t1 dur rc
  t0=$(date +%s)
  set +e
  uv run pytest tests/smoke/ -q >/tmp/preflight_smoke.log 2>&1
  rc=$?
  set -e
  t1=$(date +%s)
  dur=$((t1 - t0))
  if [[ "$rc" -ne 0 ]]; then
    record FAIL "06 smoke gate" "pytest tests/smoke/ exited $rc in ${dur}s — see /tmp/preflight_smoke.log"
    return
  fi
  if [[ "$dur" -ge 60 ]]; then
    record FAIL "06 smoke gate" "passed but took ${dur}s ≥ 60s budget"
  else
    record PASS "06 smoke gate" "passed in ${dur}s (<60s budget)"
  fi
}
check_07_integration() {
  set +e
  uv run pytest tests/integration/ -q >/tmp/preflight_integration.log 2>&1
  local rc=$?
  set -e
  if [[ "$rc" -ne 0 ]]; then
    record FAIL "07 integration" "pytest tests/integration/ exited $rc — see /tmp/preflight_integration.log"
  else
    record PASS "07 integration" "FindingsSchema round-trip + system_prompt↔TriageOutput consistency"
  fi
}
check_08_api_keys() {
  if [[ "$WITH_KEYS" -ne 1 ]]; then
    record SKIP "08 api keys" "skipped — pass --with-keys to exercise live providers"
    return
  fi
  if [[ ! -x scripts/validate_keys.sh ]]; then
    record FAIL "08 api keys" "scripts/validate_keys.sh not found or not executable (eval-integ deliverable)"
    return
  fi
  set +e
  uv run python scripts/check_env.py .env >/tmp/preflight_env.log 2>&1
  local env_rc=$?
  set -e
  if [[ "$env_rc" -ne 0 ]]; then
    record FAIL "08 api keys" "local .env failed validation — see /tmp/preflight_env.log"
    return
  fi
  set +e
  bash scripts/validate_keys.sh >/tmp/preflight_keys.log 2>&1
  local rc=$?
  set -e
  if [[ "$rc" -ne 0 ]]; then
    record FAIL "08 api keys" "validate_keys.sh exited $rc — see /tmp/preflight_keys.log"
  else
    record PASS "08 api keys" "configured live providers responded"
  fi
}
check_09_panel_artifact() {
  local path=results/methodology_panel_refset_eval.json
  if [[ ! -f "$path" ]]; then
    record FAIL "09 panel artefact" "missing $path — run scripts/run_panel_refset_eval.py for the full reference-set panel"
    return
  fi
  set +e
  local msg
  msg=$(uv run python - <<'PY' 2>/tmp/preflight_panel_artifact.log
import json
from pathlib import Path

path = Path("results/methodology_panel_refset_eval.json")
data = json.loads(path.read_text())
models = data.get("panel_models") or []
complete = data.get("complete_panel_models") or []
rows = data.get("rows") or []
expected_models = len(models)
expected_rows = 30 * expected_models
assert expected_models >= 3, f"expected >=3 panel models, got {expected_models}"
assert data.get("n_models_done") == expected_models, (
    f"only {data.get('n_models_done')}/{expected_models} models complete"
)
assert set(complete) == set(models), f"incomplete models: {sorted(set(models) - set(complete))}"
assert data.get("n_prompts_done") == expected_rows, (
    f"expected {expected_rows} prompt-model rows, got {data.get('n_prompts_done')}"
)
assert data.get("n_prompts_total") == expected_rows, (
    f"n_prompts_total should be {expected_rows}, got {data.get('n_prompts_total')}"
)
assert len(rows) == expected_rows, f"rows length {len(rows)} != {expected_rows}"
for model_id, artefact in (data.get("models") or {}).items():
    assert artefact.get("n_prompts_done") == 30, f"{model_id}: expected 30 prompts"
    assert len(artefact.get("rows") or []) == 30, f"{model_id}: rows != 30"
print(f"{expected_models} models × 30 prompts complete ({len(rows)} rows)")
PY
  )
  local rc=$?
  set -e
  if [[ "$rc" -ne 0 ]]; then
    record FAIL "09 panel artefact" "panel artefact incomplete or invalid — see /tmp/preflight_panel_artifact.log"
  else
    record PASS "09 panel artefact" "$msg"
  fi
}
check_10_findings_schema() {
  if [[ "$WITH_FINDINGS" -ne 1 ]]; then
    record SKIP "10 findings.json" "skipped — pass --with-findings after results/findings.json is written"
    return
  fi
  if [[ ! -f results/findings.json ]]; then
    record FAIL "10 findings.json" "results/findings.json missing"
    return
  fi
  set +e
  uv run python - <<'PY' >/tmp/preflight_findings.log 2>&1
import json
from data.schemas import FindingsSchema
FindingsSchema.model_validate(json.load(open("results/findings.json")))
print("ok")
PY
  local rc=$?
  set -e
  if [[ "$rc" -ne 0 ]]; then
    record FAIL "10 findings.json" "FindingsSchema validation failed — see /tmp/preflight_findings.log"
  else
    record PASS "10 findings.json" "validates against data.schemas.FindingsSchema"
  fi
}
check_11_readme() {
  if [[ ! -f README.md ]]; then
    record FAIL "11 README"; return
  fi
  if grep -q 'docker compose up' README.md; then
    if grep -qE 'docker-compose up' README.md; then
      record FAIL "11 README" "contains both 'docker compose up' AND 'docker-compose up' (legacy hyphen variant) — drift"
    else
      record PASS "11 README" "one-command setup uses canonical 'docker compose up'"
    fi
  else
    record FAIL "11 README" "missing literal 'docker compose up' line"
  fi
}
check_12_demo_ui() {
  local issues=()

  if [[ ! -f wrangler.toml ]]; then
    issues+=("wrangler.toml missing")
  else
    if ! uv run python -c "import tomllib,sys; tomllib.load(open('wrangler.toml','rb'))" >/dev/null 2>&1; then
      issues+=("wrangler.toml invalid TOML")
    fi
  fi

  if [[ ! -f functions/api/chat.js ]]; then
    issues+=("functions/api/chat.js missing")
  elif command -v node >/dev/null 2>&1; then
    if ! node --check functions/api/chat.js >/dev/null 2>&1; then
      issues+=("functions/api/chat.js fails 'node --check' syntax check")
    fi
  fi

  if [[ ! -f demo/index.html ]]; then
    issues+=("demo/index.html missing")
  fi

  if [[ ${#issues[@]} -gt 0 ]]; then
    record FAIL "12 demo UI" "${issues[*]}"
  else
    record PASS "12 demo UI" "wrangler.toml + functions/api/chat.js + demo/index.html ready"
  fi
}
check_13_source_map() {
  local issues=()
  [[ -d corpus ]] || issues+=("corpus/ missing")
  grep -q '## Literature And Source Map' README.md || issues+=("README source map missing")
  local n
  n=$(awk '
    /^### References/ {inside=1; next}
    inside && /^---$/ {inside=0}
    inside && /^[0-9]+\./ {count++}
    END {print count+0}
  ' README.md)
  if [[ "$n" -lt 10 ]]; then
    issues+=("README has $n/10 references")
  fi
  if [[ ${#issues[@]} -gt 0 ]]; then
    record FAIL "13 source map" "${issues[*]}"
  else
    record PASS "13 source map" "README source map + corpus/ present"
  fi
}
check_14_methodology_summary() {
  local f=README.md
  local issues=()
  grep -q 'n=30 x 4' "$f" || issues+=("missing n=30 x 4 panel summary")
  grep -q 'methodology_panel_refset_eval.json' "$f" || issues+=("missing panel artefact reference")
  grep -q 'MaaSwasth Safety Method' "$f" || issues+=("missing method name")
  if [[ ${#issues[@]} -gt 0 ]]; then
    record FAIL "14 methodology summary" "${issues[*]}"
  else
    record PASS "14 methodology summary" "README names the full panel artefact and n=30 x 4 result"
  fi
}
check_15_no_credentials() {
  if ! git rev-parse --git-dir >/dev/null 2>&1; then
    record SKIP "15 no credentials" "not a git repo"; return
  fi
  local hits
  hits=$(git ls-files \
    | grep -iE '(session|cookie|token)\.json$|^\.env$|^\.env\.[^e][^x][^a]' \
    || true)
  if [[ -n "$hits" ]]; then
    record FAIL "15 no credentials" "tracked files look credential-bearing: $(printf '%s' "$hits" | tr '\n' ' ')"
  else
    record PASS "15 no credentials" "no session/cookie/token files tracked (Codex R10)"
  fi
}
run_check "01" check_01_repo_state
run_check "02" check_02_docker_compose
run_check "03" check_03_dep_pinning
run_check "04" check_04_env_example
run_check "05" check_05_test_data
run_check "06" check_06_smoke_gate
run_check "07" check_07_integration
run_check "08" check_08_api_keys
run_check "09" check_09_panel_artifact
run_check "10" check_10_findings_schema
run_check "11" check_11_readme
run_check "12" check_12_demo_ui
run_check "13" check_13_source_map
run_check "14" check_14_methodology_summary
run_check "15" check_15_no_credentials
if [[ -t 1 ]]; then C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YEL=$'\033[33m'; C_OFF=$'\033[0m'
else C_RED=""; C_GRN=""; C_YEL=""; C_OFF=""; fi

printf '\n%-6s %-30s %s\n' "STATUS" "CHECK" "DETAIL"
printf -- '%s\n' "------ ------------------------------ -----------------------------------"
for row in "${ROWS[@]}"; do
  IFS=$'\t' read -r status name detail <<< "$row"
  case "$status" in
    PASS) printf '%s%-6s%s %-30s %s\n' "$C_GRN" "$status" "$C_OFF" "$name" "$detail" ;;
    FAIL) printf '%s%-6s%s %-30s %s\n' "$C_RED" "$status" "$C_OFF" "$name" "$detail" ;;
    SKIP) printf '%s%-6s%s %-30s %s\n' "$C_YEL" "$status" "$C_OFF" "$name" "$detail" ;;
  esac
done

printf '\n%d passed, %d failed, %d skipped\n' "$PASS_N" "$FAIL_N" "$SKIP_N"

if [[ "$FAIL_N" -gt 0 ]]; then
  printf '\nPre-flight: NOT READY — fix the FAIL items above before submission.\n' >&2
  exit 1
fi
printf '\nPre-flight: READY (all required checks passed; SKIPs are explicit gates).\n'
exit 0
