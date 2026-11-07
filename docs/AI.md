# Local AI-assisted exception triage

The local console includes **Analyze exception with AI** on allocation and settlement exceptions. This invokes a local Ollama model with a JSON-schema-constrained response. No paid API, API key, cloud account, or third-party Python dependency is required. Model inference uses your computer's memory and compute resources.

## Setup

Install Ollama from its official distribution if it is not already present, then:

```sh
ollama serve                  # only if Ollama is not already running
ollama pull qwen2.5:3b         # only if the model is not installed
PYTHONPATH=src python3 -m settlementlab.server
```

The adapter always calls `http://127.0.0.1:11434/api/chat`. The default model is `qwen2.5:3b`; set `SETTLEMENTLAB_MODEL` to another installed local model to change it. An empty model setting disables AI. The application never downloads models automatically. Missing models and unavailable servers produce explicit errors; there is no simulated-AI fallback.

## Data and authority boundaries

The model receives only a bounded synthetic envelope: trade identity/version, lifecycle state, quantity totals, required/available cash and securities, and the latest 20 audit action identifiers. Free-form account names, instructions, actors, request keys, and audit details are excluded. The application sends no analysis data to cloud endpoints. Do not use real financial data with this prototype.

The model has no tools or mutation interface. Its output contains a summary, likely cause, next investigation step, evidence references, and uncertainty. References must identify supplied facts or events. Missing or invented citations, malformed output, refusals, incomplete output, and provider failures are rejected. Schema and reference validation do not prove semantic correctness; operator review remains necessary.

The response identifies local provider, model, prompt version, and analyzed trade version. Results are advisory and may be stale if another operator changes the trade during analysis. Refresh before acting. One model request may run at a time per local server; requests time out after 60 seconds. No automatic retries or background inference occurs.

## Verification and evaluation

Contract tests use injected model responses to verify request shape, evidence minimization, provenance, citation rejection, invalid/incomplete handling, and disabled configuration. These are adapter and boundary tests, not a model-quality benchmark.

For live evaluation, run synthetic allocation mismatch, insufficient cash, insufficient securities, and recovered-settlement cases. Record model and prompt versions, supplied evidence, cited IDs, factual errors, unsupported recommendations, latency, and operator assessment. Keep these outcomes distinct from mocked contract results.

Official interface references: https://docs.ollama.com/api/chat and https://docs.ollama.com/capabilities/structured-outputs.

## Recorded local runs

`docs/evidence/local-ai-allocation.json` records a real qwen2.5:3b response for a quantity mismatch. The first-pass capture is retained separately because it discussed funding before affirmation; stage-specific evidence in prompt v2 addresses that observation. The revised output still contains speculative causal language and requires operator review. These are a few examples, not an accuracy claim.

Run `PYTHONPATH=src python3 scripts/evaluate_local_ai.py` for opt-in live cash/inventory examples. Run the browser journey with `SETTLEMENTLAB_TEST_LOCAL_AI=1` to include an actual local-model request and capture `artifacts/local-ai.png`. Default CI never requires Ollama.
