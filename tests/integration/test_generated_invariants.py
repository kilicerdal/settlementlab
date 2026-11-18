"""Seeded property/state-machine checks with replayable seeds, no extra dependency.

This is bounded generation, not exhaustive proof or automatic shrinking.
"""

import random
import tempfile
import unittest
from pathlib import Path

from settlementlab.application.operations import DurableOperations
from settlementlab.assurance.campaign import application, planned_trade
from settlementlab.assurance.durable_data import AUDITOR, CHECKER, MAKER, entry, fund_trade
from settlementlab.assurance.oracle import audit
from settlementlab.core.postings import balanced_changes
from settlementlab.core.validation import DomainError


class GeneratedInvariants(unittest.TestCase):
    def test_two_thousand_generated_conservation_cases_and_mutations(self):
        rng = random.Random(410)
        for index in range(2000):
            with self.subTest(seed=410, case=index):
                quantity = rng.randint(1, 10**8)
                cash = quantity * rng.randint(1, 10**5)
                lines = [
                    ("A", "CASH:USD", -cash),
                    ("B", "CASH:USD", cash),
                    ("B", "SEC:NOVA", -quantity),
                    ("A", "SEC:NOVA", quantity),
                ]
                rng.shuffle(lines)
                changes = balanced_changes(lines)
                self.assertEqual(
                    sum(v for (_, unit), v in changes.items() if unit == "CASH:USD"), 0
                )
                party, unit, delta = lines[0]
                lines[0] = party, unit, delta + 1
                with self.assertRaises(DomainError):
                    balanced_changes(lines)

    def test_generated_sequences_preserve_effects_under_replay_fencing_and_faults(self):
        for seed in range(24):
            with self.subTest(seed=seed), tempfile.TemporaryDirectory() as d:
                app = application(Path(d) / "properties.db")
                pending = app.service.create(
                    dict(
                        symbol="PEND",
                        quantity=seed + 1,
                        price="1.00",
                        side="BUY",
                        currency="USD",
                        trade_date="2026-11-06",
                        settlement_date="2026-11-09",
                        matching_mode="two-sided",
                        settlement_model="shared-ledger",
                    ),
                    "pending",
                    principal=MAKER,
                )
                with self.assertRaises(DomainError):
                    app.service.command(
                        pending["id"], "settle", dict(version=pending["version"]), principal=CHECKER
                    )
                self.assertEqual(audit(app.settings.database, {})["status"], "passed")
                now = [1000.0]
                ops = DurableOperations(app.service, now=lambda: now[0])
                trade, expected = planned_trade(app, "generated", random.Random(seed), funded=False)
                before = app.service.snapshot()
                with self.assertRaises(DomainError):
                    ops.enqueue_batch([entry(trade)], "unauthorized", AUDITOR)
                self.assertEqual(app.service.snapshot(), before)
                batch = ops.enqueue_batch([entry(trade)], "batch", CHECKER)
                self.assertTrue(ops.enqueue_batch([entry(trade)], "batch", CHECKER)["replayed"])
                # Unfunded execution must never create a settlement journal.
                dead = ops.process_one("shortage")
                self.assertEqual(dead["status"], "DEAD_LETTER")
                self.assertEqual(audit(app.settings.database, {})["status"], "passed")
                current = next(
                    t for t in app.service.snapshot()["trades"] if t["id"] == trade["id"]
                )
                fund_trade(app.service, current, "fund")
                funded = app.service.snapshot()
                fund_trade(app.service, current, "fund")
                self.assertEqual(app.service.snapshot(), funded)
                ops.requeue(
                    dead["id"], current["version"], "Reviewed generated capacity recovery", CHECKER
                )
                old = ops.claim("expired", lease=1)
                now[0] += 2
                owned = ops.claim("current")
                self.assertEqual(ops.apply_claim(old)["status"], "FENCED")
                if seed % 2:

                    def fault(phase):
                        if phase == "before-commit":
                            raise RuntimeError("generated fault")

                    self.assertEqual(ops.apply_claim(owned, fault)["status"], "RETRY_WAIT")
                    now[0] += 2
                    result = ops.process_one("retry")
                else:
                    result = ops.apply_claim(owned)
                self.assertEqual(result["status"], "SUCCEEDED")
                self.assertIsNone(ops.process_one("duplicate"))
                self.assertEqual(
                    audit(app.settings.database, {trade["id"]: expected})["status"], "passed"
                )
                while ops.deliver_one("observer"):
                    pass
                events = ops.snapshot()["outbox"]
                before = app.service.snapshot()
                for event in reversed(events):
                    self.assertFalse(ops.redeliver(event["event_id"], CHECKER)["applied"])
                self.assertEqual(app.service.snapshot(), before)
                self.assertEqual(ops.snapshot()["receipts"], 2)
                self.assertEqual(batch["jobs"][0]["id"], dead["id"])
