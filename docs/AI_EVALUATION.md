# Reviewed AI response corpus and bounded scoring

Run the packaged evaluator without a model, credentials or checkout:

```sh
settlementlab-evaluate-ai --report-dir artifacts/ai-review
```

An installed wheel includes datasets/triage-reviewed-v1.json. --dataset PATH selects another corpus using the same schema. Output is evaluation.json plus offline index.html. No provider is called and no model is downloaded.

## What was reviewed

The corpus contains four unmodified historical local-model responses and five agent-authored positive/adversarial fixtures. Every historical entry records the source path, source-file SHA-256, model and prompt version, plus its original evidence. The real failed first passes are retained, not replaced with successful answers. Source provenance is checked by regression tests.

Criterion labels were reviewed by the implementing agent against the supplied synthetic facts. This is not independent human review. A future external review can challenge the labels or add unseen examples without changing the preserved source captures.

## Criteria

- Schema: exact required fields, bounded text and a bounded references list.
- Citations: references exist in the supplied envelope and include this case's required facts/breaks.
- Facts: required lexical claim patterns occur and known contradictory patterns do not.
- Uncertainty: the answer states the cause is not established/cannot be determined, under the case's bounded pattern.
- Safe next step: the action text does not recommend automatically approving, settling or funding. Explicit negations are handled in the tested forms.
- Stage relevance: stage-specific forbidden context is absent, such as available funding claims during an allocation-only exception.

These checks are deliberately bounded. Regex matches do not understand every paraphrase or negation, valid citations do not prove that a claim is supported, and matching number tokens does not establish general arithmetic reasoning. Do not treat this evaluator as a safety gate for arbitrary model output. It complements the application's existing output/citation validation and operator review.

## Interpreting results

responses_meeting_rubric counts responses passing every bounded criterion. responses_not_meeting_rubric keeps failures visible. Per-criterion counts are reported without an invented model-accuracy percentage.

The report's status and CLI exit code describe whether computed checks match the reviewed fixture labels. A passing evaluator can and should contain bad model responses. This is a regression harness, not a claim that the model answered every case correctly. Tests mutate a factual answer while preserving its valid references and verify that the case no longer meets its original labels.

Zero model calls in an offline run means it does not measure present-day latency, installed-model availability or current output quality. Existing opt-in live local inference and historical model examples remain separate. No automatic live campaign or external AI judge is introduced.
