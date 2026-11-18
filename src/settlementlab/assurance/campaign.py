"""Bounded synthetic business-day campaign with independent expectations and real workers."""

import concurrent.futures
import random
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from threading import Event

from ..bootstrap import create_application
from ..configuration import Settings
from ..infrastructure.backup import backup
from .durable_data import CHECKER, approved_trade, entry, fund_trade
from .oracle import audit


def application(database):
    return create_application(
        Settings(database=str(database), model="", business_date="2026-11-09")
    )


def planned_trade(app, key, rng, funded=True, symbol="NOVA", correction=False):
    quantity, cents = rng.randint(1, 500), rng.randint(1, 20000)
    side = rng.choice(["BUY", "SELL"])
    expected = dict(
        quantity=quantity,
        price_cents=cents,
        symbol=symbol,
        buyer_id="SYN-ALPHA" if side == "BUY" else "SYN-BROKER",
        seller_id="SYN-BROKER" if side == "BUY" else "SYN-ALPHA",
    )
    trade = approved_trade(
        app.service,
        key,
        funded=funded,
        quantity=quantity,
        price=f"{cents // 100}.{cents % 100:02}",
        side=side,
        symbol=symbol,
        initial_manager_price=f"{(cents + 1) // 100}.{(cents + 1) % 100:02}"
        if correction
        else None,
    )
    return trade, expected


def queue(app, trades, prefix):
    for offset in range(0, len(trades), 50):
        app.operations.enqueue_batch(
            [entry(t) for t in trades[offset : offset + 50]], prefix + str(offset), CHECKER
        )


def drain(database, workers=4, mode="process", timeout=90):
    """Run only owned child workers; always stop/reap them, never an existing server."""
    started = time.perf_counter()
    processes = []
    with tempfile.TemporaryFile() as log:
        try:
            for index in range(workers):
                processes.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "settlementlab.worker",
                            "--db",
                            str(database),
                            "--business-date",
                            "2026-11-09",
                            "--mode",
                            mode,
                            "--worker-id",
                            mode + "-" + str(index),
                        ],
                        stdout=log,
                        stderr=log,
                    )
                )
            while True:
                if any(p.poll() is not None for p in processes):
                    log.seek(0)
                    raise RuntimeError(
                        "Owned worker exited unexpectedly: " + log.read().decode()[-1000:]
                    )
                with sqlite3.connect(
                    Path(database).resolve().as_uri() + "?mode=ro", uri=True
                ) as db:
                    if mode == "process":
                        remaining = db.execute(
                            "SELECT COUNT(*) FROM ops_jobs WHERE status IN ('READY','RUNNING','RETRY_WAIT')"
                        ).fetchone()[0]
                    else:
                        remaining = db.execute(
                            "SELECT COUNT(*) FROM ops_outbox WHERE status IN ('PENDING','LEASED')"
                        ).fetchone()[0]
                if remaining == 0:
                    break
                if time.perf_counter() - started > timeout:
                    raise TimeoutError("Campaign drain exceeded bounded timeout")
                time.sleep(0.02)
        finally:
            for p in processes:
                if p.poll() is None:
                    p.send_signal(signal.SIGINT)
            for p in processes:
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(timeout=5)
    return time.perf_counter() - started


def timing(database, elapsed, workers):
    with sqlite3.connect(database) as db:
        durations = sorted(
            r[0]
            for r in db.execute(
                "SELECT finished_at-started_at FROM ops_attempts WHERE status='SUCCEEDED'"
            )
        )
        completed = db.execute("SELECT COUNT(*) FROM ops_jobs WHERE status='SUCCEEDED'").fetchone()[
            0
        ]
        used = db.execute("SELECT COUNT(DISTINCT worker_id) FROM ops_attempts").fetchone()[0]

    def percentile(fraction):
        return (
            durations[min(len(durations) - 1, int((len(durations) - 1) * fraction))]
            if durations
            else None
        )

    return dict(
        workers_requested=workers,
        workers_with_claims=used,
        completed=completed,
        elapsed_seconds=elapsed,
        settlements_per_second=completed / elapsed,
        attempt_seconds=dict(
            p50=percentile(0.5), p95=percentile(0.95), maximum=max(durations, default=0)
        ),
        measurement="Wall time includes worker startup/shutdown; attempt time includes transaction work, not queue wait",
    )


def benchmark(directory, count=40, workers=4, seed=410):
    database = Path(directory) / ("benchmark-" + str(workers) + ".db")
    app = application(database)
    rng = random.Random(seed)
    planned = [planned_trade(app, "load-" + str(i), rng) for i in range(count)]
    trades = [t for t, _ in planned]
    accepted = {t["id"]: expected for t, expected in planned}
    queue(app, trades, "load-batch-")
    elapsed = drain(database, workers)
    result = audit(database, accepted)
    if result["status"] != "passed":
        raise AssertionError(result)
    return dict(financial_oracle=result, performance=timing(database, elapsed, workers), seed=seed)


def contention_probe(directory):
    database = Path(directory) / "contention.db"
    app = application(database)
    trade, expected = planned_trade(app, "contention", random.Random(410))
    queue(app, [trade], "contended-")
    entered = Event()

    def process():
        entered.set()
        return app.operations.process_one("blocked-worker")

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        with sqlite3.connect(database) as writer:
            writer.execute("BEGIN IMMEDIATE")
            future = pool.submit(process)
            if not entered.wait(5):
                raise RuntimeError("Contention worker did not start")
            try:
                future.result(timeout=0.05)
                raise AssertionError("Worker bypassed the held writer transaction")
            except concurrent.futures.TimeoutError:
                pass
            writer.commit()
        if future.result(timeout=15)["status"] != "SUCCEEDED":
            raise AssertionError("Contended worker did not recover")
    oracle = audit(database, {trade["id"]: expected})
    if oracle["status"] != "passed":
        raise AssertionError(oracle)
    return dict(
        status="passed",
        held_writer_seconds_at_least=0.05,
        completion_seconds=time.perf_counter() - started,
        oracle=oracle,
        scope="Controlled writer lock, one waiting worker, no production contention SLA",
    )


def business_day(directory, count=240, seed=410):
    if not 8 <= count <= 1000:
        raise ValueError("Business day requires 8–1000 trades")
    root = Path(directory)
    database = root / "business-day.db"
    app = application(database)
    rng = random.Random(seed)
    funded = count * 3 // 4
    planned = [
        planned_trade(app, "day-" + str(i), rng, correction=i % 10 == 0) for i in range(funded)
    ]
    trades = [t for t, _ in planned]
    accepted = {t["id"]: expected for t, expected in planned}
    corrections = sum(len(t["submission_history"]) == 2 for t in trades)
    if corrections != len(range(0, funded, 10)):
        raise AssertionError("Planned price corrections were not retained")
    queue(app, trades, "opening-")
    # Snapshot while work is pending; independent restored database must recover identically.
    restored = root / "restored.db"
    saved = backup(database, restored)
    elapsed = drain(database)
    opening_metrics = timing(database, elapsed, 4)
    application(restored)
    restore_start = time.perf_counter()
    drain(restored, workers=2)
    restored_oracle = audit(restored, accepted)
    if restored_oracle["status"] != "passed":
        raise AssertionError(restored_oracle)
    recovery_seconds = time.perf_counter() - restore_start
    # Novel symbols guarantee securities shortages despite cash recycling in the opening book.
    planned_late = [
        planned_trade(app, "late-" + str(i), rng, funded=False, symbol="LATE" + str(i))
        for i in range(count - funded)
    ]
    late = [t for t, _ in planned_late]
    accepted.update({t["id"]: expected for t, expected in planned_late})
    queue(app, late, "late-")
    drain(database)
    with sqlite3.connect(database) as db:
        failed = db.execute(
            "SELECT id,trade_id FROM ops_jobs WHERE status='DEAD_LETTER'"
        ).fetchall()
    if len(failed) != len(late):
        raise AssertionError("Shortage population differed from independent campaign plan")
    current = {t["id"]: t for t in app.service.snapshot()["trades"]}
    for job, trade_id in failed:
        fund_trade(app.service, current[trade_id], "reviewed-" + trade_id)
        app.operations.requeue(
            job,
            current[trade_id]["version"],
            "Reviewed synthetic late-day securities funding",
            CHECKER,
        )
    drain(database)
    drain(database, mode="deliver")
    oracle = audit(database, accepted, include_details=True)
    statement = [
        dict(trade_id=key, quantity=t["quantity"], amount_cents=t["quantity"] * t["price_cents"])
        for key, t in accepted.items()
    ]
    reconciliation = app.service.reconcile(statement)
    with sqlite3.connect(database) as db:
        exact = dict(
            trades=db.execute("SELECT COUNT(*) FROM trades").fetchone()[0],
            receipts=db.execute("SELECT COUNT(*) FROM ops_receipts").fetchone()[0],
            inbox=db.execute("SELECT COUNT(*) FROM ops_inbox").fetchone()[0],
            delivered=db.execute(
                "SELECT COUNT(*) FROM ops_outbox WHERE status='DELIVERED'"
            ).fetchone()[0],
            observer=db.execute("SELECT COUNT(*) FROM ops_projection").fetchone()[0],
        )
    if (
        oracle["status"] != "passed"
        or reconciliation["status"] != "BALANCED"
        or exact
        != dict(
            trades=count,
            receipts=count + len(late),
            inbox=count + len(late),
            delivered=count + len(late),
            observer=count,
        )
    ):
        raise AssertionError(dict(oracle=oracle, totals=exact, reconciliation=reconciliation))
    return dict(
        seed=seed,
        planned_trades=count,
        opening_trades=funded,
        price_corrections=corrections,
        shortages=len(late),
        reviewed_recoveries=len(failed),
        exact_totals=exact,
        financial_oracle=oracle,
        reconciliation=reconciliation["status"],
        opening_performance=opening_metrics,
        backup=dict(schema_version=saved["schema_version"], integrity=saved["integrity"]),
        restore=dict(recovery_seconds=recovery_seconds, oracle=restored_oracle),
        scope="Synthetic fixed business date, not a wall-clock market session; no production capacity claim",
    )
