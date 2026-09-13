# HealthEval Workbench

A Streamlit interface for reviewing Hindi general-health chatbot responses.

Run from the repository root:

```bash
uv sync --frozen --extra dev
uv run streamlit run streamlit_app/app.py
```

Open <http://localhost:8501>. Reference cases and rubrics are available without
API credentials. Live panel/judge calls require funded provider keys in `.env`.
The default candidate is `sarvam-105b-conversations`.

The nine pages cover overview, live prompts and conversations, case exploration,
human review, thresholds, judge memory, rubrics, traces and evaluator stability.
Results are accepted only for the current benchmark fingerprint. Missing runs or
comparators are shown as unavailable; historical scores are not reused.

Draft source-grounded assets are not clinical validation. Synthetic calibration
anchors are labeled as draft reference scores and have no human approval.

Session-local reviews can be downloaded. Persistent review saving requires
`HITL_ADMIN_TOKEN` and `CLOUDFLARE_HITL_ENDPOINT_URL`. Live demo controls include
`DAILY_BUDGET_USD`, `LIVE_DEMO_RATE_LIMIT_PER_SESSION`, and `LIVE_DEMO_MAX_PROMPT_CHARS`.

See the root [README](../README.md) for datasets, models, tests and research.
Deployment uses the root Dockerfile. Supply your own existing cloud project and
service configuration; no new hosted endpoint is implied by the project rename.
