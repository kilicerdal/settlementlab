"""Independent expectations for two-sided matching, replay, and migration."""

import concurrent.futures
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from settlementlab.domain import DomainError, Ledger


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "matching.db"
        self.ledger = Ledger(self.path)
        self.terms = dict(
            symbol="NOVA",
            side="BUY",
            currency="USD",
            quantity=100,
            price="42.75",
            trade_date="2026-11-06",
            settlement_date="2026-11-09",
        )
        self.trade = self.ledger.create(dict(self.terms, matching_mode="two-sided"), "broker-1")

    def submit(self, terms=None, version=None, key="manager-1"):
        payload = dict(self.terms, allocations=[dict(account="SYN-A", quantity=100)])
        if terms:
            payload.update(terms)
        payload.update(
            version=self.trade["version"] if version is None else version, submission_key=key
        )
        return self.ledger.command(self.trade["id"], "manager", payload)

    def test_independent_terms_match_and_broker_is_preserved(self):
        self.assertIsNone(self.trade["manager_submission"])
        result = self.submit()
        self.assertEqual(result["state"], "MATCHED")
        self.assertEqual(result["matching"]["findings"], [])
        self.assertEqual(result["matching"]["compared_fields"], 7)
        self.assertEqual(result["matching"]["policy"], "equity-exact-v1")
        self.assertEqual(result["version"], 2)
        self.assertEqual(result["price_cents"], 4275)

    def test_each_field_has_an_independent_discrepancy(self):
        cases = [
            ("symbol", "LUMA", "symbol", "NOVA", "LUMA"),
            ("side", "SELL", "side", "BUY", "SELL"),
            ("quantity", 99, "quantity", 100, 99),
            ("price", "42.76", "price_cents", 4275, 4276),
            ("currency", "EUR", "currency", "USD", "EUR"),
            ("trade_date", "2026-11-05", "trade_date", "2026-11-06", "2026-11-05"),
            ("settlement_date", "2026-11-10", "settlement_date", "2026-11-09", "2026-11-10"),
        ]
        version = 1
        for index, (input_field, value, field, expected, observed) in enumerate(cases):
            with self.subTest(field=field):
                changed = {input_field: value}
                if input_field == "quantity":
                    changed["allocations"] = [dict(account="SYN-A", quantity=99)]
                result = self.submit(changed, version, key="case-" + str(index))
                version = result["version"]
                self.assertEqual(result["state"], "EXCEPTION")
                self.assertEqual(len(result["matching"]["findings"]), 1)
                finding = result["matching"]["findings"][0]
                self.assertEqual(
                    (finding["field"], finding["expected"], finding["observed"]),
                    (field, expected, observed),
                )
        self.assertEqual(result["price_cents"], 4275)

    def test_allocation_total_is_distinct_from_trade_quantity(self):
        result = self.submit(dict(allocations=[dict(account="SYN-A", quantity=99)]))
        self.assertEqual(result["matching"]["findings"][0]["code"], "ALLOCATION_TOTAL_MISMATCH")
        self.assertEqual(result["manager_submission"]["quantity"], 100)

    def test_correction_preserves_revision_history(self):
        broken = self.submit(dict(price="42.76"))
        corrected = self.submit(version=broken["version"], key="correction")
        self.assertEqual(corrected["state"], "MATCHED")
        self.assertEqual(
            [s["terms"]["price_cents"] for s in corrected["submission_history"]], [4276, 4275]
        )
        self.assertEqual([s["revision"] for s in corrected["submission_history"]], [1, 2])
        reopened = Ledger(self.path).snapshot()["trades"][0]
        self.assertEqual(reopened["submission_history"], corrected["submission_history"])

    def test_replay_returns_original_result_even_after_correction(self):
        broken = self.submit(dict(price="42.76"))
        self.submit(version=broken["version"], key="correction")
        replay = self.submit(dict(price="42.76"), version=999)
        self.assertEqual(replay, broken)
        current = self.ledger.snapshot()["trades"][0]
        self.assertEqual(current["state"], "MATCHED")
        self.assertEqual(len(current["submission_history"]), 2)
        with self.assertRaises(DomainError):
            self.submit()

    def test_no_legacy_bypass_and_affirmation_locks_revisions(self):
        with self.assertRaises(DomainError):
            self.ledger.command(
                self.trade["id"],
                "allocate",
                dict(version=1, allocations=[dict(account="A", quantity=100)]),
            )
        matched = self.submit()
        affirmed = self.ledger.command(
            matched["id"], "affirm", dict(version=matched["version"], instruction="SYN-CUSTODY")
        )
        with self.assertRaises(DomainError):
            self.submit(version=affirmed["version"], key="too-late")
        self.assertEqual(self.ledger.snapshot()["trades"][0]["state"], "AFFIRMED")

    def test_invalid_submission_rolls_back(self):
        before = self.ledger.snapshot()
        for terms in [
            dict(side=None),
            dict(price="42.755"),
            dict(settlement_date="2026-11-01"),
            dict(allocations=[dict(account="A", quantity=50), dict(account=" A ", quantity=50)]),
        ]:
            with self.subTest(terms=terms):
                with self.assertRaises(DomainError):
                    self.submit(terms)
                self.assertEqual(self.ledger.snapshot(), before)

    def test_manager_must_supply_complete_terms(self):
        with self.assertRaises(DomainError):
            self.ledger.command(
                self.trade["id"],
                "manager",
                dict(version=1, submission_key="incomplete", quantity=100),
            )
        self.assertEqual(self.ledger.snapshot()["trades"][0]["version"], 1)

    def test_concurrent_distinct_revisions_reject_stale_writer(self):
        def send(index):
            try:
                return self.submit(key="parallel-" + str(index))["state"]
            except DomainError as error:
                return error.status

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(send, range(2))), ["MATCHED", 409])
        self.assertEqual(len(self.ledger.snapshot()["trades"][0]["submission_history"]), 1)

    def test_concurrent_same_key_is_one_revision(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.submit(), range(8)))
        self.assertTrue(all(r == results[0] for r in results))
        self.assertEqual(len(self.ledger.snapshot()["trades"][0]["submission_history"]), 1)

    def test_evidence_contains_break_facts_without_accounts(self):
        broken = self.submit(dict(price="42.76"))
        evidence = self.ledger.evidence(broken["id"], broken["version"])
        facts = {fact["id"]: fact["value"] for fact in evidence["facts"]}
        self.assertEqual(
            facts["break:price_cents"],
            dict(expected=4275, observed=4276, rule_id="equity-exact-v1:PRICE"),
        )
        self.assertNotIn("SYN-A", json.dumps(evidence))


class MigrationTests(unittest.TestCase):
    def test_existing_v1_database_and_replay_survive_upgrade(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "old.db"
            with sqlite3.connect(path) as db:
                db.execute("""CREATE TABLE trades(id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
                  fingerprint TEXT NOT NULL,symbol TEXT NOT NULL,quantity INTEGER NOT NULL,
                  price_cents INTEGER NOT NULL,trade_date TEXT NOT NULL,settlement_date TEXT NOT NULL,
                  state TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,allocations TEXT NOT NULL DEFAULT '[]',
                  instruction TEXT,reason TEXT,cash_cents INTEGER NOT NULL DEFAULT 0,securities INTEGER NOT NULL DEFAULT 0)""")
                db.execute(
                    "INSERT INTO trades(id,request_key,fingerprint,symbol,quantity,price_cents,trade_date,settlement_date,state) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        "SL-000001",
                        "old-key",
                        json.dumps(["NOVA", 100, 4275, "2026-11-06"]),
                        "NOVA",
                        100,
                        4275,
                        "2026-11-06",
                        "2026-11-09",
                        "RECEIVED",
                    ),
                )
            upgraded = Ledger(path)
            replay = upgraded.create(
                dict(symbol="NOVA", quantity=100, price="42.75", trade_date="2026-11-06"), "old-key"
            )
            self.assertEqual(replay["matching_mode"], "allocation-only")
            self.assertEqual(replay["id"], "SL-000001")
            self.assertEqual(Ledger(path).snapshot()["trades"][0]["version"], 1)
