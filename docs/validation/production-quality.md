# Delivery and repository validation

This report covers the production-quality organization and delivery changes on
13 September 2026. It complements the [earlier end-to-end report](end-to-end.md).
The live benchmark and its input fingerprint are unchanged; no new clinical or
model-performance claim is made by restructuring the repository.

## Changes under verification

- One Python manifest/lockfile and one workbench Dockerfile.
- All Python tests under `tests/`, including the workbench suite.
- Guides, methodology, reference, research and validation grouped under `docs/`.
- Local state separated from published evidence and excluded from image builds.
- Non-root container, validated port, health probe and explicit live Compose override.
- CI for both supported Python versions, Worker tests/build and container checks.
- Generated-asset, current-evidence, documentation-link and credential-pattern checks.

CI remains the source of current automated status. Historical paid API tests
are recorded separately in the end-to-end report.

## Dependency maintenance

Promptfoo was patched from 0.121.11 to 0.121.20; its Docker tool image uses the
same version. The npm lockfile was regenerated and unused entries removed.
Audit findings fell from 15 to five affected packages, all high severity in the
optional Transformers/ONNX/Sharp chain. Details and operating scope are in
[SECURITY.md](../../SECURITY.md#known-optional-tooling-advisories).
This work does not claim a clean security audit.


## Executed checks

| Check | Observed result |
|---|---|
| `make check` | 168 Python tests and five Worker tests passed; correctness lint and repository checks passed. |
| Locked Node installation | `npm ci` completed; Worker tests and Wrangler Functions build passed after the clean install. |
| Live Promptfoo integration | One synthetic case through Promptfoo 0.121.20 → Python → Sarvam 105B Conversations → DeepEval/Gemini passed, with zero failed assertions or evaluation errors. |
| Compose startup | `docker compose up --build --wait` reached healthy on local port 8504 without provider credentials. |
| Runtime isolation | UID 10001; application writes rejected; the state volume was writable; no provider environment, local ledgers, experiments or diagnostic smoke results were present in the image. |
| Evidence | Current canonical artifact and aggregate validated inside the container; fingerprinted benchmark inputs and measured artifacts were preserved. |
| Browser | All nine workbench pages opened in the container with zero Streamlit exceptions, using `agent-browser --auto-connect`. |
| Repository hygiene | Relative Markdown file links, common credential patterns and deterministic generated-asset comparison passed. |
| GitHub settings | Private vulnerability reporting and dependency security alerts enabled; repository topics updated. |

The new regression tests cover container port validation, environment precedence,
separate runtime storage and unavailable comparator decisions. Case Explorer now
keeps absent comparison results out of both agreement and disagreement filters.
Older scaffolding XFAIL/SKIP paths for required contracts were replaced with hard
failures, so missing schemas and fixtures cannot silently pass CI.

The CI workflow independently verifies Python 3.11/3.12, Node tooling and a
container on a non-default port, including private-file markers excluded during
the image build. See the [Quality workflow](https://github.com/iamjr15/healtheval/actions/workflows/quality.yml)
for the status of the exact published revision.

## Python dependency follow-up

GitHub's first scan of the published workflow surfaced 100 Python alerts against
the existing lockfile, including four critical findings. Targeted compatible
updates and removal of unused NLTK address that original inventory. A fresh
`pip-audit` of 162 installed packages reports one residual Click advisory blocked
by the current evaluation-framework constraints; see [the dependency record](../../SECURITY.md#python-dependencies).

After these updates, all 168 Python tests and five Worker tests passed again.
The container rebuilt and reached healthy, and the live Promptfoo → Sarvam →
DeepEval/Gemini case passed again with no failed assertions or evaluation errors.
The new `make audit` command exposes current findings rather than suppressing them.

The first published [CI run](https://github.com/iamjr15/healtheval/actions/runs/34762178871)
passed all four jobs. The README was also checked on GitHub: all six screenshots
and both badges loaded, navigation anchors resolved, and the methodology diagram
and expanded screenshot sections rendered.

## Limits

No hosting deployment or external review-persistence backend was provisioned.
Provider billing limits, authenticated public access and durable multi-user state
remain operator responsibilities. One Click advisory and five npm package advisories remain, with scope and
upstream constraints documented in SECURITY.md. Clinical and bilingual validation and the funded full Claude jury remain
outstanding as described in the earlier end-to-end report. These delivery checks
do not change the interpretation of the 90-response benchmark.
