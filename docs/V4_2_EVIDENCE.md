# V4.2 development validation

These are local candidate measurements. Reproduce them with the commands in [V4.2](V4_2.md) and inspect the CI artifacts tied to the pull-request commit. They are not production capacity or independent-human-review claims.

| Check | Observed local outcome |
| --- | --- |
| Full regression controls | 160 tests passed; scenario assurance passed |
| Coverage | Above the repository's 85% branch-inclusive gate |
| Source mutation campaign | 6 of 6 targeted mutants killed; no invalid mutants |
| Browser verification | Existing trade workbench, durable operations and new lifecycle flows passed |
| Mobile lifecycle | 390 px viewport; no page overflow or JavaScript errors |
| Genuine release compatibility | V4.1 schema 5 upgraded to schema 6 with unchanged financial rows; expired claim recovered once |
| Downgrade and restore | V4.1 refused schema 6 and opened the pre-upgrade schema 5 backup |
| Standalone wheel | Fresh environment without financial application; healthy second service passed and injected replay defect detected |
| External human review | Pending |

## Larger partial-execution sample

One local Python 3.13 / SQLite sample used 1,000 approved synthetic trades and four concurrent worker threads, explicit 40-of-100-unit slices, plus one precommit rollback. Each trade contributes two funding batches and one DVP slice batch.

- 1,000 verified execution slices, processing receipts and outbox events.
- 3,000 journal batches and 8,000 journal lines; database approximately 18.8 MB.
- Setup approximately 30.6 seconds; processing approximately 66.7 seconds.
- Approximately 15 completed jobs/second; successful worker-call p95 approximately 0.93 seconds.
- One claim lock timeout; campaign retried acquisition and recovered all obligations. No additional completed-job retries in that sample.
- Independent slice economics and cumulative receipts passed; no duplicate financial execution.

This is one machine, one sample, a serialized SQLite writer and a growing full-journal integrity check. It is not a scaling promise. The actual workload report records elapsed time, counts and contention; results will vary. `STORAGE_BUSY` is now explicit in the real worker CLI, including one-shot exit 75. A separate 300-trade development rehearsal also passed, but it used a different workload-driver revision and should not be compared as a throughput benchmark.

Artifacts are generated under `artifacts/v42/`; they are not committed as static passing proof. GitHub Actions uploads fresh evidence and the standalone wheel. The committed lifecycle screenshot is synthetic UI documentation.
