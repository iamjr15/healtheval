# MaaSwasth Evaluation Workbench (Streamlit)

Dashboard for checking whether Hindi maternal health chatbot answers are safe,
source grounded, and easy to audit. It shows the saved reference set run, lets
reviewers inspect individual cases, tune safety thresholds, submit human
reviews, read judge memory examples and rubrics, and replay detailed judge
traces where available.

## Live deployment

| Surface | URL |
|---|---|
| **Workbench (this app)** | https://maaswasth-workbench-491690076762.asia-south1.run.app |
| Source repo | https://github.com/iamjr15/maaswasth-eval |

## Local run

```bash
# from repo root
cp .env.example .env
# fill provider keys in .env
docker compose up --build
```

Then open `http://localhost:8501`.

For a host run instead:

```bash
uv sync --frozen --extra dev
uv run streamlit run streamlit_app/app.py
```

### Environment variables

| Var | Required | Default | Purpose |
|---|---|---|---|
| `SARVAM_API_KEY` | yes (for Live Demo) | none | Sarvam-30b and Sarvam-105b panel calls plus Sarvam-105b judge |
| `GOOGLE_API_KEY` | yes (for Live Demo) | none | Gemini 2.5 Pro panel call and judge |
| `ANTHROPIC_API_KEY` | yes (for Live Demo) | none | Claude Sonnet 4.6 panel call and judge |
| `HITL_ADMIN_TOKEN` | optional | none | Gates Human Review Queue repo saving actions |
| `DAILY_BUDGET_USD` | optional | `5.00` | Hard cap on Live Demo spend per UTC day |

For local development, the Streamlit Live Demo loads the repo `.env` file
without overriding real environment variables.

## Page map (8 pages)

1. **Overview**: headline results, definitions, and limits
2. **Live Demo**: run one Hindi prompt through the evaluation pipeline
3. **Case Explorer**: inspect any reference case end to end
4. **Human Review Queue**: review cases routed to a person
5. **Safety Thresholds**: test how thresholds change catch rate and false alarms
6. **Judge Memory**: inspect approved examples used to calibrate the judge
7. **Scoring Rubrics**: read the scoring rules
8. **Audit Trace**: replay judge call evidence where traces exist

## Refreshing evidence

The workbench reads saved evidence from `results/`. Human review actions write
reviewer overlays to `results/hitl_reviews.jsonl`. To refresh the measured
panel artefact:

```bash
# regenerate the full MaaSwasth n=30 x 4 panel reference set run
uv run python scripts/run_panel_refset_eval.py --force --judge-workers 6
uv run python scripts/compute_panel_tool_meta.py
```

Then redeploy:

```bash
gcloud run deploy maaswasth-workbench --source . --region asia-south1 \
    --clear-base-image \
    --set-secrets "SARVAM_API_KEY=SARVAM_API_KEY:latest,GOOGLE_API_KEY=GOOGLE_API_KEY:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest,HITL_ADMIN_TOKEN=HITL_ADMIN_TOKEN:latest,DAILY_BUDGET_USD=DAILY_BUDGET_USD:latest"
```

## GCP deploy (one time setup)

This is already done for project `maaswasth-eval-workbench-2026`. It is kept
here for reproducibility.

```bash
gcloud projects create maaswasth-eval-workbench-2026 \
    --name="MaaSwasth Eval Workbench"
gcloud config set project maaswasth-eval-workbench-2026

# billing
BILLING_ACCT=$(gcloud beta billing accounts list \
    --filter='OPEN=True' --format='value(ACCOUNT_ID)' | head -1)
gcloud beta billing projects link maaswasth-eval-workbench-2026 \
    --billing-account=$BILLING_ACCT

# APIs
gcloud services enable \
    run.googleapis.com cloudbuild.googleapis.com \
    secretmanager.googleapis.com artifactregistry.googleapis.com

# secrets (read keys from the local .env)
set -a && source .env && set +a
echo -n "$GOOGLE_API_KEY"     | gcloud secrets create GOOGLE_API_KEY     --data-file=-
echo -n "$ANTHROPIC_API_KEY"  | gcloud secrets create ANTHROPIC_API_KEY  --data-file=-
echo -n "$SARVAM_API_KEY"     | gcloud secrets create SARVAM_API_KEY     --data-file=-
echo -n "$(openssl rand -hex 32)" | gcloud secrets create HITL_ADMIN_TOKEN --data-file=-
echo -n "5.00"                | gcloud secrets create DAILY_BUDGET_USD   --data-file=-

# grant Cloud Run runtime SA read access on each secret
PROJECT_NUMBER=$(gcloud projects describe maaswasth-eval-workbench-2026 \
    --format='value(projectNumber)')
for SECRET in SARVAM_API_KEY GOOGLE_API_KEY ANTHROPIC_API_KEY HITL_ADMIN_TOKEN DAILY_BUDGET_USD; do
  gcloud secrets add-iam-policy-binding $SECRET \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
done

# deploy
gcloud run deploy maaswasth-workbench --source . \
    --region asia-south1 --allow-unauthenticated \
    --memory 1Gi --cpu 1 --timeout 300 --max-instances 5 --port 8080 \
    --clear-base-image \
    --set-secrets "SARVAM_API_KEY=SARVAM_API_KEY:latest,GOOGLE_API_KEY=GOOGLE_API_KEY:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest,HITL_ADMIN_TOKEN=HITL_ADMIN_TOKEN:latest,DAILY_BUDGET_USD=DAILY_BUDGET_USD:latest"
```

`Dockerfile` lives at the repo root so `gcloud run deploy --source .` picks it
up. An identical copy under `streamlit_app/Dockerfile` is the canonical
reference for the build context (root) plus entry layout.

## Cloudflare DNS proxy (optional, post deadline)

The bare `*.run.app` URL is fine for review. To put Cloudflare in front for
WAF and per IP rate limiting:

1. Add a CNAME on the user's CF zone: `workbench.<domain>` to
   `maaswasth-workbench-491690076762.asia-south1.run.app` (proxy ON).
2. CF WAF rule: rate limit `30 req/min/IP` on `/`.
3. Update Cloud Run with `--add-custom-audiences` if Cloud Run requires
   the custom hostname for IAP style auth.

## Deliberately outside this dashboard

- Building new reference set cases.
- Running self consistency sweeps.
- Expanding the translated adversarial sets.
- Editing the saved automated evidence in place.
