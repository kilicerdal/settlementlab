"""Measure indexed investigation latency with unrelated statement history."""

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

from settlementlab.application.investigation import Investigation
from settlementlab.application.reconciliation import Reconciliation
from settlementlab.assurance.durable_data import CHECKER, approved_trade
from settlementlab.assurance.incident_export import provenance
from settlementlab.bootstrap import create_application
from settlementlab.configuration import Settings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--statements", type=int, default=1000)
    parser.add_argument("--reads", type=int, default=20)
    parser.add_argument("--output", default="artifacts/v44-investigation")
    args = parser.parse_args(argv)
    if not 0 <= args.statements <= 5000 or not 2 <= args.reads <= 100:
        parser.error("Use 0–5000 unrelated statements and 2–100 reads")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        app = create_application(
            Settings(
                database=str(Path(directory) / "bench.db"), model="", business_date="2026-11-09"
            )
        )
        recon = Reconciliation(app.service)
        for i in range(args.statements):
            recon.import_statement(
                [dict(trade_id="EXTERNAL-" + str(i), quantity=1, amount_cents=100)],
                "history-" + str(i),
                CHECKER,
            )
        trade = approved_trade(app.service, "indexed-target")
        trade = app.service.command(
            trade["id"],
            "settle-partial",
            dict(version=trade["version"], quantity=40, request_key="benchmark"),
            principal=CHECKER,
        )
        statement = recon.import_statement(
            [dict(trade_id=trade["id"], quantity=40, amount_cents=171000)], "target", CHECKER
        )
        durations = []
        for _ in range(args.reads):
            started = time.perf_counter()
            graph = Investigation(app.service).snapshot(trade["id"])
            durations.append(time.perf_counter() - started)
            assert [s["id"] for s in graph["records"]["statements"]] == [statement["id"]]
        with app.service.store.read_transaction() as repo:
            plan = [
                tuple(r)
                for r in repo.db.execute(
                    "EXPLAIN QUERY PLAN SELECT s.* FROM statement_membership m JOIN recon_statements s ON s.id=m.statement_id WHERE m.trade_id=? ORDER BY s.created_at,s.id LIMIT 5001",
                    (trade["id"],),
                )
            ]
        ordered = sorted(durations)
        report = dict(
            status="passed",
            unrelated_statements=args.statements,
            matched_statements=1,
            reads=args.reads,
            median_seconds=statistics.median(durations),
            p95_seconds=ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
            query_plan=plan,
            source=provenance(),
            scope="One local sample; indexed statement retrieval still includes global financial control reads. No production latency or scaling SLA.",
        )
        (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
