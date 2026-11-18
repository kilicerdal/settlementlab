import unittest

from settlementlab.assurance.durable_data import approved_trade, entry, fund_trade
from settlementlab.assurance.fixtures import LocalEnvironment
from settlementlab.assurance.transport import APIError


class DurableAPI(unittest.TestCase):
    def test_checker_only_batch_and_token_free_replay(self):
        with LocalEnvironment() as env:
            trade = approved_trade(env.app.service)
            data = dict(trades=[entry(trade)])
            with self.assertRaises(APIError) as missing:
                env.client.request("/api/operations/batches", dict(data, role="checker"), "batch")
            self.assertIn(missing.exception.status, (403, 422))
            for persona in ["maker-alex", "auditor-casey"]:
                env.client.use_persona(persona)
                with self.assertRaises(APIError) as denied:
                    env.client.request("/api/operations/batches", data, "batch")
                self.assertEqual(denied.exception.status, 403)
            env.client.use_persona("checker-sam")
            batch = env.client.request("/api/operations/batches", data, "batch")
            self.assertEqual(env.client.last_exchange["status"], 202)
            self.assertFalse(batch["replayed"])
            self.assertEqual(len(batch["jobs"]), 1)
            env.app.operations.claim("private-worker")
            replay = env.client.request("/api/operations/batches", data, "batch")
            self.assertTrue(replay["replayed"])
            self.assertNotIn("lease_token", replay["jobs"][0])
            snapshot = env.client.request("/api/operations")
            self.assertEqual(snapshot["totals"]["RUNNING"], 1)
            self.assertNotIn("lease_token", snapshot["jobs"][0])
            with self.assertRaises(APIError):
                env.client.request(
                    "/api/operations/batches", dict(trades=[entry(trade)], max_attempts=4), "batch"
                )

    def test_reviewed_http_requeue_and_event_deduplication(self):
        with LocalEnvironment() as env:
            trade = approved_trade(env.app.service, funded=False)
            env.client.use_persona("checker-sam")
            batch = env.client.request(
                "/api/operations/batches", dict(trades=[entry(trade)]), "capacity-job"
            )
            dead = env.app.operations.process_one("underfunded")
            self.assertEqual(dead["status"], "DEAD_LETTER")
            current = env.app.service.snapshot()["trades"][0]
            fund_trade(env.app.service, current, "review-funding")
            path = "/api/operations/jobs/" + batch["jobs"][0]["id"] + "/requeue"
            env.client.use_persona("auditor-casey")
            with self.assertRaises(APIError) as denied:
                env.client.request(
                    path, dict(version=current["version"], reason="Reviewed funding")
                )
            self.assertEqual(denied.exception.status, 403)
            env.client.use_persona("checker-sam")
            queued = env.client.request(
                path, dict(version=current["version"], reason="Reviewed synthetic funding")
            )
            self.assertEqual(queued["generation"], 2)
            env.app.operations.process_one("recovered")
            event = env.app.operations.deliver_one("observer")
            self.assertEqual(event["status"], "DELIVERED")
            env.app.operations.deliver_one("observer")
            replay = env.client.request(
                "/api/operations/events/" + event["event_id"] + "/redeliver", {}
            )
            self.assertFalse(replay["applied"])
            with self.assertRaises(APIError) as invalid:
                env.client.request(
                    "/api/operations/events/" + event["event_id"] + "/retry",
                    dict(reason="Reviewed"),
                )
            self.assertEqual(invalid.exception.status, 409)
            self.assertEqual(env.app.operations.snapshot()["inbox_count"], 2)

    def test_assets_and_no_http_worker_fault_surface(self):
        from urllib.request import urlopen

        with LocalEnvironment() as env:
            for path, mime in [
                ("/operations", "text/html"),
                ("/operations.js", "text/javascript"),
                ("/operations.css", "text/css"),
            ]:
                with urlopen(env.base_url + path) as response:
                    self.assertIn(mime, response.headers["Content-Type"])
                    self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
            with self.assertRaises(APIError) as forbidden:
                env.client.request("/api/operations/worker/kill", {})
            self.assertEqual(forbidden.exception.status, 404)
            self.assertEqual(env.client.request("/api/operations")["totals"], {})
