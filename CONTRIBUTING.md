# Contributing to HealthEval

Thanks for helping improve a clear, reproducible health-response evaluation tool.
Start with the [README](README.md), [architecture](docs/reference/architecture.md)
and [development guide](docs/guides/development.md).

## Make a change

1. Create a focused branch and explain the problem or behavior being improved.
2. Run `make setup`, then implement the change with a regression test when it
   affects parsing, scoring, evidence handling or application behavior.
3. Run `make check`. For JavaScript changes also run `npm run build:worker`; for
   container changes follow the operations guide and verify health/evidence.
4. Update the relevant guide. For UI changes, inspect the actual application and
   refresh screenshots only when the visible behavior changes.
5. Open a pull request describing the problem, resulting behavior, validation
   performed and any remaining limitations.

Python tests are offline. Do not add a test that requires funded credentials or
replace published measurements with mocked outputs. Keep keys, private prompts,
reviewer information and local runtime state out of commits and screenshots.

## Dataset or methodology changes

Read the [benchmark change workflow](docs/guides/development.md#change-the-benchmark-deliberately).
Preserve source citations, localization decisions, draft provenance and the
separation between patient urgency and answer quality. Do not describe synthetic
anchors as human-approved. A changed benchmark requires new evidence rather than
relabeling an existing run. Document a changed jury or scoring profile explicitly.

## Reporting problems

Use a bug report with reproduction steps, expected and actual behavior, the
commit/version, environment and sanitized errors. For an evaluation concern,
include the synthetic case ID, model, jury and fingerprint where available.
Report credential exposure and security issues through [SECURITY.md](SECURITY.md).
Do not include patient information or API keys in a public issue.

Contributions to original project code and material use the existing
[Apache 2.0 license](LICENSE). Preserve third-party attribution and rights.
