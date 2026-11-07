import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from urllib.error import URLError

from settlementlab.assurance.http_steps import resolve
from settlementlab.assurance.targets import TargetProfile
from settlementlab.assurance.transport import JsonClient, TransportError


class TargetTransportControls(unittest.TestCase):
    def test_profile_precedence_and_unsafe_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "target.json"
            path.write_text(
                json.dumps(dict(target="collateral", base_url="http://127.0.0.1:8090", timeout=5))
            )
            profile = TargetProfile.load(path, {"SETTLEMENTLAB_TIMEOUT": "3"}, timeout=2)
            self.assertEqual(profile.timeout, 2)
            self.assertEqual(profile.target, "collateral")
        for url in [
            "file:///tmp/example",
            "https://user:password@example.com",
            "https://example.com?token=value",
            "http://",
            "http://localhost:99999",
        ]:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    JsonClient(url)
        for timeout in [True, 0, 61, float("nan"), float("inf")]:
            with self.assertRaises(ValueError):
                TargetProfile("collateral", "http://localhost:8090", timeout)

    def test_connection_and_timeout_are_typed_without_credentials(self):
        for error, kind in [(TimeoutError(), "timeout"), (URLError("refused"), "connection")]:
            client = JsonClient("http://127.0.0.1:8090")
            client.opener = Mock()
            client.opener.open.side_effect = error
            with self.assertRaises(TransportError) as failure:
                client.request("/health")
            self.assertEqual(failure.exception.kind, kind)
            self.assertEqual(client.last_exchange["path"], "/health")
            self.assertIsNone(client.last_exchange["status"])

    def test_diagnostics_omit_query_headers_and_body(self):
        client = JsonClient("http://127.0.0.1:8090")
        client.opener = Mock()
        client.opener.open.side_effect = TimeoutError()
        with self.assertRaises(TransportError):
            client.request("/health?token=secret", {"password": "secret"}, "secret")
        self.assertEqual(client.last_exchange["path"], "/health")
        self.assertNotIn("secret", str(client.last_exchange))

    def test_relative_paths_and_template_resolution(self):
        client = JsonClient("http://127.0.0.1:8090")
        for path in ["//other/route", "https://other/route", "health"]:
            with self.assertRaises(ValueError):
                client.request(path)
        context = dict(reservation=dict(id="R-001"), run_id="TEST")
        self.assertEqual(
            resolve("/reservations/${reservation.id}/release", context),
            "/reservations/R-001/release",
        )
        self.assertEqual(resolve({"$ref": "reservation.id"}, context), "R-001")
        with self.assertRaises(KeyError):
            resolve({"$ref": "missing.id"}, context)

    def test_configuration_failure_has_report_and_nonzero_exit(self):
        from settlementlab.assurance.runner import main

        with tempfile.TemporaryDirectory() as directory:
            result = main(
                ["--suite", "scenarios", "--target", "collateral", "--report-dir", directory]
            )
            self.assertEqual(result, 2)
            report = json.loads((Path(directory) / "results.json").read_text())
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["cases"][0]["id"], "runner.configuration")
