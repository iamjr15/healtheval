# HealthEval documentation

HealthEval evaluates Hindi health chatbot responses and makes the supporting
evidence inspectable. Start with the [project overview](../README.md) and its
screenshots, then choose the guide that matches your task.

| Task | Read |
|---|---|
| Understand the question → response → score → review process | [Evaluation methodology](methodology/evaluation.md) |
| Browse cases, explanations and human review | [Workbench guide](guides/workbench.md) |
| Run a small check or reproduce the included panel | [Evaluation guide](guides/evaluations.md) |
| Install, test and contribute changes | [Development guide](guides/development.md) and [contribution guide](../CONTRIBUTING.md) |
| Build and operate the container | [Deployment and operations](guides/deployment.md) |
| Configure credentials, limits and storage | [Configuration reference](reference/configuration.md) |
| Understand the folders and component boundaries | [Architecture](reference/architecture.md) |
| Inspect authored inputs and their review status | [Datasets](reference/datasets.md) and [verified sources](research/health-sources.md) |
| See what has actually been tested | [End-to-end validation](validation/end-to-end.md) and [delivery checks](validation/production-quality.md), plus [dashboard usability](validation/dashboard-usability.md) |
| Inspect optional research methods | [Perturbation audit](methodology/perturbation-audit.md), [CeRAI findings](methodology/cerai-findings.md) |
| Repeat visual QA | [Browser QA](guides/browser-qa.md) and [screenshot capture guide](screenshots/README.md) |

The checked-in cases and scoring anchors are synthetic drafts pending clinical
and Hindi-language review. Software verification, LLM judgments and independent
clinical validation are different forms of evidence; the documentation names
which one supports each claim.
