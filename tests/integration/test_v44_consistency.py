"""Financial event ordering, nonblocking snapshots, indexed investigations and bundle economics."""

import concurrent.futures
import json
import sqlite3
import tempfile
import time
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from settlementlab.application.investigation import Investigation
from settlementlab.application.reconciliation import Reconciliation
from settlementlab.assurance.durable_data import CHECKER, MAKER, approved_trade
from settlementlab.assurance.incident_demo import current
from settlementlab.assurance.incident_export import export, verify
from settlementlab.assurance.reviewer_exercise import build
from settlementlab.bootstrap import create_application
from settlementlab.configuration import Settings
from settlementlab.core.durable import LeaseLost
from settlementlab.core.validation import DomainError


class ConsistencyControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = create_application(
            Settings(database=str(self.root / "test.db"), model="", business_date="2026-11-09")
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

    def compensate(self):
        trade = current(self.service, self.trade["id"])
        request = self.service.command(
            trade["id"],
            "request-reversal",
            dict(
                version=trade["version"],
                original_batch=self.batch,
                reason="Review original posting for compensation",
                request_key="correction",
            ),
            principal=MAKER,
        )
        trade = current(self.service, trade["id"])
        return self.service.command(
            trade["id"],
            "approve-reversal",
            dict(
                version=trade["version"],
                reversal_id=request["id"],
                reason="Independent checker verified exact inverse entries",
            ),
            principal=CHECKER,
        )

    def plan(self):
        data = dict(
            format_version=1,
            trade_id=self.trade["id"],
            terms=dict(
                buyer_id=self.trade["buyer_id"],
                seller_id=self.trade["seller_id"],
                symbol="NOVA",
                quantity=100,
                price_cents=4275,
            ),
            executions=[dict(batch_id=self.batch, quantity=40)],
            compensations=[self.batch],
        )
        path = self.root / "accepted.json"
        path.write_text(json.dumps(data))
        return path

    def test_correction_event_is_atomic_and_projection_becomes_net_zero(self):
        self.assertEqual(self.app.positions.deliver_one("observer")["status"], "DELIVERED")
        view = self.app.positions.snapshot(self.trade["id"])
        self.assertEqual(view["observed"]["net_quantity"], 40)
        self.compensate()
        view = self.app.positions.snapshot(self.trade["id"])
        self.assertEqual(view["status"], "LAGGING")
        self.assertEqual(view["authoritative"]["net_quantity"], 0)
        self.assertEqual(view["observed"]["net_quantity"], 40)
        self.assertEqual(view["event_history"][-1]["event_type"], "CompensationPosted")
        self.app.positions.deliver_one("observer")
        self.assertEqual(self.app.positions.snapshot(self.trade["id"])["status"], "CURRENT")

    def test_out_of_order_and_duplicate_events_cannot_regress_position(self):
        self.compensate()
        now = time.time()
        with self.service.store.transaction() as repo:
            first = repo.position_claim("first", now, 30)
            second = repo.position_claim("second", now, 30)
            self.assertTrue(repo.position_consume(second, now))
            repo.position_ack(second, now)
            self.assertFalse(repo.position_consume(first, now))
            repo.position_ack(first, now)
            self.assertFalse(repo.position_consume(second, now))
        view = self.app.positions.snapshot(self.trade["id"])
        self.assertEqual(view["observed"]["net_quantity"], 0)
        self.assertEqual(view["status"], "CURRENT")

    def test_post_projection_crash_replays_without_duplicate_projection(self):
        def crash(phase):
            if phase == "after-projection-commit":
                raise RuntimeError("injected response loss")

        self.assertEqual(
            self.app.positions.deliver_one("observer", fault=crash)["status"], "PENDING"
        )
        result = self.app.positions.deliver_one("recovery")
        self.assertEqual(result["status"], "DELIVERED")
        self.assertFalse(result["applied"])
        with self.service.store.read_transaction() as repo:
            self.assertEqual(
                repo.db.execute("SELECT COUNT(*) FROM position_inbox").fetchone()[0], 1
            )

    def test_pre_projection_crash_rolls_back_inbox_and_projection(self):
        def crash(phase):
            if phase == "before-projection-commit":
                raise RuntimeError("injected rollback")

        self.app.positions.deliver_one("observer", fault=crash)
        self.assertIsNone(self.app.positions.snapshot(self.trade["id"])["observed"])
        self.assertTrue(self.app.positions.deliver_one("recovery")["applied"])

    def test_publication_failure_rolls_back_compensation(self):
        before = self.service.snapshot()
        # Fail only compensation publication after its inverse journal was staged.
        from settlementlab.infrastructure.position_repository import PositionRepository

        original = PositionRepository.position_emit

        def fail(repo, trade, kind, batch):
            if kind == "CompensationPosted":
                raise RuntimeError("outbox failed")
            return original(repo, trade, kind, batch)

        with (
            patch.object(PositionRepository, "position_emit", fail),
            self.assertRaises(RuntimeError),
        ):
            self.compensate()
        trade = current(self.service, self.trade["id"])
        self.assertEqual(trade["reversed_quantity"], 0)
        self.assertEqual(trade["corrections"][0]["status"], "PENDING")
        self.assertEqual(len(self.app.positions.snapshot(self.trade["id"])["event_history"]), 1)
        self.assertEqual(trade["settled_quantity"], before["trades"][0]["settled_quantity"])

    def test_expired_claim_is_fenced_and_tokens_are_not_public(self):
        now = time.time()
        with self.service.store.transaction() as repo:
            first = repo.position_claim("old", now, 0.1)
            second = repo.position_claim("new", now + 1, 30)
            with self.assertRaises(LeaseLost):
                repo.position_ack(first, now + 1)
        snapshot = Investigation(self.service).snapshot(self.trade["id"])
        self.assertNotIn(second["lease_token"], json.dumps(snapshot))
        self.assertNotIn("lease_token", json.dumps(snapshot))

    def test_read_snapshot_allows_writer_commit_and_remains_consistent(self):
        with self.service.store.read_transaction() as repo:
            old = repo.db.execute(
                "SELECT version FROM trades WHERE id=?", (self.trade["id"],)
            ).fetchone()[0]
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    self.service.command,
                    self.trade["id"],
                    "settle-partial",
                    dict(version=old, quantity=10, request_key="while-reading"),
                    principal=CHECKER,
                )
                result = future.result(timeout=3)
            self.assertEqual(result["settled_quantity"], 50)
            self.assertEqual(
                repo.db.execute(
                    "SELECT version FROM trades WHERE id=?", (self.trade["id"],)
                ).fetchone()[0],
                old,
            )
            with self.assertRaises(sqlite3.OperationalError):
                repo.db.execute("DELETE FROM trades")
        self.assertGreater(current(self.service, self.trade["id"])["version"], old)

    def test_statement_membership_covers_missing_external_and_empty_resolution(self):
        recon = Reconciliation(self.service)
        missing = recon.import_statement([], "missing", CHECKER)
        matched = recon.import_statement(
            [dict(trade_id=self.trade["id"], quantity=40, amount_cents=171000)], "match", CHECKER
        )
        recon.resolve(
            missing["cases"][0]["id"],
            matched["id"],
            "Corrected statement confirms internal receipts",
            CHECKER,
        )
        graph = Investigation(self.service).snapshot(self.trade["id"])
        self.assertEqual(
            {s["id"] for s in graph["records"]["statements"]}, {missing["id"], matched["id"]}
        )

    def test_investigation_bounds_before_materializing_large_history(self):
        with self.service.store.transaction() as repo:
            repo.db.executemany(
                "INSERT INTO audit(trade_id,timestamp,actor,action,detail) VALUES(?,?,?,?,?)",
                [
                    (
                        self.trade["id"],
                        "2026-11-22T00:00:00+00:00",
                        "fixture",
                        "ROW",
                        "bounded history",
                    )
                    for _ in range(5001)
                ],
            )
        with self.assertRaises(DomainError) as error:
            Investigation(self.service).snapshot(self.trade["id"])
        self.assertEqual(error.exception.status, 413)

    def test_basis_contracts_explicitly_distinguish_gross_and_net(self):
        self.compensate()
        rows = [dict(trade_id=self.trade["id"], quantity=0, amount_cents=0)]
        gross = self.service.reconcile(rows)
        net = Reconciliation(self.service).import_statement(rows, "net", CHECKER)
        self.assertEqual(gross["accounting_basis"], "GROSS_EXECUTED_RECEIPTS")
        self.assertEqual(gross["status"], "BREAKS")
        self.assertEqual(net["accounting_basis"], "NET_AFTER_APPROVED_COMPENSATIONS")
        self.assertEqual(net["cases"], [])

    def test_combined_verification_rejects_balanced_wrong_bundle(self):
        self.compensate()
        path = self.root / "correct.zip"
        path.write_bytes(export(self.service, self.trade["id"]))
        self.assertEqual(verify(path)["verification_level"], "CONTENT_INTEGRITY_ONLY")
        self.assertEqual(verify(path, self.plan())["status"], "passed")
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
        build(self.app.settings.database, self.root / "exercise", accepted)
        bad = self.root / "exercise/reviewer-exercise.zip"
        self.assertEqual(verify(bad)["status"], "passed")
        report = verify(bad, self.plan())
        self.assertEqual(report["status"], "failed")
        self.assertIn(
            "compensation-economics", [f["control"] for f in report["economics"]["findings"]]
        )

    def test_external_expectations_are_not_inferred_from_the_bundle(self):
        self.compensate()
        path = self.root / "bundle.zip"
        path.write_bytes(export(self.service, self.trade["id"]))
        plan_path = self.plan()
        data = json.loads(plan_path.read_text())
        data["terms"]["price_cents"] = 4276
        plan_path.write_text(json.dumps(data))
        self.assertEqual(verify(path, plan_path)["status"], "failed")
        plan_path.write_text('{"format_version":1,"format_version":1}')
        with self.assertRaises(ValueError):
            verify(path, plan_path)

    def test_indexed_investigation_ignores_unrelated_statement_history(self):
        fresh = create_application(
            Settings(database=str(self.root / "indexed.db"), model="", business_date="2026-11-09")
        )
        recon = Reconciliation(fresh.service)
        for i in range(100):
            recon.import_statement(
                [dict(trade_id="EXTERNAL-" + str(i), quantity=1, amount_cents=100)],
                "history-" + str(i),
                CHECKER,
            )
        trade = approved_trade(fresh.service, "index-target")
        trade = fresh.service.command(
            trade["id"],
            "settle-partial",
            dict(version=trade["version"], quantity=10, request_key="post"),
            principal=CHECKER,
        )
        relevant = recon.import_statement(
            [dict(trade_id=trade["id"], quantity=10, amount_cents=42750)], "relevant", CHECKER
        )
        with fresh.service.store.read_transaction() as repo:
            queries = []
            repo.db.set_trace_callback(queries.append)
            records = repo.investigation_records(trade["id"])
        self.assertEqual([r["id"] for r in records["statements"]], [relevant["id"]])
        self.assertTrue(
            any("statement_membership" in q and "WHERE m.trade_id=" in q for q in queries)
        )
        self.assertFalse(any("SELECT * FROM recon_statements ORDER BY" in q for q in queries))

    def test_full_execution_has_exactly_one_financial_event(self):
        other = approved_trade(self.service, "full")
        done = self.service.command(
            other["id"], "settle", dict(version=other["version"]), principal=CHECKER
        )
        view = self.app.positions.snapshot(done["id"])
        self.assertEqual(len(view["event_history"]), 1)
        self.assertEqual(view["authoritative"]["gross_quantity"], 100)

    def test_invalid_position_envelope_is_blocked_without_inbox_commit(self):
        with self.service.store.transaction() as repo:
            repo.db.execute(
                "UPDATE position_outbox SET payload=?",
                (json.dumps(dict(trade_id=self.trade["id"], source_version=1)),),
            )
        result = self.app.positions.deliver_one("observer")
        self.assertEqual(result["status"], "BLOCKED")
        with self.service.store.read_transaction() as repo:
            self.assertEqual(
                repo.db.execute("SELECT COUNT(*) FROM position_inbox").fetchone()[0], 0
            )

    def test_position_schema_failure_rolls_back_new_tables(self):
        from settlementlab.infrastructure.position_schema import initialize_positions
        from settlementlab.infrastructure.store import SQLiteStore

        target = self.root / "migration-fault.db"

        def fail(db):
            initialize_positions(db)
            raise RuntimeError("position migration checkpoint")

        with (
            patch("settlementlab.infrastructure.schema.initialize_positions", side_effect=fail),
            self.assertRaises(RuntimeError),
        ):
            SQLiteStore(target)
        with sqlite3.connect(target) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0], 0
            )

    def test_expectation_validation_rejects_ambiguous_and_overfilled_plans(self):
        from settlementlab.assurance.bundle_audit import load_plan

        path = self.plan()
        original = json.loads(path.read_text())
        for field, value in [
            ("quantity", True),
            ("price_cents", 0),
            ("buyer_id", original["terms"]["seller_id"]),
        ]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                candidate = json.loads(json.dumps(original))
                candidate["terms"][field] = value
                path.write_text(json.dumps(candidate))
                load_plan(path)
        candidate = json.loads(json.dumps(original))
        candidate["executions"] *= 2
        path.write_text(json.dumps(candidate))
        with self.assertRaises(ValueError):
            load_plan(path)
        candidate = json.loads(json.dumps(original))
        candidate["compensations"] = ["UNKNOWN"]
        path.write_text(json.dumps(candidate))
        with self.assertRaises(ValueError):
            load_plan(path)

    def test_malformed_position_json_and_boolean_versions_are_not_retried(self):
        for payload in ("not json", "[]", json.dumps(dict(source_version=True))):
            with self.subTest(payload=payload):
                with self.service.store.transaction() as repo:
                    repo.db.execute(
                        "UPDATE position_outbox SET payload=?,status='PENDING'", (payload,)
                    )
                self.assertEqual(self.app.positions.deliver_one("observer")["status"], "BLOCKED")
        with self.service.store.read_transaction() as repo:
            self.assertEqual(
                repo.db.execute("SELECT COUNT(*) FROM position_inbox").fetchone()[0], 0
            )

    def test_expired_delivery_budget_stops_reclaiming_without_financial_changes(self):
        with self.service.store.transaction() as repo:
            for attempt in range(8):
                self.assertIsNotNone(repo.position_claim("crashed", 1000 + attempt, 0.1))
            self.assertIsNone(repo.position_claim("exhausted", 1009, 0.1))
        view = self.app.positions.snapshot(self.trade["id"])
        self.assertEqual(view["event_history"][0]["status"], "BLOCKED")
        self.assertIsNone(view["observed"])
        self.assertEqual(view["authoritative"]["gross_quantity"], 40)

    def test_large_external_plan_and_duplicate_manifest_keys_are_rejected(self):
        from settlementlab.assurance.bundle_audit import load_plan

        plan = self.root / "oversize.json"
        plan.write_bytes(b" " * 65537)
        with self.assertRaises(ValueError):
            load_plan(plan)
        path = self.root / "bundle.zip"
        path.write_bytes(export(self.service, self.trade["id"]))
        with zipfile.ZipFile(path) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        manifest = files["manifest.json"].decode()
        files["manifest.json"] = ('{"trade_id":"duplicate",' + manifest[1:]).encode()
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        with self.assertRaises(ValueError):
            verify(path)

    def test_wal_backup_is_closed_and_portable_before_return(self):
        import hashlib
        import shutil

        from settlementlab.infrastructure.backup import backup

        real_connect = sqlite3.connect
        connections = []

        def connect(*args, **kwargs):
            connection = real_connect(*args, **kwargs)
            connections.append(connection)
            return connection

        target = self.root / "portable.db"
        with self.service.store.read_transaction() as reader:
            old = reader.db.execute(
                "SELECT version FROM trades WHERE id=?", (self.trade["id"],)
            ).fetchone()[0]
            self.service.command(
                self.trade["id"],
                "settle-partial",
                dict(version=old, quantity=10, request_key="wal-frames"),
                principal=CHECKER,
            )
            self.assertTrue(Path(self.app.settings.database + "-wal").exists())
            with patch("settlementlab.infrastructure.backup.sqlite3.connect", side_effect=connect):
                result = backup(self.app.settings.database, target)
            for connection in connections:
                with self.assertRaises(sqlite3.ProgrammingError):
                    connection.execute("SELECT 1")
            self.assertFalse(Path(str(target) + "-wal").exists())
            self.assertFalse(Path(str(target) + "-shm").exists())
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), result["sha256"])
            restored = self.root / "separate-restore.db"
            shutil.copyfile(target, restored)
            with closing(real_connect(restored)) as db:
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "delete")
                self.assertEqual(
                    db.execute(
                        "SELECT quantity FROM settlements WHERE trade_id=?", (self.trade["id"],)
                    ).fetchone()[0],
                    50,
                )
