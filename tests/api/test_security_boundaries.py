"""Concrete local-demo abuse cases, not a penetration-test certification."""

import json
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from settlementlab.assurance.durable_data import approved_trade, entry
from settlementlab.assurance.fixtures import LocalEnvironment


class SecurityBoundaries(unittest.TestCase):
    def test_rejected_inputs_cannot_mutate_financial_or_operation_state(self):
        with LocalEnvironment() as env:
            trade = approved_trade(env.app.service)
            before = env.app.service.snapshot()
            cases = [
                ("/api/operations/batches", b'{"trades":[],"trades":[]}', {}, 400),
                ("/api/operations/batches", b'{"max_attempts":NaN}', {}, 400),
                ("/api/operations/batches", b"[]", {}, 422),
                ("/api/operations/batches", b"x" * 65537, {}, 413),
                ("/api/operations/batches", b"{}", {"Origin": "https://attacker.invalid"}, 403),
                ("/api/operations/batches", b"{}", {"Host": "attacker.invalid"}, 400),
                ("/api/operations/batches", b"{}", {"Host": "127.0.0.1@attacker.invalid"}, 400),
                (
                    "/api/operations/batches",
                    json.dumps(dict(trades=[entry(trade)])).encode(),
                    {"Cookie": "settlementlab_session=checker-sam", "Idempotency-Key": "forged"},
                    403,
                ),
                (
                    "/api/operations/jobs/unknown/requeue",
                    b'{"reason":"review","version":1,"role":"checker"}',
                    {},
                    422,
                ),
                (
                    "/api/operations/events/unknown/retry",
                    b'{"reason":"review","role":"checker"}',
                    {},
                    422,
                ),
                ("/api/operations/events/unknown/redeliver", b'{"role":"checker"}', {}, 422),
            ]
            for path, body, headers, status in cases:
                with self.subTest(path=path, headers=headers, body=body[:60]):
                    request = Request(
                        env.base_url + path,
                        data=body,
                        headers={"Content-Type": "application/json", **headers},
                    )
                    with self.assertRaises(HTTPError) as error:
                        urlopen(request, timeout=5)
                    self.assertEqual(error.exception.code, status)
                    self.assertEqual(env.app.service.snapshot(), before)
                    self.assertEqual(env.app.operations.snapshot()["jobs"], [])

    def test_read_host_headers_asset_paths_and_no_lease_secret(self):
        with LocalEnvironment() as env:
            with self.assertRaises(HTTPError) as error:
                urlopen(
                    Request(env.base_url + "/api/health", headers={"Host": "evil.invalid"}),
                    timeout=5,
                )
            self.assertEqual(error.exception.code, 400)
            for path in ["/operations", "/operations.js", "/operations.css", "/api/operations"]:
                with urlopen(env.base_url + path, timeout=5) as response:
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    self.assertIn(
                        "frame-ancestors 'none'", response.headers["Content-Security-Policy"]
                    )
            for path in ["/../../pyproject.toml", "/.git/config", "/api/operations/kill"]:
                with self.assertRaises(HTTPError) as error:
                    urlopen(env.base_url + path, timeout=5)
                self.assertEqual(error.exception.code, 404)
