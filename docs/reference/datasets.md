# Datasets and provenance

[Documentation](../README.md) · [Project overview](../../README.md)

## Datasets and source grounding

| Asset | Contents and purpose |
|---|---|
| [Case blueprints](../../data/health_case_blueprints.json) | The 30 authored case definitions and a catalogue of 15 primary sources. |
| [Reference set](../../data/reference_set.yaml) | 30 cases: 10 GREEN, 10 AMBER and 10 RED; ten each in Devanagari, Roman Hindi and Hinglish. |
| [Curated prompts](../../data/prompts.yaml) | The 30 corresponding questions in the prompt schema. |
| [Equity challenges](../../data/equity_challenges_hindi.yaml) | 180 variants: six attributes applied to every reference case, linked by `base_ref_id`. |
| [Safety challenges](../../data/safety_challenges_hindi.yaml) | 30 authored medication-safety, diagnostic-caution and harmful-request challenges. |
| [Personas](../../data/personas.yaml) | Five synthetic personas spanning children, adolescents, adults and older adults. |
| [Shared system prompt](../../data/system_prompt_health.yaml) | Hindi response instructions used by the main candidate clients; also generated into the Worker demo. |
| [Constitution](../../data/constitution.yaml) and [rubrics](../../data/rubrics) | Twelve response principles and four versioned scoring packs. |
| [Calibration examples](../../data/judge_calibration_examples.yaml) | Ten illustrative scoring anchors, with draft provenance and review status. |
| [Source manifest](../../corpus/health_source_manifest.yaml) | Source URLs, relevant sections and paraphrased grounding. |

A reference case includes its original and canonical Devanagari wording, topic,
expected action, factual checklist, unsafe-answer examples, relevant danger signs,
source citations and review status. The equity attributes are caste, disability,
literacy, geography, language and intersectional context. These variants support
paired comparisons; their existence alone is not an equity measurement.

The source catalogue draws on WHO, Government of India, NHS and CDC material.
Indian emergency contacts are checked against Indian sources rather than copied
from overseas guidance. Source passages support particular facts and safety
principles; the case wording, routing labels, rubric scores and thresholds are
HealthEval-authored policy. The challenge sets are authored here, not translations
claimed to come from an external benchmark.

See [Research and source verification](../research/health-sources.md) for all 15 sources,
verification dates, localization decisions and unresolved review needs. Sources
include [WHO diabetes guidance](https://www.who.int/news-room/fact-sheets/detail/diabetes),
[CDC antibiotic safety](https://www.cdc.gov/antibiotic-use/about/index.html), and
[India's Emergency Response Support System](https://112.gov.in/).

<a id="reference-case-preview"></a>

<details>
<summary><strong>See inside a reference case: expectations before scoring</strong></summary>

[![Reference case ref-003 showing the urgent action, RED risk, Roman Hindi question, Hindi factual checklist, required danger signs and source link](../screenshots/reference-case.png)](../screenshots/reference-case.png)

*The case definition makes the expected handling inspectable. Its source context
is explicitly marked as paraphrased, with clinical review pending.*

</details>

<a id="case-explorer-preview"></a>

<details>
<summary><strong>Browse the benchmark: models, risk tiers and case filters</strong></summary>

[![Case Explorer displaying the 30-case benchmark, model selection, risk filters, and the Open Case Detail control](../screenshots/case-explorer.png)](../screenshots/case-explorer.png)

*Choose a model and case, then open the detail view. Optional comparison columns
may have no measurement; that absence is not evidence that an answer passed.*

</details>
