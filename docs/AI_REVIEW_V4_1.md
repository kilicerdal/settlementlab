# V4.1 AI review

The AI remains a read-only local exception explainer. It cannot approve, fund, settle or execute tools. Deterministic financial controls remain authoritative.

```sh
settlementlab-review-ai --report-dir artifacts/ai-review
# Optional: only if this model is already installed in local Ollama
settlementlab-review-ai --model qwen2.5:3b --report-dir artifacts/ai-live-review
```

The default makes zero model calls. It combines the [historical corpus](AI_EVALUATION.md) with seven explicitly synthetic adversarial response fixtures. Six intentionally bad answers must fail their labelled criteria and one advisory control must meet them. Harness success means agreement with those labels, not that the six answers are good or that a model achieved a success rate.

Criteria cover schema, valid/required evidence IDs, case-specific fact patterns, uncertainty language, bounded unsafe-action patterns and lifecycle relevance. New unsafe-action expressions are supplied explicitly by the case rubric; negation and natural-language meaning remain imperfect. These regular-expression checks cannot prove factual correctness or robust prompt-injection resistance.

With `--model`, two samples use the actual local adapter against fixed loopback `127.0.0.1:11434`: an ordinary evidence envelope and one containing an untrusted instruction in a fact. Both responses, elapsed times, actual model identifier, per-criterion outcomes, and provider/validation errors are retained in `review.json`. The CLI returns nonzero if a sample fails validation or the bounded rubric. No downloads, cloud endpoint, fallback response, API key, or paid request is used.

During V4.1 implementation Ollama was unavailable, so live local sampling was **not run**. Historical recorded results and synthetic harness checks are available; this is not a fresh live-model benchmark. Run the opt-in command to add new evidence from your machine. A passing injection fixture alone does not establish real-model resistance.
