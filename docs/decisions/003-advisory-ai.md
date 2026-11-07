# 003 — Give AI bounded evidence and no mutation interface

Status: implemented; documented from the V3.0 code.

## Problem

An operator may need help interpreting several matching or capacity findings. A model can produce a plausible but incorrect explanation, invent an evidence reference, or follow untrusted text. Allowing that model to approve or settle would turn an advisory error into a financial state change.

## Decision

Construct a bounded, stage-specific evidence envelope on the server. Exclude free-form account names, actors and request keys. Send it to loopback Ollama and require a structured response containing summary, likely cause, next step, uncertainty and supplied evidence IDs. Reject invalid structure, missing/unknown citations and incomplete output. Supply no mutation tools. Identify the analyzed trade version and keep command authority with the application and operator.

Implementation: [evidence shaping](../../src/settlementlab/core/evidence.py), [local AI adapter](../../src/settlementlab/adapters/ai.py), [HTTP inference boundary](../../src/settlementlab/adapters/http.py). Setup and recorded evaluation scope: [AI guide](../AI.md).

## Alternatives and tradeoff

A fixed rule explanation is cheaper and deterministic but less flexible for investigation. Sending the entire trade snapshot gives a model more context but exposes unnecessary fields. Autonomous remediation would require a separate policy/approval design and stronger evaluation; it is outside this project. Local inference avoids paid API requirements, but consumes the operator's compute and depends on an installed model.

## Reproducible evidence

[AI contract tests](../../tests/unit/test_ai.py) verify that the request declares no tools, private free-form values are excluded, unknown citations fail, missing configuration never calls the provider and extra output fields are rejected. These use injected responses.

[HTTP tests](../../tests/api/test_http.py), `test_disabled_ai_and_stale_analysis_do_not_mutate_trade`, verify errors leave the trade unchanged.

```sh
PYTHONPATH=src python -m unittest tests.unit.test_ai tests.api.test_http -v
```

## Limits

Schema validity and reference identity do not establish factual accuracy. A cited explanation can still be wrong. Historical live-model examples retain failed review outcomes and are not an accuracy benchmark. Concurrent changes can make analysis stale. The recorded walkthrough makes no live-model request.
