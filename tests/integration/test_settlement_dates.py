import tempfile
import unittest
from pathlib import Path

from settlementlab.core.calendar import BusinessCalendar, FixedClock
from settlementlab.core.identity import Principal
from settlementlab.domain import DomainError, Ledger

MAKER = Principal("maker-alex", "maker")
CHECKER = Principal("checker-sam", "checker")


class SettlementDateControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = Ledger(Path(self.temp.name) / "dates.db", clock=FixedClock("2026-11-06"))
        self.terms = dict(
            symbol="NOVA",
            side="BUY",
            currency="USD",
            quantity=100,
            price="42.75",
            trade_date="2026-11-06",
            settlement_date="2026-11-09",
        )

    def ready(self):
        t = self.ledger.create(
            dict(self.terms, matching_mode="two-sided", settlement_model="shared-ledger"),
            "trade",
            principal=MAKER,
        )
        t = self.ledger.command(
            t["id"],
            "manager",
            dict(
                self.terms,
                version=t["version"],
                submission_key="manager",
                allocations=[dict(account="SYN-A", quantity=100)],
            ),
            principal=MAKER,
        )
        t = self.ledger.command(
            t["id"],
            "request-affirmation",
            dict(version=t["version"], request_key="review", instruction="SYN-CUSTODY"),
            principal=MAKER,
        )
        t = self.ledger.command(
            t["id"],
            "approve",
            dict(version=t["version"], approval_id=t["pending_approval"]["id"]),
            principal=CHECKER,
        )
        for party, asset, amount in [
            ("SYN-ALPHA", "CASH:USD", 427500),
            ("SYN-BROKER", "SEC:NOVA", 100),
        ]:
            self.ledger.fund_participant(
                dict(participant_id=party, asset=asset, amount=amount), asset, CHECKER
            )
        return t

    def test_early_rejection_preserves_state_journal_and_audit(self):
        t = self.ready()
        before = self.ledger.snapshot()
        self.assertIn(
            "NOT_DUE", [b["code"] for b in self.ledger.settlement_readiness(t["id"])["blockers"]]
        )
        with self.assertRaises(DomainError) as error:
            self.ledger.command(t["id"], "settle", dict(version=t["version"]), principal=CHECKER)
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.ledger.snapshot(), before)
        self.ledger.clock = FixedClock("2026-11-09")
        self.assertTrue(self.ledger.settlement_readiness(t["id"])["eligible"])
        settled = self.ledger.command(
            t["id"], "settle", dict(version=t["version"]), principal=CHECKER
        )
        self.assertEqual(settled["state"], "SETTLED")

    def test_closed_business_date_blocks_late_settlement(self):
        t = self.ready()
        self.ledger.clock = FixedClock("2026-11-14")
        before = self.ledger.snapshot()
        with self.assertRaises(DomainError):
            self.ledger.command(t["id"], "settle", dict(version=t["version"]), principal=CHECKER)
        self.assertEqual(self.ledger.snapshot(), before)

    def test_calendar_pin_survives_configuration_change(self):
        t = self.ready()
        pin = t["calendar_policy"]
        self.ledger.calendar = BusinessCalendar("changed", ("2026-11-09",))
        self.ledger.clock = FixedClock("2026-11-09")
        readiness = self.ledger.settlement_readiness(t["id"])
        self.assertEqual(readiness["calendar"]["id"], "weekday-v1")
        self.assertTrue(readiness["eligible"])
        self.assertEqual(self.ledger.snapshot()["trades"][0]["calendar_policy"], pin)

    def test_new_trade_uses_configured_closure_and_replay_remains_valid(self):
        self.ledger.calendar = BusinessCalendar("demo-closure", ("2026-11-09",))
        with self.assertRaises(DomainError):
            self.ready()
        self.terms["settlement_date"] = "2026-11-10"
        t = self.ready()
        self.assertEqual(t["settlement_date"], "2026-11-10")
        self.ledger.calendar = BusinessCalendar()
        replay = self.ledger.create(
            dict(self.terms, matching_mode="two-sided", settlement_model="shared-ledger"),
            "trade",
            principal=MAKER,
        )
        self.assertEqual(replay["calendar_policy"], t["calendar_policy"])
