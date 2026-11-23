# V4.4 fresh-checkout rehearsal

Rehearsed on macOS on 2026-11-22 against released commit `6050a91284ad42dbb17c6be0d5e122a4ab682b18` (`v4.4.0`). This is an automated fresh-user rehearsal, not outside human review.

## Compatibility fix: verified before and after

Post-release source commit `1cfb1a883e34864ebcc45ae5cf1a9220e988f325` fixes cold-WAL startup. Fresh, pip-free checkouts now pass on the previously failing macOS **Python 3.9.6 / SQLite 3.54.0** and on **Python 3.13.18 / SQLite 3.54.1**. Both generate verified incident evidence and serve investigation/health endpoints with HTTP 200. The complete framework run on system Python passes **215 tests plus four assurance scenarios**. [Recorded before/after observations](evidence/sqlite-compatibility.json).

The initial `mode=ro` connection is still preferred. Only the specific cold-open failure triggers a query-only `mode=rw` helper for an existing WAL database. Reading its schema initializes SQLite-owned sidecars; it issues no DML or writer transaction. The consumer is reopened with physical `mode=ro` enforcement. All handles close deterministically. Investigations, backup and assurance readers share only this connection setup; economic expectations and oracle logic remain separate.

Regression controls cover a cold database, names requiring URI escaping, physical write rejection even after `query_only=OFF`, a writer committing during an unchanged snapshot, a subsequent reader seeing that commit, missing-source refusal and standalone backup cleanup. Linux CI also forces the initialization branch so it is exercised on SQLite builds that open cold WAL directly. No immutable mode, journal-mode downgrade or writable investigation fallback is used. See [SQLite's read-only WAL requirements](https://sqlite.org/wal.html#read_only_databases).

On the affected system build, WAL-to-DELETE backup conversion also left a disposable destination SHM. Backup now removes that destination SHM only after owned handles are closed, DELETE mode is verified and no WAL remains; source sidecars are untouched.

This is a source fix after V4.4.0, not a replacement of the released tag or wheels. For the original binaries, Python 3.13 remains the rehearsed workaround.

## Passed path

Python **3.13.18**, SQLite **3.54.1**. The harness exported tracked source to a new temporary directory, created a virtual environment **without pip**, removed inherited `PYTHONPATH`/`PYTHONHOME` and disabled user-site packages. Before running, it checked that `settlementlab`, `playwright` and `pip` could not be imported.

- `python scripts/incident_quickstart.py --no-serve --output artifacts/first-run` exited 0 and created unresolved/resolved incident ZIPs and a results file.
- The regular serving quickstart, using a different fresh output directory, served `/investigation` and `/api/health` with HTTP 200 on port 8086.
- The harness stopped its child server and removed its temporary checkout. No model, API key, package installation or preexisting database was used.

The quickstart internally runs a real worker interruption and verifies the resolved export. It also generates an existing deliberately defective local exercise fixture; this is not a request for human review.

## Retained failed attempt

The first attempt used this Mac's system **Python 3.9.6 / SQLite 3.54.0**. It failed before seeding with `sqlite3.OperationalError: unable to open database file` while querying a read-only WAL connection. A minimal standalone SQLite reproduction also failed. The working 3.13 runtime passed. This does not establish that all Python 3.9 installations fail; the release CI tests Python 3.9 on Linux.

This original failed attempt remains historical evidence. The source fix described above resolves the reproduced startup failure while retaining read-only snapshot enforcement. The completed-incident quickstart and empty workbench remain distinct. The website is unchanged.

## Reproduce the rehearsal

From a tracked checkout containing the fix, use Python 3.9+:

```sh
python3 -m scripts.rehearse_fresh_checkout --revision HEAD
# Optional: choose an exact interpreter, revision and unused output directory.
python3 -m scripts.rehearse_fresh_checkout --python python3.13 --revision HEAD --output artifacts/fresh-checkout-head
```

Port 8086 must be free. The harness fails instead of stopping an existing service. Output directories must be new. `rehearsal.json` records the exact tested commit, checks and hashes; `quickstart.log`, `server.log` and `incident-results.json` retain observations. The local failed attempt is retained under `artifacts/v44-fresh-release/quickstart.log`; it is not counted as a pass. CI retains a new rehearsal under the `browser-evidence` artifact, not the original local failure.

This exercises the source quickstart and actual HTTP startup. It does not emulate a human, test every platform, test pip installation from the internet or run the full regression suite. The release's standalone-wheel installation and broader controls are documented separately.
