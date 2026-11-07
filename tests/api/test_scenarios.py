import copy
import unittest
from pathlib import Path

from settlementlab.assurance.data import TradeFactory
from settlementlab.assurance.fixtures import LocalEnvironment
from settlementlab.assurance.scenarios import catalog, run_scenario


class ScenarioControls(unittest.TestCase):
    def test_bad_expectation_fails_with_exact_step(self):
        spec = copy.deepcopy(catalog()[0])
        spec["steps"][-1]["assert"]["state"] = "IMPOSSIBLE"
        result = run_scenario(spec)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["steps"][-1]["status"], "failed")
        self.assertIn("IMPOSSIBLE", result["detail"])

    def test_unknown_action_never_runs(self):
        with self.assertRaises(ValueError):
            run_scenario(dict(id="invalid", steps=[dict(action="shell")]))

    def test_environment_removes_database_and_isolates_clients(self):
        with LocalEnvironment() as first:
            path = Path(first.database)
            factory = TradeFactory()
            first.client.use_persona("maker-alex")
            first.client.create(factory.broker(), factory.key())
            self.assertTrue(path.exists())
            with LocalEnvironment() as second:
                self.assertEqual(second.client.request("/api/snapshot")["trades"], [])
                self.assertIsNone(second.client.request("/api/session")["principal"])
        self.assertFalse(path.exists())
        self.assertFalse(first.thread.is_alive())
