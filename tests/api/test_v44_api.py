"""Public financial-position snapshots and explicit reconciliation bases."""

import json
import unittest

from settlementlab.assurance.durable_data import CHECKER, approved_trade
from settlementlab.assurance.fixtures import LocalEnvironment


class ConsistencyAPI(unittest.TestCase):
    def test_position_snapshot_and_accounting_basis_contracts(self):
        with LocalEnvironment() as env:
            trade = approved_trade(env.app.service)
            trade = env.app.service.command(
                trade["id"],
                "settle-partial",
                dict(version=trade["version"], quantity=10, request_key="post"),
                principal=CHECKER,
            )
            position = env.client.request("/api/trades/" + trade["id"] + "/position")
            self.assertEqual(position["status"], "LAGGING")
            self.assertIsNone(position["observed"])
            env.app.positions.deliver_one("observer")
            self.assertEqual(
                env.client.request("/api/trades/" + trade["id"] + "/position")["observed"][
                    "net_quantity"
                ],
                10,
            )
            env.client.use_persona("checker-sam")
            statement = [dict(trade_id=trade["id"], quantity=10, amount_cents=42750)]
            net = env.client.request(
                "/api/reconciliation/statements", dict(statement=statement), "net"
            )
            gross = env.client.request("/api/reconcile", dict(statement=statement))
            self.assertEqual(net["accounting_basis"], "NET_AFTER_APPROVED_COMPENSATIONS")
            self.assertEqual(gross["accounting_basis"], "GROSS_EXECUTED_RECEIPTS")
            self.assertEqual(gross["migration_target"], "/api/reconciliation/statements")
            with env.app.service.store.transaction() as repo:
                claimed = repo.position_claim("nothing", 0, 30)
            self.assertIsNone(claimed)
            self.assertNotIn("lease_token", json.dumps(position))
