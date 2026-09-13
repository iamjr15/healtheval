# HealthEval local QA task

Review the HealthEval workbench from the repository root. Produce a reproducible
local QA report and make focused fixes for confirmed problems. This template
requires Claude Code and an already running Chrome with remote debugging; it is
optional and is not part of installation, tests or deployment.

## Scope and setup

- Read applicable repository instructions and the `dogfood` and `agent-browser`
  skills when available.
- Use the local workbench at `http://localhost:8501`, or the port supplied by the
  operator. If needed, start it with
  `uv run streamlit run streamlit_app/app.py`.
- Store the report, screenshots and diagnostic logs under `tasks/dogfood-output/`.
- Use `agent-browser --auto-connect` for every browser command. Do not install or
  launch a separate browser. Take a fresh snapshot after navigation or DOM changes.
- Use saved evidence by default. Live calls need configured, funded providers and
  the operator's requested live-testing scope. Use synthetic prompts.

## Review workflow

1. Walk Overview, Live Demo, Case Explorer, Human Review Queue, Safety Thresholds,
   Judge Memory, Scoring Rubrics, Audit Trace and Evaluator Stability.
2. Check each page's purpose, primary interaction and empty/error state. Verify
   that unavailable comparison evidence is clearly distinguished from a score.
3. Confirm that patient urgency and answer-review quality remain separate in
   labels, examples and metrics.
4. For each confirmed issue, record the page, reproduction steps, expected versus
   actual behavior, and a screenshot when useful.
5. Make focused fixes to confirmed issues. Preserve measured evidence and the
   distinction between synthetic fixtures and real provider outputs.
6. Run appropriate tests, revisit affected pages, and record what passed and any
   remaining limits. Do not claim checks that were not performed.
7. Write `tasks/dogfood-output/report.md` with findings, fixes, changed files,
   validation and remaining work.

## Boundaries

Do not edit credentials or private review records. Do not replace `data/`,
`corpus/` or `results/` just to make a screenshot look complete. Do not deploy or
commit/push as a side effect of this local QA template. If the operator explicitly
requests publication, use their supplied repository or hosting configuration;
this template assumes no cloud project, account or deployed service.

If a required local tool or browser connection is unavailable, record the exact
failure and remaining checks. Avoid repeated blind retries.
