# Configuration reference

[Documentation](../README.md) · [Evaluation guide](../guides/evaluations.md)

Python reads the repository's optional `.env` without overriding process
environment variables. The workbench loads it before calculating limits and
paths. Saved-evidence browsing needs no keys. Restart after changing settings.
The default Compose profile does not inject `.env`; add `compose.live.yml` for
live access. Wrangler reads `.dev.vars` for the optional local response demo.
Both files and `.streamlit/secrets.toml` are ignored by Git.

## Providers and judging

| Variable | Purpose |
|---|---|
| `SARVAM_API_KEY` | Sarvam candidates and the Sarvam judge. |
| `ANTHROPIC_API_KEY` | Claude candidate and judge. |
| `GOOGLE_API_KEY` | Gemini candidate and judge. |
| `GEMINI_API_KEY` | Gemini alias; a nonempty `GOOGLE_API_KEY` takes precedence. |
| `HEALTHEVAL_JUDGES` | Optional comma-separated judge IDs. Explicit batch `--judges` wins; live single-prompt scoring follows the saved artifact's jury. |
| `CERAI_BASE_URL` | Optional external CeRAI endpoint; no service is included. |
| `CERAI_DB_SCORE_CUTOFF` | Comparator review cutoff, default 0.5. Lower available scores route for review. |

Supported candidates are `sarvam-105b-conversations`, `sarvam-105b`,
`claude-sonnet-4-6` and `gemini-2.5-pro`. Every scored answer needs an independent
model family; the two Sarvam variants exclude each other. Missing, placeholder,
unfunded or unauthorized credentials cannot run a live panel.

## Workbench limits and state

| Variable | Default | Scope |
|---|---|---|
| `HEALTHEVAL_STATE_DIR` | `var/` under the checkout | Private local budget/review/threshold overlays; relative paths resolve from the repo root. Docker uses `/app/var`. |
| `DAILY_BUDGET_USD` | `5.00` | Best-effort workbench budget estimate, not a batch CLI or provider cap. |
| `LIVE_DEMO_RATE_LIMIT_PER_SESSION` | `5` | Workbench dispatch count per browser session. |
| `LIVE_DEMO_MAX_PROMPT_CHARS` | `1000` in code; example config uses `1200` | Maximum live prompt length. |
| `HITL_REVIEW_RATE_LIMIT_PER_SESSION` | `30` | Review submissions per browser session. |
| `CLOUDFLARE_HITL_ENDPOINT_URL` | Unset | Operator-supplied persistence endpoint; otherwise reviews are session-local and exportable. |
| `HITL_ADMIN_TOKEN` | Unset | Authenticates the optional review integration. Can also be supplied through Streamlit secrets. No backend is shipped. |
| `GITHUB_REPO_URL` | This repository | Workbench repository/help links. |
| `CLOUDFLARE_LIVE_DEMO_URL` | Unset | Optional externally hosted demo link. |
| `GOOGLE_CLOUD_PROJECT` | Unset | Optional project metadata; does not provision cloud resources. |
| `PORT` | `8080` | Container listening port. Native Streamlit uses its CLI/server settings. |
| `HEALTHEVAL_PORT` | `8501` | Compose host port, bound to loopback. |

Existing private overlays formerly lived in `results/`; see the
[upgrade instructions](../guides/deployment.md#storage-and-data-lifecycle).
Do not place provider secrets in code, source manifests, committed traces or
image layers. Live prompts and responses are sent to selected model providers.

## Optional tooling

| Variable | Used by |
|---|---|
| `BUDGET_CENTS_PER_DAY_SARVAM_CONVERSATIONS` | Worker conversation-model counter. |
| `BUDGET_CENTS_PER_DAY_SARVAM_105B` | Worker reasoning-model counter. |
| `BUDGET_CENTS_PER_DAY_CLAUDE_SONNET_46` | Worker Claude counter. |
| `BUDGET_CENTS_PER_DAY_GEMINI_25_PRO` | Worker Gemini counter. |
| `PROMPTFOO_PYTHON` | Python executable for Promptfoo adapters; set to the absolute `.venv/bin/python` path. |
| `HEALTHEVAL_PROMPTFOO_LIMIT` | Small Promptfoo case limit. |
| `HEALTHEVAL_DEEPEVAL_MODEL` | Promptfoo assertion judge, default `gemini-2.5-pro`. |
| `HEALTHEVAL_DEEPEVAL_THRESHOLD` | Promptfoo assertion threshold, default `0.50`; separate from the main 1–5 safety method. |
| `PROMPTFOO_DISABLE_TELEMETRY` | Optional Promptfoo telemetry setting; use `1` for local evaluation. |
| `HEALTHEVAL_QA_LOG_DIR` | Optional local QA runner log directory, default `var/qa/logs`. |
| `HEALTHEVAL_CLAUDE_BIN` | Optional local QA runner CLI, default `claude`. |

Worker budget defaults are 500 cents per model. The counter charges an estimated
one cent per dispatch, not token-accurate usage, and is stored in isolate memory.
It cannot enforce a reliable cross-instance or provider spending cap.

`uv run python scripts/check_env.py .env` checks the file's basic shape without
printing values. `--require-keys` requires all three providers and checks presence
only; it does not contact them. Selected batch runs validate the keys needed by
the selected candidate/jury. For exhaustive options, use each CLI's `--help`.
