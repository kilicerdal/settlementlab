"""Public investigation, portable export, correction and optional AI boundaries."""

import io
import json
import unittest
import zipfile
from urllib.request import urlopen

from settlementlab.assurance.client import APIError
from settlementlab.assurance.durable_data import CHECKER, approved_trade
from settlementlab.assurance.fixtures import LocalEnvironment


class InvestigationAPI(unittest.TestCase):
    def setUp(self):
        self.environment = LocalEnvironment().__enter__()
        self.addCleanup(self.environment.__exit__, None, None, None)
        self.client = self.environment.client
        self.trade = approved_trade(self.environment.app.service)
        self.trade = self.environment.app.service.command(
            self.trade["id"],
            "settle-partial",
            dict(version=self.trade["version"], quantity=20, request_key="slice"),
            principal=CHECKER,
        )
        self.path = "/api/trades/" + self.trade["id"]

    def test_snapshot_export_and_assets(self):
        graph = self.client.request(self.path + "/investigation")
        self.assertEqual(graph["trade"]["net_settled_quantity"], 20)
        self.assertGreater(len(graph["correlations"]), 0)
        with urlopen(self.environment.base_url + self.path + "/incident-export") as response:
            self.assertEqual(response.headers["Content-Type"], "application/zip")
            data = response.read()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(
                set(archive.namelist()), {"index.html", "incident.json", "manifest.json"}
            )
        for path in ("/investigation", "/investigation.js", "/investigation.css"):
            with urlopen(self.environment.base_url + path) as response:
                self.assertEqual(response.status, 200)

    def test_correction_maker_checker_role_and_header_key(self):
        data = dict(
            version=self.trade["version"],
            original_batch=self.trade["execution_slices"][0]["batch_id"],
            reason="Review synthetic correction request",
        )
        self.client.use_persona("checker-sam")
        with self.assertRaises(APIError) as error:
            self.client.request(self.path + "/request-reversal", data, "reversal")
        self.assertEqual(error.exception.status, 403)
        self.client.use_persona("maker-alex")
        request = self.client.request(self.path + "/request-reversal", data, "reversal")
        graph = self.client.request(self.path + "/investigation")
        decision = dict(
            version=graph["trade"]["version"],
            reversal_id=request["id"],
            reason="Independent review confirms exact compensation",
        )
        with self.assertRaises(APIError):
            self.client.request(self.path + "/approve-reversal", decision)
        self.client.use_persona("checker-sam")
        self.assertEqual(
            self.client.request(self.path + "/approve-reversal", decision)["status"], "APPROVED"
        )
        self.assertEqual(
            self.client.request(self.path + "/investigation")["trade"]["net_settled_quantity"], 0
        )

    def test_ai_disabled_stale_context_and_grounded_read_only_response(self):
        self.client.use_persona("checker-sam")
        data = dict(version=self.trade["version"])
        with self.assertRaises(APIError) as error:
            self.client.request(self.path + "/investigate-ai", data)
        self.assertEqual(error.exception.status, 503)
        self.environment.app.triage.model = "fixture-only"

        def transport(payload):
            evidence = json.loads(payload["messages"][1]["content"])
            fact = evidence["observations"][0]
            result = dict(
                summary="The retained evidence records a partial execution.",
                claims=[dict(code=fact["code"], evidence_ids=fact["evidence_ids"])],
                abstained=False,
                uncertainty="Underlying cause is not established by supplied evidence.",
            )
            return dict(done=True, message=dict(content=json.dumps(result)))

        self.environment.app.triage.transport = transport
        before = self.environment.app.service.snapshot()
        result = self.client.request(self.path + "/investigate-ai", data)
        self.assertTrue(result["advisory_only"])
        self.assertEqual(self.environment.app.service.snapshot(), before)
        with self.assertRaises(APIError) as error:
            self.client.request(self.path + "/investigate-ai", dict(version=1))
        self.assertEqual(error.exception.status, 409)
