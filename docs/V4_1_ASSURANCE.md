# V4.1 — independent financial assurance

V4.1 extends the V4.0 simulator with independent financial assurance. It adds reproducible engineering evidence rather than claims about production systems. No portfolio website or deployment configuration changes are included.

## Review in one command

From the source checkout, with Python 3.9 or newer:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install . -r requirements-quality.txt
.venv/bin/python -m scripts.reviewer_ready --quality
# Open artifacts/reviewer-ready/index.html
.venv/bin/python -m scripts.reviewer_ready --verify
```

The command runs lint, formatting, strict typing, the complete deterministic suite and coverage, then two worker workloads, a writer-contention probe, a 240-trade business day, backup recovery, independent-service positive/negative scenarios, and offline AI evaluations. It writes HTML, JSON, source/environment provenance, logs, and a SHA-256 manifest. A failing stage produces a failed scorecard and nonzero exit; inspect the named log. Expected negative scenarios intentionally have failed reports: the surrounding check requires the declared defect, not any arbitrary failure.

No browser or model installation is required by this command. CI separately runs desktop/mobile browser journeys. `--trades 8` shortens the day for development; valid counts are 8–1000. `--quality` requires the pinned development dependencies; without it the control suite still runs, while coverage is explicitly unmeasured. Run from the checkout: the orchestration script and independent example service are source-only. Installed financial, worker, backup and AI-review commands live in the wheel.

## Independent financial oracle

[oracle.py](../src/settlementlab/assurance/oracle.py) imports no settlement, posting, matching or reconciliation implementation. Its expected DVP movements derive from a separately retained input plan: quantity, integer price cents, symbol, and independently assigned buyer/seller from BUY/SELL terms. Only the generated trade identifier comes from the application.

The scorecard retains all expected/observed economic comparisons in `economic-oracle.json`. It opens the database read-only in one consistent snapshot, reads the full journal rather than the console's limited history, and checks:

- Exactly one four-leg DVP batch per expected settled trade, with exact participant/asset/amount multiplicities.
- Settlement quantity/notional against retained terms, and completeness across settled trades, journals and receipts.
- Separate asset conservation, materialized balance projection and nonnegative trading balances.
- An approved request with a different maker/checker and a decision timestamp preceding settlement.

A mutation test deliberately changes both cash legs while keeping the journal balanced and balance projections consistent. The economic oracle rejects it. Funding authorization is outside this oracle: funding conservation/projection is checked, while funding permissions are exercised separately. The oracle is limited to this lab's shared-ledger USD equities and schema, not a general market accounting standard.

## Generated properties and sequences

A reproducible seed (`410`) generates 2,000 conservation cases and 2,000 deliberately unbalanced mutations. Seeds 0–23 generate financial lifecycle sequences with unapproved-settlement rejection, shortages, explicit funding, funding replay, batch replay, expired claims, stale-token fencing, precommit rollback, reviewed requeue, and duplicate observer delivery. Assertions verify no repeated financial effects and compare the final database with independent terms.

These are bounded property/state-machine checks implemented with the standard library. Failing subtests include seed/case identity. They are not exhaustive proofs and do not perform automatic shrinking. Existing tests retain six actual process-termination checkpoints.

## Synthetic business day

Default seed 410 creates 240 varied-size/price BUY/SELL trades on a fixed simulated business date:

1. 180 funded opening trades, including 18 manager price breaks corrected through separate submission revisions.
2. Real worker processes settle the opening queue. A pending-work backup is restored to a separate database and independently drained and verified.
3. 60 late trades have novel security symbols and no securities funding, guaranteeing real shortages despite cash recycling.
4. Each failed job requires explicit synthetic funding, checker review, current version and a reason before generation 2.
5. Observer workers deliver all events in order. End-of-day reconciliation uses a statement constructed from retained input terms.

The expected final totals are 240 settled trades, 300 execution receipts, 300 delivered events, 300 inbox entries and 240 latest observer views. Failed attempts remain in history. All 240 economic transfers are independently checked; dashboard history truncation cannot hide older errors. This simulates business transitions, not a wall-clock trading session, exchange protocol or regulatory report.

## Measured concurrency and recovery

The scorecard records one-worker and four-worker runs over identical seeded 40-trade inputs. It includes Python/SQLite/OS/CPU provenance, workers started versus workers that actually claimed work, completed trades, wall time, throughput, and p50/p95/max attempt durations. Wall time includes worker startup/shutdown; attempt time starts at the persisted claim timestamp and includes execution/lock wait, but excludes queue age. Quantiles select the lower indexed value in the sorted observations.

One sample per workload is descriptive, not a statistical benchmark or SLA. SQLite serializes writes; more workers may be slower. A separate probe holds a writer transaction for at least 50 ms, confirms the worker waits, releases it, and independently verifies the resulting settlement. No existing server or unrelated process is stopped; only owned child workers are signalled and reaped, including on failure.

Recovery timing covers opening-work drain from an online backup, not total service restoration/RTO certification. Tests additionally snapshot while another connection holds uncommitted changes, recover an abandoned lease in a new application instance, migrate a populated financial schema 4 database to schema 5, and retain future-schema refusal and migration-rollback controls.

## Backup and restore

```sh
settlementlab-backup --source /path/to/lab.db --destination /path/to/new-backup.db
```

The SQLite online-backup API copies committed state to an exclusively created destination (mode 0600), verifies integrity/foreign keys, and returns the schema version and SHA-256. Existing destinations, symlinks, missing sources and source=destination are rejected. Failed copies are removed. Store backups outside the Git repository.

For a manual restore, stop all server/worker processes for the destination, keep the current database as a separate backup, and restore into a **new** database path. Start the compatible application against that path with the same business-date policy. In-flight leases remain owned until expiry; do not reset financial receipts or replay journal SQL. The automated drill exercises this new-path recovery. Schema remains 5; this version introduces no schema migration. Never point older code at a newer unsupported schema.

## Security boundaries

See [the concrete security review](SECURITY_REVIEW_V4_1.md). Loopback Host validation mitigates browser DNS rebinding for this local-only server. Cross-origin writes, forged cookies/roles, oversized bodies, duplicate JSON fields, nonfinite numbers, invalid review fields, and static traversal attempts have mutation-preservation checks. Lease tokens are excluded from HTTP operations responses. HTML evidence escapes untrusted text; the console uses text nodes.

This is an executable boundary review, not a penetration-test certification. Demo personas are freely switchable and reads are public on the local server. Do not expose it to the internet or insert real records; production identity, TLS, deployment isolation and external secret handling are separate engineering work.

## AI evaluation and extension

[AI review](AI_REVIEW_V4_1.md) retains four real historical local-model outputs and five prior synthetic controls, then adds seven adversarial fixtures covering citations, unwarranted certainty, automatic/imperative approval and instruction injection. Rejected answers remain visible. Optional live sampling uses only an already installed loopback Ollama model and has no action tools. Offline agreement with annotated criteria is never represented as model accuracy.

[Second-service tutorial](SECOND_SERVICE_TUTORIAL.md) demonstrates the same installed HTTP runner against a separate collateral reservation service, including a positive contract and a specific injected replay defect, with no framework-core changes.
