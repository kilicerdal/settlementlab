import unittest

from settlementlab.assurance.client import APIError
from settlementlab.assurance.data import TradeFactory
from settlementlab.assurance.fixtures import LocalEnvironment


class ReadinessAPIControls(unittest.TestCase):
    def test_readiness_exposes_actual_clock_and_preserves_records(self):
        with LocalEnvironment(business_date="2026-11-06") as environment:
            client = environment.client
            factory = TradeFactory()
            client.use_persona("maker-alex")
            trade = client.create(factory.broker(), factory.key())
            before = client.request("/api/snapshot")
            result = client.request("/api/trades/" + trade["id"] + "/readiness")
            self.assertEqual(
                result["business_time"],
                dict(mode="simulated", date="2026-11-06", timezone="date-only"),
            )
            self.assertFalse(result["eligible"])
            self.assertIn("NOT_DUE", [b["code"] for b in result["blockers"]])
            self.assertEqual(client.request("/api/snapshot"), before)
            with self.assertRaises(APIError) as error:
                client.request("/api/trades/UNKNOWN/readiness")
            self.assertEqual(error.exception.status, 404)
