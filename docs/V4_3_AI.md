# Incident investigator: evaluation and limits

The optional investigator uses an already installed local Ollama model. There is no paid provider, model download, action tool or automatic financial decision. The incident UI, deterministic controls and exports work with AI disabled.

## Offline contract evaluation

```sh
python -m settlementlab.assurance.investigator_evaluation
```

The committed corpus declares supported incident observations, correct abstention, unsupported claim codes, invented or misattributed citations, unsafe financial instructions, false certainty, duplicate claims and malformed booleans. Its responses and expected labels are synthetic developer fixtures, not independently reviewed model answers.

The report measures false acceptance of negative fixtures and correct acceptance/rejection for insufficient-evidence cases. Passing means the validator and declared rubric detect these specific cases. It does not measure general model accuracy, exhaustive prompt-injection resistance or external human agreement.

To enable the UI with an already installed model, run `python3 scripts/incident_quickstart.py --model qwen2.5:3b`, select the checker demo identity and explicitly request analysis. The default quick start keeps AI disabled.

## Actual free local-model sampling

```sh
python -m settlementlab.assurance.investigator_evaluation \
  --live-model qwen2.5:3b --output artifacts/v43-ai-live
```

Sampling uses the fixed loopback transport, a bounded response, two selected synthetic contexts and no records from a running financial database. Unavailable/invalid samples remain explicit and do not become fabricated model metrics. Sampling never installs a model.

On November 19, 2026, an existing local `qwen2.5:3b` model produced two recorded responses in each of two development samples. The initial prompt accepted both responses structurally, but the model abstained on both the supported-observation context and empty context: expected abstention behavior matched 1/2 cases. After clarifying that reporting an observation does not require knowing its underlying cause, the model cited the recorded observation and abstained on the empty context: both responses passed the declared checks and matched expected abstention behavior in that two-case sample.

[Retained actual responses](examples/incident-ai-local-sample.json) include both outcomes. This is prompt-development evidence, not a statistically meaningful benchmark or a guarantee that another run will behave identically.

## Authority and data boundary

The investigator receives observation codes, short fixed descriptions and their exact evidence IDs. It does not receive raw imported statement payloads, participant account identities, operator review reasons, arbitrary audit prose or request credentials. Requests are read-only; the analyzed trade version remains visible and may become stale during inference.

Citation checks establish only that a declared claim points to an allowed observation. They do not verify unrestricted prose, prove root cause or establish counterparty authenticity. Unknown cause must remain explicit. The deterministic financial application, checker review and independently retained numerical evidence remain authoritative.
