# 002 — Separate replay identity from stale-write protection

Status: implemented; documented from the V3.0 code.

## Problem

A caller may retry a request after losing its response. Another caller may instead submit new terms based on an older trade version. Rejecting every old version would break legitimate replay; treating every similar payload as replay could hide a competing amendment.

## Decision

For manager submissions, scope the idempotency key to the trade and retain the normalized request fingerprint plus original response. An identical replay returns that response without a revision or audit append, even when the current trade has advanced. Reusing the key for different normalized content conflicts. A fresh key represents a new operation and requires the current trade version before creating a revision.

Implementation: [submit_manager in the workflow service](../../src/settlementlab/application/service.py), [repository operations](../../src/settlementlab/infrastructure/repository.py). See [API replay semantics](../API.md#replay-semantics) for the deliberately different response contracts of broker creation, instruction requests and funding.

## Alternatives and tradeoff

Version-only protection rejects duplicate writes but cannot reliably return a lost response. Key-only protection handles retries but cannot establish whether a new amendment used current terms. Storing both identities costs persistence space and requires explicit replay response contracts. A replay snapshot may be stale: use snapshot/readiness reads when the question is current state.

## Reproducible evidence

[Matching tests](../../tests/integration/test_matching.py):

- `test_replay_returns_original_result_even_after_correction`: the old response replays while current state stays corrected; changed content under that key is rejected.
- `test_concurrent_same_key_is_one_revision`: concurrent retries produce one stored revision.
- `test_concurrent_distinct_revisions_reject_stale_writer`: independent keys racing from one version yield one success and one 409.

```sh
PYTHONPATH=src python -m unittest tests.integration.test_matching -v
```

The independent collateral API has its own implementation of reservation replay. [C02](../../src/settlementlab/assurance/catalog/C02.json) checks its response contract through generic HTTP steps; the controlled faulty variant returns 201 instead of replaying with 200. This proves observed detection against that example, not arbitrary-service correctness.

## Limits

Not every lifecycle command accepts an idempotency key. Legacy commands retain their version/state guards. This is not a universal exactly-once claim; external asynchronous delivery, key retention and cross-service recovery need their own contracts.
