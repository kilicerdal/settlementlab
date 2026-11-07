"""Opt-in live local-model checks; never run by the default test suite."""

import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from settlementlab.ai import Triage
from settlementlab.domain import Ledger

results = []
for name, cash, securities, required in [
    ("insufficient-cash", 0, 100, ["fact:required_cash_cents", "fact:available_cash_cents"]),
    (
        "insufficient-securities",
        427500,
        0,
        ["fact:required_securities", "fact:available_securities"],
    ),
]:
    with tempfile.TemporaryDirectory() as temporary:
        ledger = Ledger(Path(temporary) / "eval.db")
        t = ledger.create(
            dict(symbol="NOVA", quantity=100, price="42.75", trade_date="2026-11-06"), name
        )
        for action, data in [
            ("allocate", dict(allocations=[dict(account="SYN-A", quantity=100)])),
            ("affirm", dict(instruction="SYN-CUSTODY")),
            ("fund", dict(cash_cents=cash, securities=securities)),
            ("settle", {}),
        ]:
            t = ledger.command(t["id"], action, dict(version=t["version"], **data))
        before = ledger.snapshot()
        start = time.monotonic()
        try:
            response = Triage().analyze(ledger.evidence(t["id"], t["version"]))
            references = response["analysis"]["evidence_ids"]
            checks = dict(
                required_fact_references=all(i in references for i in required),
                ledger_unchanged=before == ledger.snapshot(),
            )
            results.append(
                dict(
                    case=name,
                    elapsed_seconds=round(time.monotonic() - start, 2),
                    checks=checks,
                    response=response,
                )
            )
        except Exception as error:
            results.append(dict(case=name, error=str(error), checks={"provider_completed": False}))
report = dict(
    generated_at=datetime.now(timezone.utc).isoformat(),
    mode="live-local-model",
    scope="Two synthetic examples; citation and mutation checks, not a semantic quality benchmark",
    cases=results,
)
destination = Path("docs/evidence/local-ai-evaluation.json")
destination.write_text(json.dumps(report, indent=2) + "\n")
for result in results:
    print(result["case"], result["checks"], flush=True)
if not all(all(result["checks"].values()) for result in results):
    raise SystemExit(1)
