"""Compensation, authorization, durable fencing and complete investigation evidence."""

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from settlementlab.application.investigation import Investigation
from settlementlab.application.reconciliation import Reconciliation
from settlementlab.assurance.durable_data import CHECKER, MAKER, approved_trade, entry
from settlementlab.assurance.incident_demo import current, seed
from settlementlab.assurance.incident_export import export, package, verify
from settlementlab.bootstrap import create_application
from settlementlab.configuration import Settings
from settlementlab.core.identity import Principal
from settlementlab.core.validation import DomainError


class InvestigationControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        self.app = create_application(
            Settings(database=str(self.output / "test.db"), model="", business_date="2026-11-09")
        )
        self.service = self.app.service
        self.trade = approved_trade(self.service)
        self.trade = self.service.command(
            self.trade["id"],
            "settle-partial",
            dict(version=self.trade["version"], quantity=40, request_key="first"),
            principal=CHECKER,
        )
        self.batch = self.trade["execution_slices"][0]["batch_id"]

    def request(self, key="reversal", batch=None):
        self.trade = current(self.service, self.trade["id"])
        return self.service.command(
            self.trade["id"],
            "request-reversal",
            dict(
                version=self.trade["version"],
                original_batch=batch or self.batch,
                request_key=key,
                reason="Review synthetic execution correction",
            ),
            principal=MAKER,
        )

    def decide(self, request, action="approve-reversal", principal=CHECKER):
        trade = current(self.service, self.trade["id"])
        return self.service.command(
            trade["id"],
            action,
            dict(
                version=trade["version"],
                reversal_id=request["id"],
                reason="Independent checker reviewed original financial entries",
            ),
            principal=principal,
        )

    def test_compensation_preserves_gross_receipts_and_exact_inverse_lines(self):
        original = Investigation(self.service).snapshot(self.trade["id"])["records"]["batches"][0]
        request = self.request()
        self.decide(request)
        graph = Investigation(self.service).snapshot(self.trade["id"])
        trade = graph["trade"]
        self.assertEqual(
            (
                trade["settled_quantity"],
                trade["reversed_quantity"],
                trade["net_settled_quantity"],
                trade["state"],
            ),
            (40, 40, 0, "REVERSED"),
        )
        batches = graph["records"]["batches"]
        self.assertEqual(next(b for b in batches if b["id"] == self.batch), original)
        compensation = next(b for b in batches if b["kind"] == "DVP_REVERSAL")
        self.assertEqual(
            sorted(
                (line["participant_id"], line["asset"], line["delta"])
                for line in compensation["lines"]
            ),
            sorted(
                (line["participant_id"], line["asset"], -line["delta"])
                for line in original["lines"]
            ),
        )
        self.assertEqual(graph["financial_controls"]["status"], "BALANCED")
        net = Reconciliation(self.service).import_statement(
            [dict(trade_id=trade["id"], quantity=0, amount_cents=0)], "net", CHECKER
        )
        self.assertEqual(net["cases"], [])

    def test_same_person_cannot_approve_even_with_checker_role(self):
        request = self.request()
        with self.assertRaises(DomainError) as error:
            self.decide(request, principal=Principal(MAKER.id, "checker"))
        self.assertEqual(error.exception.status, 403)
        self.assertEqual(current(self.service, self.trade["id"])["net_settled_quantity"], 40)

    def test_request_and_decision_replay_never_double_post(self):
        data = dict(
            version=self.trade["version"],
            original_batch=self.batch,
            request_key="same",
            reason="Review synthetic execution correction",
        )
        request = self.service.command(self.trade["id"], "request-reversal", data, principal=MAKER)
        self.assertEqual(
            self.service.command(self.trade["id"], "request-reversal", data, principal=MAKER)["id"],
            request["id"],
        )
        pending = current(self.service, self.trade["id"])
        decision = dict(
            version=pending["version"],
            reversal_id=request["id"],
            reason="Independent checker reviewed original financial entries",
        )
        first = self.service.command(
            self.trade["id"], "approve-reversal", decision, principal=CHECKER
        )
        self.assertEqual(
            self.service.command(self.trade["id"], "approve-reversal", decision, principal=CHECKER),
            first,
        )
        with self.assertRaises(DomainError):
            self.request("another")
        self.assertEqual(
            len(Investigation(self.service).snapshot(self.trade["id"])["records"]["batches"]), 2
        )

    def test_wrong_batch_and_stale_request_rejected_without_writes(self):
        other = approved_trade(self.service, "other")
        other = self.service.command(
            other["id"], "settle", dict(version=other["version"]), principal=CHECKER
        )
        before = self.service.snapshot()
        with self.assertRaises(DomainError):
            self.request(batch=other["settlement_journal"])
        with self.assertRaises(DomainError):
            self.service.command(
                self.trade["id"],
                "request-reversal",
                dict(
                    version=1,
                    original_batch=self.batch,
                    request_key="bad",
                    reason="Review synthetic execution correction",
                ),
                principal=MAKER,
            )
        self.assertEqual(self.service.snapshot(), before)

    def test_request_fences_claim_and_pauses_remaining_execution(self):
        self.app.operations.enqueue_batch([dict(entry(self.trade), quantity=10)], "queued", CHECKER)
        claim = self.app.operations.claim("held-worker")
        request = self.request()
        self.assertEqual(self.app.operations.apply_claim(claim)["status"], "FENCED")
        pending = current(self.service, self.trade["id"])
        with self.assertRaises(DomainError):
            self.service.command(
                pending["id"],
                "cancel",
                dict(
                    version=pending["version"],
                    request_key="cancel",
                    reason="Must not bypass correction review",
                ),
                principal=CHECKER,
            )
        self.decide(request, "reject-reversal")
        self.assertEqual(current(self.service, self.trade["id"])["state"], "PARTIALLY_SETTLED")

    def test_insufficient_reversal_capacity_preserves_pending_decision(self):
        request = self.request()
        # Spend seller cash through another valid synthetic BUY by that participant.
        trade = approved_trade(self.service, "seller-spend", funded=False, quantity=40, side="SELL")
        # Existing manager cash and broker securities allow this opposite execution.
        self.service.command(
            trade["id"], "settle", dict(version=trade["version"]), principal=CHECKER
        )
        before = self.service.snapshot()
        with self.assertRaises(DomainError):
            self.decide(request)
        self.assertEqual(self.service.snapshot(), before)
        self.assertEqual(
            current(self.service, self.trade["id"])["corrections"][0]["status"], "PENDING"
        )

    def test_injected_failure_rolls_back_compensation_and_decision(self):
        request = self.request()
        before = self.service.snapshot()
        with patch.object(self.service, "event", side_effect=RuntimeError("precommit failure")):
            with self.assertRaises(RuntimeError):
                self.decide(request)
        self.assertEqual(self.service.snapshot(), before)
        self.decide(request)
        self.assertEqual(current(self.service, self.trade["id"])["reversed_quantity"], 40)

    def test_portable_export_is_read_only_escaped_and_detects_tampering(self):
        before = self.service.snapshot()
        graph = Investigation(self.service).snapshot(self.trade["id"])
        ids = {n["id"] for n in graph["timeline"]}
        self.assertTrue(
            all(e["source"] in ids and e["target"] in ids for e in graph["correlations"])
        )
        graph["timeline"][0]["title"] = "<script>alert(1)</script>"
        path = self.output / "evidence.zip"
        path.write_bytes(package(graph, dict(version="test", source_commit="test", dirty=True)))
        self.assertEqual(verify(path)["status"], "passed")
        with zipfile.ZipFile(path) as archive:
            self.assertNotIn(b"<script>", archive.read("index.html"))
            files = {n: archive.read(n) for n in archive.namelist()}
        files["incident.json"] += b" "
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        with self.assertRaises(ValueError):
            verify(path)
        self.assertEqual(self.service.snapshot(), before)

    def test_full_legacy_execution_can_be_compensated(self):
        trade = approved_trade(self.service, "legacy-full")
        self.trade = self.service.command(
            trade["id"], "settle", dict(version=trade["version"]), principal=CHECKER
        )
        self.batch = self.trade["settlement_journal"]
        self.decide(self.request())
        self.assertEqual(current(self.service, self.trade["id"])["net_settled_quantity"], 0)

    def test_complete_incident_fixture_retains_initial_and_resolved_evidence(self):
        fresh = create_application(
            Settings(database=str(self.output / "fresh.db"), model="", business_date="2026-11-09")
        )
        report = seed(fresh, self.output, crash=False)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["crash_mode"], "expired-test-fixture")
        self.assertEqual(verify(self.output / "investigate.zip")["status"], "passed")
        self.assertEqual(verify(self.output / "resolved.zip")["status"], "passed")

    def test_sequential_slice_compensations_preserve_distinct_batches(self):
        first = self.batch
        self.trade = self.service.command(
            self.trade["id"],
            "settle-partial",
            dict(version=self.trade["version"], quantity=20, request_key="second"),
            principal=CHECKER,
        )
        second = self.trade["execution_slices"][1]["batch_id"]
        self.decide(self.request("first-correction", first))
        trade = current(self.service, self.trade["id"])
        self.assertEqual((trade["state"], trade["net_settled_quantity"]), ("CORRECTION_REVIEW", 20))
        self.decide(self.request("second-correction", second))
        self.assertEqual(current(self.service, self.trade["id"])["state"], "REVERSED")

    def test_independent_oracle_and_reviewer_fixture_detect_balanced_wrong_value(self):
        from settlementlab.assurance.correction_oracle import audit
        from settlementlab.assurance.reviewer_exercise import build

        self.decide(self.request())
        accepted = {
            self.batch: dict(
                trade_id=self.trade["id"],
                buyer_id=self.trade["buyer_id"],
                seller_id=self.trade["seller_id"],
                symbol="NOVA",
                quantity=40,
                price_cents=4275,
            )
        }
        self.assertEqual(audit(self.app.settings.database, accepted)["status"], "passed")
        before = self.service.snapshot()
        answer = build(self.app.settings.database, self.output / "exercise", accepted)
        self.assertEqual(answer["oracle"]["status"], "failed")
        self.assertEqual(self.service.snapshot(), before)
        self.assertEqual(verify(self.output / "exercise/reviewer-exercise.zip")["status"], "passed")

    def test_investigation_schema_failure_rolls_back_initial_database(self):
        import sqlite3

        from settlementlab.infrastructure.investigation_schema import initialize_investigation
        from settlementlab.infrastructure.store import SQLiteStore

        path = self.output / "broken.db"

        def fail(db):
            initialize_investigation(db)
            raise RuntimeError("investigation migration fault")

        with (
            patch("settlementlab.infrastructure.schema.initialize_investigation", side_effect=fail),
            self.assertRaises(RuntimeError),
        ):
            SQLiteStore(path)
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0], 0
            )

    def test_exports_strip_live_lease_capabilities_without_invalidating_worker(self):
        import io
        import json

        self.app.operations.enqueue_batch(
            [dict(entry(self.trade), quantity=10)], "leased-export", CHECKER
        )
        claim = self.app.operations.claim("live-worker")
        token = claim["lease_token"]
        snapshot = Investigation(self.service).snapshot(self.trade["id"])
        self.assertNotIn(token, json.dumps(snapshot))
        self.assertNotIn("lease_token", json.dumps(snapshot))
        with zipfile.ZipFile(io.BytesIO(export(self.service, self.trade["id"]))) as archive:
            self.assertNotIn(token.encode(), archive.read("incident.json"))
        self.assertEqual(self.app.operations.apply_claim(claim)["status"], "SUCCEEDED")
