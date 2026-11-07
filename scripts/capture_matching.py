"""Capture an independently submitted V2.1 trade; --ai opts into local inference."""

import argparse
import hashlib
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from settlementlab.ai import Triage
from settlementlab.domain import Ledger

parser = argparse.ArgumentParser()
parser.add_argument("--ai", action="store_true", help="Run the installed local model; no paid API")
args = parser.parse_args()
with tempfile.TemporaryDirectory() as temporary:
    ledger = Ledger(Path(temporary) / "matching.db")
    terms = dict(
        symbol="NOVA",
        side="BUY",
        currency="USD",
        quantity=10000,
        price="42.75",
        trade_date="2026-11-06",
        settlement_date="2026-11-09",
    )
    broker = ledger.create(dict(terms, matching_mode="two-sided"), "capture-broker")
    manager = dict(
        terms,
        price="42.80",
        allocations=[
            dict(account="SYN-ALPHA", quantity=6000),
            dict(account="SYN-BETA", quantity=3900),
        ],
    )
    broken = ledger.command(
        broker["id"],
        "manager",
        dict(manager, version=broker["version"], submission_key="capture-initial"),
    )
    assert [f["code"] for f in broken["matching"]["findings"]] == [
        "PRICE_MISMATCH",
        "ALLOCATION_TOTAL_MISMATCH",
    ]
    before = ledger.snapshot()
    analysis = (
        Triage().analyze(ledger.evidence(broken["id"], broken["version"])) if args.ai else None
    )
    assert ledger.snapshot() == before
    corrected = dict(
        terms,
        allocations=[
            dict(account="SYN-ALPHA", quantity=6000),
            dict(account="SYN-BETA", quantity=4000),
        ],
    )
    matched = ledger.command(
        broker["id"],
        "manager",
        dict(corrected, version=broken["version"], submission_key="capture-corrected"),
    )
    assert matched["state"] == "MATCHED" and matched["price_cents"] == 4275
    assert len(matched["submission_history"]) == 2
    capture = dict(
        version="2.1.0",
        generated_at=datetime.now(timezone.utc).isoformat(),
        origin="recorded-local-execution",
        source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        source_state="working-tree",
        source_hashes={
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in Path("src/settlementlab").glob("*.py")
        },
        model_calls=1 if args.ai else 0,
        broker=broker,
        exception=broken,
        corrected=matched,
        analysis=analysis,
        checks=dict(broker_preserved=True, revision_history_preserved=True, ai_did_not_mutate=True),
        scope="One synthetic example; contract and reference validation do not establish model accuracy",
    )
    if analysis:
        refs = analysis["analysis"]["evidence_ids"]
        capture["checks"]["both_discrepancies_cited"] = all(
            ref in refs for ref in ["break:price_cents", "break:allocation_total"]
        )
    output = Path("docs/evidence/matching-v21" + ("-ai" if args.ai else "") + ".json")
    output.write_text(json.dumps(capture, indent=2) + "\n")
    print(output)
    print(json.dumps(capture["checks"]))
    if analysis:
        print(json.dumps(analysis["analysis"], indent=2))
