# Perturbations Data Schema

Inputs to the real-world robustness audit (`docs/perturbation_audit.md`).

## Design note

Both evaluators (MaaSwasth jury and CeRAI metric-layer) score the SAME response text.
Base responses are sourced from `results/panel_refset_eval/sarvam-105b.json` — sarvam-105b's
outputs under the maaswasth system prompt (JSON triage block + Hindi prose). Perturbations
modify only the Hindi prose portion; the JSON triage block is held constant so prose-form
variation is isolated as the single variable under test.

## base_responses.jsonl

One JSON object per line:

| Field | Type | Description |
|---|---|---|
| `prompt_id` | string | `ref-NNN` matching `data/reference_set.yaml` |
| `user_prompt` | string | Original Hindi prompt |
| `base_response` | string | Full response text (JSON triage + Hindi prose), verbatim from panel data |
| `base_response_prose` | string | The Hindi prose portion only (the perturbation target) |
| `base_response_triage_block` | string | The JSON triage block prefix (held constant across perturbations) |
| `base_source` | string | Provenance — `panel_refset_eval/sarvam-105b.json:ref-NNN` |
| `violation_expected` | bool | Ground-truth label from reference set |
| `expected_urgency` | string | Reference-set urgency tier |
| `selected_rationale` | string | Why this base is in the 5 |

## perturbed_responses.jsonl

One JSON object per line:

| Field | Type | Description |
|---|---|---|
| `prompt_id` | string | matches base |
| `perturbation_type` | string | one of `script_swap`, `code_mix`, `length_compress`, `style_inflate`, `style_deflate`, `authority_register` |
| `base_response` | string | full original response (JSON + prose) |
| `perturbed_response` | string | full perturbed response (JSON triage block held constant + perturbed prose) |
| `perturbed_prose` | string | the perturbed prose portion only |
| `factual_diff` | object | `{"facts_dropped": [...], "facts_added": [...], "facts_preserved": [...]}` from verifier |
| `verifier_pass` | bool | true iff `facts_dropped` and `facts_added` are both empty |
| `generator_model` | string | model used to generate (e.g. `claude-sonnet-4-6`) |
| `verifier_model` | string | independent model used to verify (e.g. `gemini-2.5-pro`) |
| `attempt` | int | retry count (0 = first try) |

## Perturbation type definitions

- **script_swap** — Convert Hindi prose from Devanagari to Roman script (Hinglish-script). Preserves all medical facts. Cites Khullar et al. 2025 as the published precedent.
- **code_mix** — Natural Hinglish (mixed Hindi + English keywords) as real users write. Same medical facts.
- **length_compress** — SMS-length compression. Preserves safety-critical facts (doses, helplines, referrals); may drop politeness phrases.
- **style_inflate** — Confident, authoritative clinical register, may add citation-shaped phrases. No new medical facts.
- **style_deflate** — Casual ASHA-worker register. Removes citations; preserves medical facts.
- **authority_register** — ASHA training manual voice (instructional, third-person, structured).
