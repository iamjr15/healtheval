# Benchmark inputs

These are synthetic, AI-authored general-health evaluation inputs. Clinical
routing, Hindi wording and scoring anchors are drafts pending independent review.
No patient records are included.

- Edit `health_case_blueprints.json` for case wording, expectations and sources.
- `scripts/build_health_assets.py` generates the reference set, prompt set, shared
  system prompt, constitution, rubric packs, personas and challenge sets.
- `schemas.py` validates the dataset contracts; `rubrics/` contains versioned
  written scoring guides.
- `judge_calibration_examples.yaml` contains ten illustrative draft examples,
  not clinician-approved judgments or training records.

See the [dataset reference](../docs/reference/datasets.md),
[source research](../docs/research/health-sources.md) and
[benchmark change workflow](../docs/guides/development.md#change-the-benchmark-deliberately).
Changing fingerprinted inputs invalidates old scores for the new benchmark.
`make repository-check` checks generated consistency without modifying these files.
