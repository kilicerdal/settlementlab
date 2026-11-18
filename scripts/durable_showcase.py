"""Real local worker crashes, recovery, redelivery and reviewed exception recovery."""

import argparse
import hashlib
import html
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from settlementlab.assurance.durable_data import CHECKER, approved_trade, entry, fund_trade
from settlementlab.bootstrap import create_application
from settlementlab.configuration import Settings


def worker_once(database, mode="both", fault=None, lease=30):
    root = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        "-m",
        "settlementlab.worker",
        "--db",
        str(database),
        "--business-date",
        "2026-11-09",
        "--once",
        "--mode",
        mode,
        "--lease",
        str(lease),
    ]
    if fault:
        command.extend(["--fault", fault])
    result = subprocess.run(
        command,
        cwd=root,
        env=dict(os.environ, PYTHONPATH=str(root / "src")),
        capture_output=True,
        text=True,
        timeout=15,
    )
    expected = 73 if fault else 0
    if result.returncode != expected:
        raise RuntimeError("Worker result differed from expected checkpoint: " + result.stderr)
    return dict(
        exit=result.returncode,
        mode=mode,
        fault=fault,
        output=[json.loads(line) for line in result.stdout.splitlines() if line.strip()],
    )


def await_lease(until):
    deadline = time.monotonic() + 10
    while time.time() <= until:
        if time.monotonic() > deadline:
            raise RuntimeError("Owned test lease failed to expire")
        time.sleep(0.02)


def capture(directory):
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    stages = []
    commands = []
    with tempfile.TemporaryDirectory(prefix="durable-showcase-") as temporary:
        database = Path(temporary) / "demo.db"
        app = create_application(
            Settings(database=str(database), model="", business_date="2026-11-09")
        )
        trades = [approved_trade(app.service, "batch-trade-" + str(i)) for i in range(3)]
        before = app.service.snapshot()
        batch = app.operations.enqueue_batch(
            [entry(t) for t in trades], "batch-acceptance", CHECKER
        )
        stages.append(
            dict(title="Accepted batch / no financial posting", snapshot=app.operations.snapshot())
        )
        commands.append(worker_once(database, "process", "before-commit", 1))
        snap = app.operations.snapshot()
        leased = next(job for job in snap["jobs"] if job["status"] == "RUNNING")
        if app.service.snapshot() != before or snap["receipts"] or snap["outbox"]:
            raise RuntimeError("Crash leaked partial financial work")
        stages.append(
            dict(title="Worker exited before commit / financial state unchanged", snapshot=snap)
        )
        await_lease(leased["lease_until"])
        for _ in range(3):
            commands.append(worker_once(database, "process"))
        snap = app.operations.snapshot()
        if (
            snap["totals"].get("SUCCEEDED") != 3
            or snap["receipts"] != 3
            or len(snap["outbox"]) != 3
        ):
            raise RuntimeError("Recovery did not account for every accepted trade")
        stages.append(dict(title="New workers completed all three settlements once", snapshot=snap))
        financial = app.service.snapshot()
        commands.append(worker_once(database, "deliver", "after-consume", 1))
        snap = app.operations.snapshot()
        if snap["inbox_count"] != 1:
            raise RuntimeError("Observer receipt did not survive acknowledgement loss")
        stages.append(
            dict(
                title="Observer committed / publisher exited before acknowledgement", snapshot=snap
            )
        )
        event = next(event for event in snap["outbox"] if event["status"] == "LEASED")
        await_lease(event["lease_until"])
        for _ in range(3):
            commands.append(worker_once(database, "deliver"))
        duplicate = app.operations.redeliver(event["event_id"], CHECKER)
        if duplicate["applied"] or app.service.snapshot() != financial:
            raise RuntimeError(
                "Redelivery changed financial state or duplicated observer application"
            )
        stages.append(
            dict(
                title="Redelivery ignored through durable inbox receipt",
                snapshot=app.operations.snapshot(),
            )
        )
        fourth = approved_trade(app.service, "review-needed", False)
        app.operations.enqueue_batch([entry(fourth)], "exception-command", CHECKER)
        commands.append(worker_once(database, "process"))
        dead = next(
            job for job in app.operations.snapshot()["jobs"] if job["status"] == "DEAD_LETTER"
        )
        stages.append(
            dict(
                title="Insufficient capacity preserved in exception queue",
                snapshot=app.operations.snapshot(),
            )
        )
        current = next(t for t in app.service.snapshot()["trades"] if t["id"] == fourth["id"])
        fund_trade(app.service, current, "reviewed-funding")
        app.operations.requeue(
            dead["id"], current["version"], "Reviewed after explicit synthetic funding", CHECKER
        )
        commands.append(worker_once(database, "process"))
        for _ in range(2):
            commands.append(worker_once(database, "deliver"))
        final = app.operations.snapshot()
        finance = app.service.snapshot()
        statement = [
            dict(trade_id=t["id"], quantity=100, amount_cents=427500) for t in finance["trades"]
        ]
        reconciled = app.service.reconcile(statement)
        with app.service.store.connection() as db:
            settlement_lines = db.execute(
                "SELECT COUNT(*) FROM journal_lines l JOIN journal_batches b ON b.id=l.batch_id WHERE b.kind='DVP_SETTLEMENT'"
            ).fetchone()[0]
        checks = dict(
            all_four_trades_settled=all(t["state"] == "SETTLED" for t in finance["trades"]),
            one_receipt_per_execution_generation=final["receipts"] == 5,
            observer_applied_five_unique_events=final["inbox_count"] == 5,
            exactly_four_financial_settlements=len(statement) == 4 and settlement_lines == 16,
            all_events_delivered=final["outbox_totals"] == {"DELIVERED": 5},
            ledger_balanced=finance["treasury"]["controls"]["status"] == "BALANCED",
            statement_balanced=reconciled["status"] == "BALANCED",
        )
        if not all(checks.values()):
            raise RuntimeError("Final durable controls failed: " + str(checks))
        stages.append(
            dict(title="Reviewed generation 2 recovered / four trades reconcile", snapshot=final)
        )
    root = Path(__file__).resolve().parents[1]
    report = dict(
        version=1,
        generated_at=datetime.now(timezone.utc).isoformat(),
        scope="Owned local Python processes and SQLite; not distributed exactly-once processing",
        source_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        source_dirty=bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip()
        ),
        checks=checks,
        commands=commands,
        batch_id=batch["id"],
        stages=stages,
    )
    (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    cards = "".join(
        '<article id="stage-'
        + str(i)
        + '"><p>0'
        + str(i)
        + "</p><h2>"
        + html.escape(stage["title"])
        + "</h2><details><summary>Inspect recorded state and correlated timeline</summary><pre>"
        + html.escape(json.dumps(stage["snapshot"], indent=2))
        + "</pre></details></article>"
        for i, stage in enumerate(stages, 1)
    )
    page = (
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SettlementLab durable recovery</title><style>body{background:#09111c;color:#dce8ed;font:16px/1.7 system-ui;max-width:1100px;margin:60px auto;padding:0 24px}h1{font:52px/1.1 Georgia,serif;color:#a3dfca}article{border-top:1px solid #345;padding:28px 0}article>p,a{color:#a3dfca}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}summary{cursor:pointer}</style><main><p>SETTLEMENTLAB / RECORDED LOCAL RECOVERY</p><h1>Stop the worker.<br>Account for the work.</h1><p>This capture uses real process exits at named checkpoints. All final financial, queue, outbox and observer checks passed. It uses synthetic data, a simulated business date and no model calls.</p><p><a href="results.json">Full execution evidence and source state</a></p>'
        + cards
        + "<p>Explicitly reviewed requeue creates a new execution generation; it does not erase the failed attempt. The observer is a separate local read model sharing the same database, not an external broker or financial institution.</p></main></html>"
    )
    (output / "index.html").write_text(page)
    (output / "checksums.json").write_text(
        json.dumps(
            {
                name: hashlib.sha256((output / name).read_bytes()).hexdigest()
                for name in ["results.json", "index.html"]
            },
            indent=2,
        )
        + "\n"
    )
    print("Durable recovery showcase passed: " + str(output / "index.html"), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/durable-showcase")
    args = parser.parse_args()
    capture(args.output)


if __name__ == "__main__":
    main()
