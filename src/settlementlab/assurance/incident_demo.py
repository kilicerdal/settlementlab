"""Seed a replayable incident with real child-worker interruption and retained evidence."""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from ..application.investigation import Investigation
from ..application.reconciliation import Reconciliation
from ..bootstrap import create_application
from ..configuration import Settings
from .durable_data import CHECKER, MAKER, approved_trade, entry
from .incident_export import export, verify


def current(service, trade_id):
    with service.store.transaction() as repository:
        return service.get(repository, trade_id)


def seed(app, output, crash=True):
    service, ops = app.service, app.operations
    if service.snapshot()["trades"]:
        raise ValueError("Incident replay requires a fresh empty synthetic database")
    trade = approved_trade(service, "incident-43", quantity=100)
    ops.enqueue_batch([dict(entry(trade), quantity=40)], "incident-first", CHECKER)
    fault_returncode = None
    if crash:
        env = dict(os.environ)
        source = Path(__file__).resolve().parents[2]
        if (source / "settlementlab").is_dir():
            env["PYTHONPATH"] = str(source)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "settlementlab.worker",
                "--db",
                app.settings.database,
                "--business-date",
                "2026-11-09",
                "--worker-id",
                "interrupted-worker",
                "--lease",
                "0.1",
                "--mode",
                "process",
                "--once",
                "--fault",
                "after-claim",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        fault_returncode = result.returncode
        if result.returncode != 73:
            raise RuntimeError(
                "Expected actual worker checkpoint exit 73: " + result.stdout + result.stderr
            )
        (output / "worker-interruption.log").write_text(result.stdout + result.stderr)
        time.sleep(0.15)
    else:
        # Explicit test-only expired claim; report distinguishes this from a real process crash.
        claim = ops.claim("interrupted-fixture", 0.1)
        time.sleep(max(0, claim["lease_until"] - time.time()) + 0.01)
    recovered = ops.process_one("recovery-worker")
    if recovered["status"] != "SUCCEEDED":
        raise AssertionError(recovered)
    assert ops.deliver_one("observer")["status"] == "DELIVERED"
    trade = current(service, trade["id"])
    assert trade["settled_quantity"] == 40 and len(trade["execution_slices"]) == 1
    recon = Reconciliation(service)
    stale = recon.import_statement(
        [dict(trade_id=trade["id"], quantity=0, amount_cents=0)], "delayed-statement", CHECKER
    )
    wrong = recon.import_statement(
        [dict(trade_id=trade["id"], quantity=40, amount_cents=170999)],
        "discrepant-statement",
        CHECKER,
    )
    assert len(stale["cases"]) == len(wrong["cases"]) == 1
    (output / "investigate.zip").write_bytes(export(service, trade["id"]))
    corrected = recon.import_statement(
        [dict(trade_id=trade["id"], quantity=40, amount_cents=171000)],
        "corrected-statement",
        CHECKER,
    )
    for case in stale["cases"] + wrong["cases"]:
        recon.resolve(
            case["id"],
            corrected["id"],
            "Corrected independent statement confirms executed quantity and cents",
            CHECKER,
        )
    trade = current(service, trade["id"])
    requested = service.command(
        trade["id"],
        "request-reversal",
        dict(
            version=trade["version"],
            original_batch=trade["execution_slices"][0]["batch_id"],
            request_key="incident-correction",
            reason="Synthetic execution requires independently reviewed compensation",
        ),
        principal=MAKER,
    )
    trade = current(service, trade["id"])
    service.command(
        trade["id"],
        "approve-reversal",
        dict(
            version=trade["version"],
            reversal_id=requested["id"],
            reason="Reviewed original execution and exact compensating entries",
        ),
        principal=CHECKER,
    )
    final = current(service, trade["id"])
    assert (
        final["settled_quantity"],
        final["reversed_quantity"],
        final["net_settled_quantity"],
    ) == (40, 40, 0)
    # Earlier resolutions remain historical. A new net statement demonstrates post-correction accounting.
    net = recon.import_statement(
        [dict(trade_id=trade["id"], quantity=0, amount_cents=0)], "net-after-correction", CHECKER
    )
    assert not net["cases"]
    bundle = output / "resolved.zip"
    bundle.write_bytes(export(service, trade["id"]))
    verified = verify(bundle)
    graph = Investigation(service).snapshot(trade["id"])
    assert any(n["title"] == "LEASE_EXPIRED" for n in graph["timeline"])
    report = dict(
        status="passed",
        trade_id=trade["id"],
        state=final["state"],
        gross_quantity=40,
        reversed_quantity=40,
        net_quantity=0,
        original_execution_batches=1,
        compensating_batches=1,
        worker_checkpoint_exit=fault_returncode,
        crash_mode="real-child-process" if crash else "expired-test-fixture",
        timeline_events=len(graph["timeline"]),
        correlations=len(graph["correlations"]),
        export_verification=verified,
        phases=[
            "partial execution after interrupted worker",
            "delayed statement",
            "amount discrepancy",
            "corrected evidence resolution",
            "maker/checker compensation",
            "net statement verification",
        ],
    )
    (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/v43-incident")
    parser.add_argument(
        "--model",
        default="",
        help="Optional already installed local Ollama model; disabled by default",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Keep the seeded local investigation UI running on port 8086",
    )
    parser.add_argument(
        "--verify", type=Path, help="Verify an existing incident ZIP without running a service"
    )
    parser.add_argument(
        "--exercise",
        action="store_true",
        help="Also generate an isolated deliberately defective reviewer fixture",
    )
    args = parser.parse_args(argv)
    if args.verify:
        print(json.dumps(verify(args.verify), indent=2))
        return 0
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    database = output / "incident.db"
    if database.exists():
        parser.error(
            "Use a fresh output directory; existing incident evidence is never overwritten"
        )
    app = create_application(
        Settings(database=str(database), model=args.model, business_date="2026-11-09", port=8086)
    )
    report = seed(app, output)
    if args.exercise:
        from .correction_oracle import audit
        from .reviewer_exercise import build

        snapshot = Investigation(app.service).snapshot(report["trade_id"])
        trade = snapshot["trade"]
        original = trade["execution_slices"][0]["batch_id"]
        accepted = {
            original: dict(
                trade_id=trade["id"],
                buyer_id=trade["buyer_id"],
                seller_id=trade["seller_id"],
                symbol="NOVA",
                quantity=40,
                price_cents=4275,
            )
        }
        assert audit(database, accepted)["status"] == "passed"
        report["reviewer_exercise"] = build(database, output / "reviewer-exercise", accepted)
        (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(
        "Open investigate.zip for the unresolved incident; resolved.zip contains the recovery and correction."
    )
    if args.serve:
        from http.server import ThreadingHTTPServer

        from ..adapters.http import handler

        server = ThreadingHTTPServer(
            ("127.0.0.1", 8086), handler(app.service, app.triage, app.operations)
        )
        print("Investigation: http://127.0.0.1:8086/investigation", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
