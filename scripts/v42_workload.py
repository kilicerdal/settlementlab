"""Measure bounded local journal growth and concurrent partial settlement recovery."""

import argparse
import concurrent.futures
import json
import platform
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from settlementlab.application.operations import DurableOperations
from settlementlab.assurance.durable_data import CHECKER, approved_trade, entry
from settlementlab.assurance.slice_oracle import audit_slices
from settlementlab.bootstrap import create_application
from settlementlab.configuration import Settings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trades", type=int, default=300)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output", default="artifacts/v42/workload")
    args = parser.parse_args(argv)
    if not 1 <= args.trades <= 2000 or not 1 <= args.workers <= 8:
        parser.error("Use 1–2000 trades and 1–8 workers")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="settlementlab-load-") as directory:
        database = Path(directory) / "workload.db"
        app = create_application(
            Settings(database=str(database), model="", business_date="2026-11-09")
        )
        service, ops = app.service, DurableOperations(app.service)
        started = time.perf_counter()
        plans = {}
        for i in range(args.trades):
            trade = approved_trade(service, "load-" + str(i), quantity=100)
            plans[trade["id"]] = dict(
                buyer_id=trade["buyer_id"],
                seller_id=trade["seller_id"],
                symbol=trade["symbol"],
                quantity=100,
                price_cents=4275,
                revision=1,
                executed_quantity=40,
            )
            ops.enqueue_batch([dict(entry(trade), quantity=40)], "job-" + str(i), CHECKER)
        setup_seconds = time.perf_counter() - started

        # One real precommit rollback; recovery occurs through the same lease/retry protocol.
        def fault(phase):
            if phase == "before-commit":
                raise RuntimeError("workload rollback checkpoint")

        assert ops.process_one("fault-worker", fault=fault)["status"] == "RETRY_WAIT"
        durations = []
        retries = []
        claim_timeouts = []

        def drain(worker):
            while True:
                tick = time.perf_counter()
                try:
                    job = ops.process_one("worker-" + str(worker))
                except sqlite3.OperationalError as error:
                    if "locked" not in str(error).lower():
                        raise
                    claim_timeouts.append(str(worker))
                    time.sleep(0.05)
                    continue
                if job is None:
                    return
                if job["status"] == "RETRY_WAIT":
                    retries.append(job["id"])
                elif job["status"] != "SUCCEEDED":
                    raise AssertionError(job)
                else:
                    durations.append(time.perf_counter() - tick)
                time.sleep(0.001)

        started = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(drain, range(args.workers)))
        # Retry availability is actual elapsed queue time, separate from fixed business date.
        deadline = time.monotonic() + 15
        while ops.snapshot()["totals"].get("RETRY_WAIT", 0) and time.monotonic() < deadline:
            time.sleep(0.05)
            drain("recovery")
        elapsed = time.perf_counter() - started
        oracle = audit_slices(database, plans)
        assert oracle["status"] == "passed", oracle
        with sqlite3.connect(database) as db:
            counts = {
                table: db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                for table in (
                    "journal_batches",
                    "journal_lines",
                    "settlement_slices",
                    "ops_receipts",
                    "ops_outbox",
                )
            }
            assert (
                counts["settlement_slices"]
                == counts["ops_receipts"]
                == counts["ops_outbox"]
                == args.trades
            )
        sorted_durations = sorted(durations)
        report = dict(
            status="passed",
            generated_at=datetime.now(timezone.utc).isoformat(),
            python=platform.python_version(),
            sqlite=sqlite3.sqlite_version,
            trades=args.trades,
            workers=args.workers,
            setup_seconds=setup_seconds,
            processing_seconds=elapsed,
            completed_jobs_per_second=args.trades / elapsed,
            p95_worker_call_seconds=sorted_durations[
                min(len(sorted_durations) - 1, int(len(sorted_durations) * 0.95))
            ],
            database_bytes=database.stat().st_size,
            rows=counts,
            oracle=oracle,
            recovered_precommit_failure=True,
            contention_retry_events=len(retries),
            claim_lock_timeouts=len(claim_timeouts),
            scope="Single-machine SQLite serialized writers; measured sample only, not a production SLA or distributed scale claim",
        )
        (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
