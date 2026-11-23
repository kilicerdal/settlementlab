"""Explicit synthetic reviewer exercise, isolated from the original incident database."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from ..application.investigation import Investigation
from ..bootstrap import create_application
from ..configuration import Settings
from ..infrastructure.sqlite_snapshot import readonly_connection
from .correction_oracle import audit
from .incident_export import export, verify


def build(database, output, accepted):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    target = output / "reviewer-exercise.db"
    if target.exists():
        raise ValueError("Reviewer exercise already exists; use a fresh output directory")
    with (
        readonly_connection(database) as source,
        closing(sqlite3.connect(target)) as destination,
    ):
        source.backup(destination)
    with closing(sqlite3.connect(target)) as db, db:
        row = db.execute(
            "SELECT compensation_batch,trade_id FROM reversal_requests WHERE status='APPROVED' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if not row:
            raise ValueError("Exercise requires an approved synthetic correction")
        batch, trade_id = row
        # Deliberately wrong by one cent, while preserving asset conservation and projection.
        lines = db.execute(
            "SELECT line,participant_id,delta FROM journal_lines WHERE batch_id=? AND asset='CASH:USD'",
            (batch,),
        ).fetchall()
        for line, party, delta in lines:
            change = -1 if delta > 0 else 1
            db.execute(
                "UPDATE journal_lines SET delta=delta+? WHERE batch_id=? AND line=?",
                (change, batch, line),
            )
            db.execute(
                "UPDATE balances SET balance=balance+? WHERE participant_id=? AND asset='CASH:USD'",
                (change, party),
            )
    app = create_application(Settings(database=str(target), model="", business_date="2026-11-09"))
    assert (
        Investigation(app.service).snapshot(trade_id)["financial_controls"]["status"] == "BALANCED"
    )
    result = audit(target, accepted)
    assert result["status"] == "failed" and any(
        f["control"] == "compensation-economics" for f in result["findings"]
    )
    bundle = output / "reviewer-exercise.zip"
    bundle.write_bytes(export(app.service, trade_id))
    assert verify(bundle)["status"] == "passed"
    (output / "REVIEWER_WORKSHEET.md").write_text("""# Independent reviewer exercise

This is a deliberately defective synthetic fixture, not production evidence. Inspect the supplied incident ZIP offline or open the isolated exercise database with the current local framework. Do not run financial commands to hide the discrepancy.

1. Explain the worker interruption and whether its underlying cause is established.
2. Trace the delayed and corrected statements to their retained case resolutions.
3. Compare all four original execution legs with the compensating legs. Does conservation alone prove correct economics?
4. State gross, reversed and net quantities; identify any difference between recorded receipts and actual cash movements.
5. Record the evidence IDs, expected/observed values, severity, a regression test and your proposed correction.

Record reviewer name, reviewed source commit and date. Leave findings open until independently resolved. Automated generation of this worksheet does not count as an outside review. The answer key is separate; give the reviewer only this worksheet and the exercise ZIP initially.
""")
    answer = dict(
        status="passed",
        fixture_defect="Compensating cash legs are one cent too small; balances were also adjusted so conservation and projection still pass.",
        oracle=result,
        checksums_only_verify_content_integrity=True,
        independent_review="pending",
    )
    (output / "reviewer-answer-key.json").write_text(json.dumps(answer, indent=2) + "\n")
    return answer
