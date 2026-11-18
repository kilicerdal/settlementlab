# 004 — Durable work, atomic financial effect and at-least-once observation

Status: implemented on the V4 development branch; not a released production guarantee.

## Problem

A caller can accept work while no worker is running. A worker can stop after claiming, during posting, after committing financial state or after committing an observer receipt but before acknowledging publication. Retrying the wrong boundary can lose work or repeat an effect.

## Decision

Persist batch acceptance separately from worker execution. Give each claim a bounded lease and token. Apply the existing settlement policy under one transaction that also records its receipt, terminal job state and outbox event. Deliver outbox events through a separately committed idempotent inbox/projection and then acknowledge publication. Expose exhausted work for explicit operator review, preserving earlier generations.

Implementation: [orchestration](../../src/settlementlab/application/operations.py), [financial transaction helper](../../src/settlementlab/application/service.py), [SQLite queue/outbox](../../src/settlementlab/infrastructure/operations_repository.py), [worker CLI](../../src/settlementlab/worker.py).

## Alternatives and consequences

An in-memory queue cannot account for acknowledged work after restart. Writing financial state and sending an event in separate uncoordinated steps exposes a lost-notification gap. The transactional outbox preserves the outgoing record with the financial transition, but a publisher can still redeliver after an uncertain acknowledgement. The observer therefore stores a unique event receipt. Calling this universal exactly-once execution would overstate the guarantee.

SQLite write serialization keeps the local correctness boundary inspectable and limits concurrency. The local observer shares its database authority; adopting an external broker or another database requires a separately verified transport/consumer implementation. Bounded retries avoid silent infinite loops; blocked work needs a human-supplied reason and appropriate current trade version.

## Evidence

- [Durable integration controls](../../tests/integration/test_durable_operations.py): financial/outbox rollback, fenced claims, retry exhaustion, reviewed generation changes and ordered/deduplicated observation.
- [Real process crash controls](../../tests/integration/test_durable_processes.py): process exits at all six checkpoints, new worker recovery and unchanged financial state on redelivery.
- [HTTP controls](../../tests/api/test_durable_api.py): checker/auditor restrictions, request identity and omitted lease tokens.
- [Browser journey](../../tests/browser/durable_smoke.py): actual console, crashes, restart, lost acknowledgement, deduplication and reviewed capacity recovery.

[Commands and exact boundaries](../DURABLE_OPERATIONS.md).
