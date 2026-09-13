# Sources and attribution

`health_source_manifest.yaml` records the fifteen primary sources used to inform
the authored general-health cases. It is generated from the source catalogue in
`data/health_case_blueprints.json`. See the
[source research](../docs/research/health-sources.md) for URLs, relevant sections,
verification dates, localization choices and unresolved review needs.

The supporting PDFs are third-party reference publications:

| File | Source |
|---|---|
| `asha_module_7_child_health.pdf` | Government of India ASHA training material on child health; attribution is retained in the publication. |
| `who_lmm_2024.pdf` | WHO guidance on ethics and governance of large multimodal AI models in health, 2024; attribution is retained in the publication. |

These publications retain their own copyright and reuse terms. The project's
Apache 2.0 license does not relicense them or imply endorsement by their authors.
The benchmark uses authored scenarios and paraphrased expectations; source
material does not validate the project's labels or scoring thresholds.

Optional `bash scripts/download_corpus.sh` downloads source cache files and
provenance under ignored `corpus/cache/`. The committed catalogue remains
inspectable offline. Do not add private records or unreviewed source dumps here.
