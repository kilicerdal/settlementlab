# Local investigator evaluation

This evaluator measures a bounded task: reporting supplied synthetic observations with valid claim codes and citations, abstaining when observations are absent, and preserving uncertainty. It is an engineering measurement, not an independent assessment of arbitrary financial explanations.

## Run it for free

From an installed source checkout, choose a fresh output directory:

```sh
# Deterministic adversarial contract fixtures; no model calls.
PYTHONPATH=src python -m settlementlab.assurance.investigator_evaluation --output artifacts/ai-contract-new

# Optional: already-installed local Ollama model; six contexts, two rounds.
PYTHONPATH=src python -m settlementlab.assurance.investigator_evaluation \
  --live-model qwen2.5:3b --repeats 2 --output artifacts/ai-live-new
```

No paid provider or model download is used. The loopback transport, prompt, schema and generation options match the application investigator. One to five rounds are allowed, with at most 30 calls per run. A round visits all six contexts before the next round. Temperature zero and repeated output do not establish independent statistical trials.

## What the report measures

Every rate in `live.metrics` carries a numerator, denominator and nullable rate. Empty populations produce `null`, not a fabricated zero.

| Metric | Population and meaning |
| --- | --- |
| Recording / schema-valid / contract acceptance | Divide by **all requested slots**, including unavailable, malformed and unattempted slots. |
| Strict success | All requested slots; requires application contract acceptance, correct abstention, complete coverage of supplied observation codes and successful canonical presentation. |
| Observation coverage | Supplied observation codes across schema-valid nonempty responses, counted only when the claim has valid citations for that code. Missing codes are listed per response and context. Read alongside all-requested strict success. |
| Unsupported claims / invalid citations | Schema-valid responses only; this conditional population is explicit. |
| Unnecessary abstention | Schema-valid responses to nonempty evidence. |
| Required abstention | Schema-valid responses to empty evidence. |
| Repeat consistency | Contexts with at least two requested rounds and every round schema-valid. Compares abstention, codes **and citation IDs**, ignoring prose. Incomplete contexts are non-comparable; stable wrong answers can still be consistent. |
| Latency | Wall-clock transport plus validation for every attempted call, including failures; median and nearest-rank p95, with sample count. Not a performance guarantee. |

`accepted_rate` now uses all requested slots. The older, successful-output-only denominator is available explicitly as `conditional_accepted_rate`; do not compare these interchangeably with archived reports. `quality_status` describes the structured evaluation; top-level `status` still describes the separate deterministic fixture checks.

The report retains per-context results, failure categories, bounded raw response text (including invalid/truncated outputs), prompt/schema/corpus hashes, options and timing. An oversized output retains its first 16,384 characters and an explicit truncation flag.

## Canonical investigator presentation

The API now renders displayed summaries from validated structured claims and fixed observation descriptions. Each summary item names its code and one exact evidence ID; all additional validated IDs remain attached to that claim's structured links. Uncertainty is fixed server text. Model-written summary and uncertainty are never interpolated into the displayed explanation. Unknown description codes and invalid or oversized presentations fail closed.

For example, the retained erroneous model prose associates IDs in the wrong order, while the displayed text explicitly says `POSITION_LAG [position:event2]` and `COMPENSATION_POSTED [journal:inverse]`. The claim buttons retain those same validated bindings. The UI layout is unchanged; this applies to the incident investigator, not every AI feature in the framework.

Evaluation version `incident-evaluation-v3` retains both `response` / `raw_response` and `displayed_analysis`. Its all-requested `presentation` metric counts successful canonical rendering; strict success now also requires that rendering. A completed 12-call local sample passed 12/12 structured/presentation slots, while both raw lagging-position summaries still contained the known prose error. [Retained raw-versus-displayed evidence](examples/incident-ai-presentation-v1.json). This fixes the served explanation, not the model's underlying prose generation.

Five added unit controls replay all four original failing summaries through the actual investigator, reorder claims, test invalid/unknown mappings, abstention and multiple references, and check evaluation retention. A real HTTP/browser journey injects the same error with live synthetic record IDs, verifies the displayed pairings and unchanged financial state. Full local controls passed 228 tests plus four scenarios and the coverage gate. Supplied observations still are not authenticated external truth.

## Partial runs and exit codes

`results.json` is replaced atomically after each attempted call. `run_status`, requested/attempted/not-attempted counts and failure rows keep incomplete work visible. Ctrl+C during inference records an interrupted attempt and returns 130. Abrupt termination can leave the last checkpoint marked `running`; it must not be counted as a completed experiment. Checkpoints are evidence retention, not automatic resumption.

Existing evidence is never overwritten: select a fresh directory for another run. A live run exits 1 if any requested slot fails strict structured success, including unavailable or malformed responses. A completed failing evaluation is a valid retained result; do not discard it or present only successful calls. Deterministic CI uses fixture responses and never claims to have run a model.

## Retained local measurements

See [the measurement record](examples/incident-ai-evaluation-v2.json) for actual responses, model identity, source fingerprints and both development/final runs. Both development and final samples completed 12/12 requested calls and passed 12/12 structured slots, with 26/26 supplied observation codes covered and correct abstention on 2/2 empty-evidence slots per run. Nevertheless, inspection found a prose citation-order error in both `lagging-position` repetitions of each run: its “respectively” wording associates the two IDs with the wrong observation order. The JSON claims themselves cite the correct IDs.

That finding is retained separately from structured metrics. It demonstrates why a structured `quality_status: passed` is not a free-text truth guarantee. The final sample's median call latency was 3.49 seconds and nearest-rank p95 was 7.67 seconds across 12 attempts on this machine. Neither sample is a blind holdout or an independent human review; the prose finding is not an exhaustive semantic audit. The final committed evaluator passed 223 unit/API/integration tests plus four assurance scenarios locally, with the existing 85% coverage gate passing.

All expected codes and evidence IDs are already supplied to the model. A deterministic formatter can cover that extraction task; these measurements do not establish incremental benefit from using AI. No production data, market connectivity, financial mutations or new model-accuracy claim is introduced. Older prompt-development results remain in [the incident AI guide](V4_3_AI.md).
