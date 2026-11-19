"""V4.2 controls: actual postings, approval fencing and independent evidence."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from settlementlab.application.operations import DurableOperations
from settlementlab.application.reconciliation import Reconciliation
from settlementlab.assurance.durable_data import CHECKER, MAKER, approved_trade, entry
from settlementlab.bootstrap import create_application
from settlementlab.configuration import Settings
from settlementlab.core.deadlines import FixedTimestampClock
from settlementlab.core.statements import statement_rows
from settlementlab.core.validation import DomainError


class WorkflowControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "workflow.db"
        self.app = create_application(
            Settings(database=str(self.database), model="", business_date="2026-11-09")
        )
        self.service = self.app.service
        self.trade = approved_trade(self.service)
        self.ops = DurableOperations(self.service, now=lambda: 1000.0)

    def command(self, action, key, **data):
        return self.service.command(
            self.trade["id"],
            action,
            dict(version=self.trade["version"], request_key=key, **data),
            principal=MAKER if action == "amend" else CHECKER,
        )

    def test_partial_replay_remaining_and_final_receipt(self):
        request_version = self.trade["version"]
        first = self.command("settle-partial", "slice-one", quantity=40)
        self.assertEqual(
            (first["state"], first["settled_quantity"], first["remaining_quantity"]),
            ("PARTIALLY_SETTLED", 40, 60),
        )
        replay = self.command("settle-partial", "slice-one", quantity=40)
        self.assertEqual(replay, first)
        self.assertEqual(self.trade["version"], request_version)
        with self.assertRaises(DomainError):
            self.command("settle-partial", "slice-one", quantity=41)
        self.trade = first
        done = self.service.command(
            first["id"], "settle", dict(version=first["version"]), principal=CHECKER
        )
        self.assertEqual(
            (done["state"], done["settled_quantity"], done["settled_amount_cents"]),
            ("SETTLED", 100, 427500),
        )
        self.assertEqual(len(done["execution_slices"]), 2)
        self.assertEqual(self.service.snapshot()["treasury"]["controls"]["status"], "BALANCED")

    def test_overfill_stale_version_and_wrong_role_do_not_post(self):
        before = self.service.snapshot()
        for quantity in (0, True, -1, 101, "10"):
            with self.subTest(quantity=quantity), self.assertRaises(DomainError):
                self.command("settle-partial", "bad-" + str(quantity), quantity=quantity)
        with self.assertRaises(DomainError):
            self.service.command(
                self.trade["id"],
                "settle-partial",
                dict(version=self.trade["version"], request_key="maker", quantity=10),
                principal=MAKER,
            )
        self.assertEqual(self.service.snapshot(), before)

    def test_cancel_partial_preserves_value_and_rejects_more_execution(self):
        self.trade = self.command("settle-partial", "first", quantity=25)
        cancelled = self.command(
            "cancel", "cancel", reason="Counterparty withdrew remaining obligation"
        )
        self.assertEqual(
            (cancelled["state"], cancelled["settled_quantity"], cancelled["remaining_quantity"]),
            ("CANCELLED", 25, 75),
        )
        self.trade = cancelled
        with self.assertRaises(DomainError):
            self.command("settle-partial", "after-cancel", quantity=1)
        with self.assertRaises(DomainError):
            self.command(
                "amend",
                "posted-amend",
                reason="Cannot rewrite posted economics",
                terms=self.terms(),
            )

    def terms(self):
        return dict(
            symbol="NOVA",
            side="BUY",
            currency="USD",
            quantity=100,
            price="43.00",
            trade_date="2026-11-06",
            settlement_date="2026-11-09",
        )

    def test_amend_fences_claimed_worker_and_invalidates_old_approval(self):
        self.ops.enqueue_batch([entry(self.trade)], "queued", CHECKER)
        claim = self.ops.claim("stale-worker")
        amended = self.command(
            "amend", "amend", reason="Broker corrected accepted price", terms=self.terms()
        )
        self.assertEqual(
            (amended["state"], amended["lifecycle_revision"], amended["price_cents"]),
            ("RECEIVED", 2, 4300),
        )
        self.assertEqual(amended["approval_history"][0]["status"], "APPROVED")
        self.assertIsNone(amended["manager_submission"])
        self.assertEqual(self.ops.apply_claim(claim)["status"], "FENCED")
        self.trade = amended
        with self.assertRaises(DomainError):
            self.command("settle-partial", "stale-approval", quantity=1)
        with self.service.store.transaction() as repo:
            self.assertEqual(len(repo.lifecycle_revisions(amended["id"])), 2)
            self.assertFalse(repo.current_authorized(amended))

    def test_durable_partial_posts_receipt_and_observer_atomically(self):
        self.ops.enqueue_batch([dict(entry(self.trade), quantity=30)], "partial-job", CHECKER)
        self.assertEqual(self.ops.process_one("worker")["status"], "SUCCEEDED")
        snapshot = self.ops.snapshot()
        self.assertEqual(snapshot["receipts"], 1)
        self.assertEqual(len(snapshot["outbox"]), 1)
        self.assertEqual(self.ops.deliver_one("observer")["status"], "DELIVERED")
        current = self.service.snapshot()["trades"][0]
        self.assertEqual(current["settled_quantity"], 30)
        self.assertEqual(current["remaining_quantity"], 70)

    def test_partial_precommit_failure_rolls_back_financial_and_evidence(self):
        self.ops.enqueue_batch([dict(entry(self.trade), quantity=30)], "partial-job", CHECKER)
        before = self.service.snapshot()

        def crash(phase):
            if phase == "before-commit":
                raise RuntimeError("injected")

        self.assertEqual(self.ops.process_one("worker", fault=crash)["status"], "RETRY_WAIT")
        self.assertEqual(self.service.snapshot(), before)
        self.assertEqual(self.ops.snapshot()["receipts"], 0)

    def test_cutoff_uses_explicit_utc_timestamp(self):
        self.service.clock = FixedTimestampClock("2026-11-09T16:30:00Z")
        self.assertEqual(self.service.snapshot()["trades"][0]["aging"]["bucket"], "DUE_SOON")
        self.service.clock = FixedTimestampClock("2026-11-09T17:00:00Z")
        before = self.service.snapshot()
        with self.assertRaises(DomainError):
            self.command("settle-partial", "late", quantity=10)
        self.assertEqual(self.service.snapshot(), before)
        self.assertEqual(before["trades"][0]["aging"]["bucket"], "CUTOFF_PASSED")

    def test_statement_break_requires_distinct_corrected_evidence(self):
        self.trade = self.command("settle-partial", "first", quantity=25)
        recon = Reconciliation(self.service)
        imported = recon.import_statement(
            "trade_id,quantity,amount_cents\n" + self.trade["id"] + ",24,102600\n",
            "external-1",
            CHECKER,
        )
        case = imported["cases"][0]
        self.assertEqual(case["kind"], "VALUE_MISMATCH")
        with self.assertRaises(DomainError):
            recon.resolve(case["id"], imported["id"], "Reviewed statement discrepancy", CHECKER)
        wrong = recon.import_statement([], "still-wrong", CHECKER)
        with self.assertRaises(DomainError):
            recon.resolve(case["id"], wrong["id"], "Reviewed statement discrepancy", CHECKER)
        correct = recon.import_statement(
            [dict(trade_id=self.trade["id"], quantity=25, amount_cents=106875)],
            "external-2",
            CHECKER,
        )
        result = recon.resolve(
            case["id"], correct["id"], "Counterparty supplied corrected statement", CHECKER
        )
        self.assertEqual(result["status"], "RESOLVED")
        self.assertEqual(result["observed"], case["observed"])
        self.assertEqual(recon.import_statement([], "still-wrong", CHECKER)["id"], wrong["id"])
        with self.assertRaises(DomainError):
            recon.import_statement([], "external-2", CHECKER)

    def test_statement_parser_rejects_duplicate_and_ambiguous_values(self):
        for value in (
            "trade_id,quantity,amount_cents\nT,1.2,10",
            "trade_id,quantity,amount_cents\nT,1,10\nT,2,20",
            [dict(trade_id="T", quantity=True, amount_cents=1)],
        ):
            with self.subTest(value=value), self.assertRaises(DomainError):
                statement_rows(value)

    def test_schema_upgrade_retains_posted_legacy_receipt(self):
        self.service.command(
            self.trade["id"], "settle", dict(version=self.trade["version"]), principal=CHECKER
        )
        with sqlite3.connect(self.database) as db:
            db.execute("PRAGMA user_version=5")
        restarted = create_application(
            Settings(database=str(self.database), model="", business_date="2026-11-09")
        )
        current = restarted.service.snapshot()["trades"][0]
        self.assertEqual((current["state"], current["settled_quantity"]), ("SETTLED", 100))
        self.assertEqual(current["execution_slices"], [])

    def test_independent_oracle_detects_balanced_wrong_economics(self):
        from settlementlab.assurance.slice_oracle import audit_slices

        self.trade = self.command("settle-partial", "slice", quantity=40)
        plans = {
            self.trade["id"]: dict(
                buyer_id=self.trade["buyer_id"],
                seller_id=self.trade["seller_id"],
                symbol="NOVA",
                price_cents=4275,
                quantity=100,
                revision=1,
                executed_quantity=40,
            )
        }
        self.assertEqual(audit_slices(self.database, plans)["status"], "passed")
        with sqlite3.connect(self.database) as db:
            db.execute(
                "UPDATE journal_lines SET delta=CASE WHEN delta<0 THEN delta-1 ELSE delta+1 END WHERE batch_id=? AND asset='CASH:USD'",
                (self.trade["execution_slices"][0]["batch_id"],),
            )
        report = audit_slices(self.database, plans)
        self.assertEqual(report["status"], "failed")
        self.assertIn("slice-economics", [f["control"] for f in report["findings"]])

    def test_partial_failure_then_funding_keeps_original_execution(self):
        from settlementlab.assurance.durable_data import fund_trade

        other = approved_trade(self.service, "unfunded", funded=False, quantity=200)
        # First trade's shared funding supports only part of this second obligation.
        self.trade = other
        self.trade = self.command("settle-partial", "one", quantity=40)
        self.assertEqual(self.trade["settled_quantity"], 40)
        failed = self.command("settle-partial", "too-much-capacity", quantity=160)
        self.assertEqual((failed["state"], failed["settled_quantity"]), ("FAILED", 40))
        fund_trade(self.service, failed, "repair-capacity")
        self.trade = failed
        done = self.service.command(
            failed["id"], "settle", dict(version=failed["version"]), principal=CHECKER
        )
        self.assertEqual((done["state"], done["settled_quantity"]), ("SETTLED", 200))

    def test_amended_trade_can_be_matched_and_approved_again(self):
        terms = self.terms()
        amended = self.command(
            "amend", "amended", terms=terms, reason="Broker corrected accepted price"
        )
        matched = self.service.command(
            amended["id"],
            "manager",
            dict(
                terms,
                version=amended["version"],
                submission_key="new-manager",
                allocations=[dict(account="SYN-FUND", quantity=100)],
            ),
            principal=MAKER,
        )
        requested = self.service.command(
            matched["id"],
            "request-affirmation",
            dict(version=matched["version"], instruction="SYN-CUSTODY", request_key="new-approval"),
            principal=MAKER,
        )
        approved = self.service.command(
            requested["id"],
            "approve",
            dict(version=requested["version"], approval_id=requested["pending_approval"]["id"]),
            principal=CHECKER,
        )
        self.trade = approved
        done = self.command("settle-partial", "revised-slice", quantity=10)
        self.assertEqual(
            (done["settled_quantity"], done["execution_slices"][0]["revision"]), (10, 2)
        )

    def test_overdue_cutoff_does_not_reopen_next_morning(self):
        self.service.clock = FixedTimestampClock("2026-11-10T09:00:00Z")
        current = self.service.snapshot()["trades"][0]
        self.assertEqual(current["aging"]["bucket"], "OVERDUE")
        self.assertEqual(current["aging"]["overdue_business_days"], 1)
        with self.assertRaises(DomainError):
            self.command("settle-partial", "next-morning", quantity=10)

    def test_lifecycle_migration_failure_rolls_back_all_ddl(self):
        from unittest.mock import patch

        from settlementlab.infrastructure.lifecycle_schema import initialize_lifecycle
        from settlementlab.infrastructure.store import SQLiteStore

        target = Path(self.temp.name) / "failed-upgrade.db"

        def fail(db):
            initialize_lifecycle(db)
            raise RuntimeError("injected lifecycle migration failure")

        with patch("settlementlab.infrastructure.schema.initialize_lifecycle", side_effect=fail):
            with self.assertRaises(RuntimeError):
                SQLiteStore(target)
        with sqlite3.connect(target) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0], 0
            )
