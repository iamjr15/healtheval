# Security reporting

## Scope

HealthEval is an evaluation workbench. The current development branch receives
fixes; no long-term support or guaranteed response time is offered. The
[operations guide](docs/guides/deployment.md) records current access, spending,
storage and deployment boundaries.

## Report a vulnerability privately

Use GitHub's [private vulnerability report](https://github.com/iamjr15/healtheval/security/advisories/new).
Include the affected commit, reproduction steps, impact and a minimal sanitized
example. Never paste live keys, patient information or private reviewer records.

If private reporting is unavailable, open a public issue asking for a private
contact route without disclosing exploit details or sensitive data. Do not use
public issues for a live credential or data exposure. Revoke exposed credentials
at the provider and preserve a sanitized incident record.

## Repository and runtime boundaries

Secrets belong in ignored local files or a deployment secret store. The default
container has no provider keys, binds to local access through Compose and runs
without root privileges. It is not an authentication layer. Protect any public
workbench or `/api/chat` route before enabling funded calls.

Judge traces retain full prompts and responses. Use synthetic inputs for shared
artifacts. Local usage counters are best-effort and do not impose a hard provider
billing cap. Session-local review forms are not durable storage. These are
explicit operating limitations, not evidence that public hosting is configured.

## Known optional-tooling advisories

On 13 September 2026, updating pinned Promptfoo from 0.121.11 to 0.121.20 reduced
`npm audit` findings from 15 affected packages to **five high-severity package
entries**. The remaining chain is Promptfoo → optional Hugging Face Transformers
→ ONNX/Sharp, with findings in `adm-zip` and Sharp's bundled native libraries.
These packages are not installed in the Python workbench image. The documented
Python-backed text evaluation does not use local Transformers inference.

This is not a clean dependency audit. Review these advisories before using
Promptfoo features that process external archives, model files or images:
[ZIP allocation](https://github.com/advisories/GHSA-xcpc-8h2w-3j85),
[ZIP symlink extraction](https://github.com/advisories/GHSA-vwc7-r8mq-g2x9),
[Sharp/libvips](https://github.com/advisories/GHSA-f88m-g3jw-g9cj) and
[Sharp/libheif](https://github.com/advisories/GHSA-rgj7-g3m4-5g8c).
At verification, the latest Promptfoo release retained this optional chain.
An incompatible transitive override or forced downgrade was not applied merely
to remove the audit count. Re-run `npm audit` when dependency updates arrive;
Dependabot proposals and security alerts are enabled.
