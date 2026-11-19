"""Public HTTP authorization, replay headers and immutable reconciliation evidence."""

import unittest

from settlementlab.assurance.client import APIError
from settlementlab.assurance.durable_data import approved_trade
from settlementlab.assurance.fixtures import LocalEnvironment


class LifecycleAPI(unittest.TestCase):
    def setUp(self):
        self.environment = LocalEnvironment().__enter__()
        self.addCleanup(self.environment.__exit__, None, None, None)
        self.client = self.environment.client
        self.trade = approved_trade(self.environment.app.service)

    def test_role_and_key_required_before_partial_posting(self):
        path = "/api/trades/" + self.trade["id"] + "/settle-partial"
        data = dict(version=self.trade["version"], quantity=20)
        self.client.use_persona("maker-alex")
        with self.assertRaises(APIError) as error:
            self.client.request(path, data, "maker-key")
        self.assertEqual(error.exception.status, 403)
        self.client.use_persona("checker-sam")
        with self.assertRaises(APIError) as error:
            self.client.request(path, data)
        self.assertEqual(error.exception.status, 422)
        first = self.client.request(path, data, "slice")
        self.assertEqual(first["settled_quantity"], 20)
        self.assertEqual(self.client.request(path, data, "slice"), first)
        with self.assertRaises(APIError) as error:
            self.client.request(path, dict(data, quantity=21), "slice")
        self.assertEqual(error.exception.status, 409)

    def test_import_requires_checker_and_rejects_malformed_csv(self):
        self.client.use_persona("maker-alex")
        with self.assertRaises(APIError) as error:
            self.client.request("/api/reconciliation/statements", dict(statement=[]), "statement")
        self.assertEqual(error.exception.status, 403)
        self.client.use_persona("checker-sam")
        with self.assertRaises(APIError) as error:
            self.client.request(
                "/api/reconciliation/statements", dict(statement="bad header"), "bad"
            )
        self.assertEqual(error.exception.status, 422)
        imported = self.client.request(
            "/api/reconciliation/statements",
            dict(statement=[dict(trade_id="EXTERNAL-ONLY", quantity=1, amount_cents=100)]),
            "statement",
        )
        self.assertEqual(imported["cases"][0]["kind"], "MISSING_INTERNAL")
        evidence = self.client.request("/api/reconciliation/statements/" + imported["id"])
        self.assertEqual(evidence["rows"][0]["quantity"], 1)
        self.assertEqual(evidence["internal_snapshot"], [])
        case = imported["cases"][0]
        with self.assertRaises(APIError) as error:
            self.client.request(
                "/api/reconciliation/cases/" + case["id"] + "/resolve",
                dict(statement_id=imported["id"], reason="Original statement still differs"),
            )
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.client.request("/api/reconciliation")["cases"][0]["status"], "OPEN")
