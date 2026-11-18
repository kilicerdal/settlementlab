import copy
import random
import sqlite3
import tempfile
import unittest
from pathlib import Path

from settlementlab.assurance.campaign import application, planned_trade
from settlementlab.assurance.durable_data import CHECKER, entry
from settlementlab.assurance.oracle import audit, expected_lines


class IndependentOracle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "oracle.db"
        self.app = application(self.database)
        self.trade, terms = planned_trade(self.app, "oracle", random.Random(41))
        self.expected = {self.trade["id"]: terms}
        self.app.operations.enqueue_batch([entry(self.trade)], "batch", CHECKER)
        self.app.operations.process_one("worker")

    def test_clean_book_and_balanced_but_wrong_economic_amount(self):
        evidence = audit(self.database, self.expected, include_details=True)
        self.assertEqual(evidence["status"], "passed")
        self.assertEqual(len(evidence["comparisons"][0]["expected_movements"]), 4)
        self.assertTrue(evidence["comparisons"][0]["movements_match"])
        # Keep every asset balanced AND keep materialized balances consistent.
        # A conservation-only control would pass this wrong economic transfer.
        with sqlite3.connect(self.database) as db:
            batch = db.execute(
                "SELECT id FROM journal_batches WHERE kind='DVP_SETTLEMENT'"
            ).fetchone()[0]
            rows = db.execute(
                "SELECT line,participant_id,asset,delta FROM journal_lines WHERE batch_id=? AND asset='CASH:USD'",
                (batch,),
            ).fetchall()
            for line, party, asset, delta in rows:
                adjustment = -1 if delta > 0 else 1
                db.execute(
                    "UPDATE journal_lines SET delta=delta+? WHERE batch_id=? AND line=?",
                    (adjustment, batch, line),
                )
                db.execute(
                    "UPDATE balances SET balance=balance+? WHERE participant_id=? AND asset=?",
                    (adjustment, party, asset),
                )
        controls = {f["control"] for f in audit(self.database, self.expected)["findings"]}
        self.assertIn("independent-dvp-movements", controls)
        self.assertNotIn("asset-conservation", controls)
        self.assertNotIn("balance-projection", controls)

    def test_missing_receipt_projection_and_approval_are_detected(self):
        with sqlite3.connect(self.database) as db:
            db.execute("DELETE FROM settlements")
            db.execute("UPDATE approval_requests SET decided_by=maker_id")
            db.execute("UPDATE balances SET balance=balance+1 WHERE participant_id='SYN-RESERVE'")
        controls = {f["control"] for f in audit(self.database, self.expected)["findings"]}
        self.assertTrue(
            {
                "independent-settlement-receipt",
                "independent-approval",
                "balance-projection",
                "settled-trade-completeness",
            }
            <= controls
        )

    def test_independent_input_changes_and_invalid_terms(self):
        wrong = copy.deepcopy(self.expected)
        wrong[self.trade["id"]]["quantity"] += 1
        self.assertEqual(audit(self.database, wrong)["status"], "failed")
        for bad in [True, 0, -1, "10"]:
            terms = dict(next(iter(self.expected.values())), quantity=bad)
            with self.assertRaises(ValueError):
                expected_lines(terms)
