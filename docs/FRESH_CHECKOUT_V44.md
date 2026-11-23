# V4.4 fresh-checkout rehearsal

Rehearsed on macOS on 2026-11-22 against released commit `6050a91284ad42dbb17c6be0d5e122a4ab682b18` (`v4.4.0`). This is an automated fresh-user rehearsal, not outside human review.

## Passed path

Python **3.13.18**, SQLite **3.54.1**. The harness exported tracked source to a new temporary directory, created a virtual environment **without pip**, removed inherited `PYTHONPATH`/`PYTHONHOME` and disabled user-site packages. Before running, it checked that `settlementlab`, `playwright` and `pip` could not be imported.

- `python scripts/incident_quickstart.py --no-serve --output artifacts/first-run` exited 0 and created unresolved/resolved incident ZIPs and a results file.
- The regular serving quickstart, using a different fresh output directory, served `/investigation` and `/api/health` with HTTP 200 on port 8086.
- The harness stopped its child server and removed its temporary checkout. No model, API key, package installation or preexisting database was used.

The quickstart internally runs a real worker interruption and verifies the resolved export. It also generates an existing deliberately defective local exercise fixture; this is not a request for human review.

## Retained failed attempt

The first attempt used this Mac's system **Python 3.9.6 / SQLite 3.54.0**. It failed before seeding with `sqlite3.OperationalError: unable to open database file` while querying a read-only WAL connection. A minimal standalone SQLite reproduction also failed. The working 3.13 runtime passed. This does not establish that all Python 3.9 installations fail; the release CI tests Python 3.9 on Linux.

The README now recommends the rehearsed 3.13 path and explains the difference between the completed-incident quickstart and the empty workbench. The application transaction design and website are unchanged. We have not resolved the system SQLite build's failure; use the tested runtime if you encounter it. Do not bypass the issue by making investigation connections writable or disabling WAL snapshot controls.

## Reproduce the rehearsal

From a tracked checkout, use a Python 3.13 interpreter:

```sh
python3.13 -m scripts.rehearse_fresh_checkout --revision v4.4.0
# Optional: choose an exact interpreter, revision and unused output directory.
python3.13 -m scripts.rehearse_fresh_checkout --python python3.13 --revision HEAD --output artifacts/fresh-checkout-head
```

Port 8086 must be free. The harness fails instead of stopping an existing service. Output directories must be new. `rehearsal.json` records the exact tested commit, checks and hashes; `quickstart.log`, `server.log` and `incident-results.json` retain observations. The local failed attempt is retained under `artifacts/v44-fresh-release/quickstart.log`; it is not counted as a pass. CI retains a new rehearsal under the `browser-evidence` artifact, not the original local failure.

This exercises the source quickstart and actual HTTP startup. It does not emulate a human, test every platform, test pip installation from the internet or run the full regression suite. The release's standalone-wheel installation and broader controls are documented separately.
