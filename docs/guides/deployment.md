# Deployment and operations

[Documentation](../README.md) · [Configuration](../reference/configuration.md)

The container is an operating path for the evaluation workbench. Public access
and patient-facing use require additional systems and validation described here.
This repository does not provision hosting, authentication or a clinical service.

## Saved-evidence review

From a checkout, with Docker Compose 2.24 or newer:

```bash
docker compose up --build --wait
curl --fail http://localhost:8501/_stcore/health
docker compose logs --tail=100 workbench
```

Open <http://localhost:8501>. The host port is bound to loopback. This profile
contains no provider credentials, makes no live evaluation calls on startup and
uses the published evidence built into the image. It does not mount the checkout
or run tests during service startup; run `make check` before deploying changes.

Use `HEALTHEVAL_PORT=8504 docker compose up --build --wait` when 8501 is occupied.
The named `workbench_state` volume holds writable runtime overlays. The code,
benchmark data and published results are read-only. The container drops Linux
capabilities, runs as UID/GID 10001 and uses a temporary filesystem for caches.

## Enable live evaluation explicitly

Create a local `.env` from `.env.example` if one does not already exist. Set keys
for the candidate and independent judges you intend to use. Then run:

```bash
docker compose -f docker-compose.yml -f compose.live.yml up --build --wait
```

The override reads `.env` at container creation. Keys are injected at runtime,
never copied into the image. A running container does not acquire changed keys
until it is recreated. For an explicit reduced jury, configure
`HEALTHEVAL_JUDGES=gemini-2.5-pro,sarvam-105b`. Credential presence does not prove
billing or model access; start with a small synthetic case.

For hosted environments, inject secrets through the platform's secret mechanism.
Do not publish a rendered Compose configuration containing injected secrets.
Local usage ledgers estimate spend after calls; they do not provide transactional
reservations, per-user enforcement or a hard billing cap. Set provider-side limits
and authenticated request quotas before exposing paid calls to others.

## Container contract

| Property | Contract |
|---|---|
| Application | Streamlit workbench, root `Dockerfile`. |
| User | UID/GID 10001; no root privileges needed at runtime. |
| Port | `PORT`, default 8080, validated between 1 and 65535. |
| Health endpoint | `/_stcore/health`; Docker probes every 15 seconds after a 30-second start period. |
| Evidence | Immutable snapshot under `/app/results`, built from canonical artifacts. |
| Runtime state | `/app/var`; override with `HEALTHEVAL_STATE_DIR` and supply writable storage. |
| Temporary files | `/tmp`; provide writable temporary storage if the root filesystem is read-only. |
| Shutdown | Streamlit receives termination signals; Compose allows 30 seconds to stop. |

A healthy process does not prove valid credentials, complete optional evidence or
clinical readiness. Verify the evidence separately in the running image:

```bash
docker compose exec workbench python -c \
  'from streamlit_app.evidence_validator import validate_evidence; assert validate_evidence() is not None; print("Current evidence validated")'
```

The image build context is an allowlist: source/runtime dependencies,
documentation and canonical benchmark evidence. It excludes `.env`, local state,
experiments, diagnostic smoke runs, Node dependencies and test files. If a new
candidate artifact must be shipped, add its published filename to `.dockerignore`
and verify the image. The optional `Dockerfile.promptfoo` is an evaluation-tool
image, not a second workbench runtime.

## Storage and data lifecycle

`results/` is published, synthetic benchmark evidence. Use ignored
`results/runs/<name>/` for experiments, and review artifacts before intentionally
publishing them. Judge traces contain full prompts, answers and rendered judge
context; live input can therefore become part of an artifact.

`var/` is local runtime state. Budget events can contain a session identifier.
Imported review and threshold logs are read from this directory, while new review
forms and threshold sweeps stay session-local by default and can be exported.
The optional persistence endpoint is operator-supplied; no persistence backend is
included. A local volume alone does not make browser-session reviews durable.

When upgrading from the older layout, move any private `budget_today.jsonl`,
`hitl_reviews.jsonl` and `threshold_sweeps.jsonl` from `results/` to `var/` before
restarting, or temporarily set `HEALTHEVAL_STATE_DIR=results`. Preserve a backup;
do not combine two ledgers without checking duplicates. Repeated deployment
must not unintentionally reset usage accounting or lose review records.

For hosted live use, define access, retention, deletion, backup and provider data
handling for prompts, traces and reviews. Keep real patient information out of
this public benchmark repository. Session-local state is lost when the session
ends; local disks and in-memory Worker counters are not shared across replicas.

## Before allowing public or multi-user access

| Area | Included behavior | Required operating decision |
|---|---|---|
| Access | Local loopback binding; no application login or user authorization. | Put the workbench and Worker API behind authenticated access, HTTPS and appropriate reviewer roles. |
| Spending | Local counters and estimates. | Enforce provider limits and durable request quotas; prevent unauthenticated paid calls. |
| Review storage | Session export or external endpoint integration. | Supply and test an authenticated durable backend, access controls and backups. |
| Scaling | Streamlit session state and local ledger. | Define session affinity, shared state and concurrency limits before using replicas. |
| Monitoring | Container health and application logs. | Monitor provider failures, latency, quota use, failed judge coverage and artifact validation. Avoid logging secrets and private prompt text. |
| Clinical interpretation | Authored draft cases, policies and model judges. | Independent clinical/language review and validation appropriate to the intended use. |

The optional Cloudflare demo has a public-style `/api/chat` handler with no built-in
identity check. Its in-memory budget counter is best-effort and resets across
isolates. It returns a candidate response and parsed triage, not a judged safety
assessment. Protect the route before publishing it with funded credentials.

## Update, verify and roll back

1. Record the deployed commit and image tag. Run `make check` and require passing
   CI on the revision to be deployed.
2. Build the image, verify health and evidence, then browse Overview, a case detail,
   review queue and any enabled live mode with a synthetic input.
3. Preserve runtime state and export in-session reviews before replacing the
   service. Keep the previous image or commit for rollback.
4. On failure, stop the new service and restore the prior image/commit with its
   matching benchmark snapshot. Do not mix old aggregate scores with new inputs.

`docker compose down` stops the service and preserves its named volume. Do not
add `--volumes` unless deleting the local runtime state is intended. Rebuild after
source or evidence changes; a git pull alone does not change a running image.

The container and CI choices follow the official
[uv Docker guide](https://docs.astral.sh/uv/guides/integration/docker/),
[uv lockfile semantics](https://docs.astral.sh/uv/concepts/projects/sync/) and
[Docker non-root guidance](https://docs.docker.com/build/building/best-practices/#user).
