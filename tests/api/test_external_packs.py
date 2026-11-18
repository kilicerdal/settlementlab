"""User-owned packs work without source edits; invalid packs send no requests."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from examples.collateral_service.server import Inventory, handler
from settlementlab.assurance.catalogs import load_external
from settlementlab.assurance.fixtures import HTTPEnvironment
from settlementlab.assurance.runner import main


class ExternalPacks(unittest.TestCase):
    def test_user_pack_runs_with_custom_target_and_saved_response(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pack = root / "my-pack"
            pack.mkdir()
            sample = (
                Path(__file__).resolve().parents[2]
                / "examples/scenario_packs/inventory/reservation.json"
            )
            (pack / "scenario.json").write_bytes(sample.read_bytes())
            with HTTPEnvironment(handler(Inventory(root / "own.db"))) as env:
                code = main(
                    [
                        "--suite",
                        "scenarios",
                        "--target",
                        "my-api",
                        "--base-url",
                        env.base_url,
                        "--scenario-dir",
                        str(pack),
                        "--report-dir",
                        str(root / "reports"),
                    ]
                )
            self.assertEqual(code, 0)
            report = json.loads((root / "reports/results.json").read_text())
            self.assertEqual(report["cases"][0]["control"], "reservation-once")
            self.assertEqual(report["cases"][0]["source"], "scenario.json")
            self.assertEqual(report["cases"][0]["steps"][2]["control"], "replay-original-id")
            self.assertNotIn(str(pack), json.dumps(report))

    def test_pack_preflight_rejects_every_file_before_network_access(self):
        sample = dict(id="MY-01", title="My contract", steps=[dict(action="http", path="/health")])
        invalids = [
            dict(sample, unexpected=True),
            dict(sample, steps=[]),
            dict(sample, steps=[dict(action="shell", path="/health")]),
            dict(sample, steps=[dict(action="http", path="//different-host")]),
            dict(sample, steps=[dict(action="http", path="/${missing.id}")]),
            dict(
                sample,
                steps=[dict(action="http", path="/health", data={"x": {"$ref": "future.id"}})],
            ),
            dict(sample, steps=[dict(action="http", path="/health", status=True)]),
            dict(sample, target="another-target"),
        ]
        for invalid in invalids:
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                pack = root / "pack"
                pack.mkdir()
                (pack / "a.json").write_text(json.dumps(sample))
                (pack / "b.json").write_text(json.dumps(invalid))
                with patch(
                    "settlementlab.assurance.transport.JsonClient.request",
                    side_effect=AssertionError("Network forbidden"),
                ) as request:
                    self.assertEqual(
                        main(
                            [
                                "--suite",
                                "scenarios",
                                "--target",
                                "my-api",
                                "--base-url",
                                "http://127.0.0.1:1",
                                "--scenario-dir",
                                str(pack),
                                "--report-dir",
                                str(root / "reports"),
                            ]
                        ),
                        1,
                    )
                    request.assert_not_called()
                self.assertEqual(
                    json.loads((root / "reports/results.json").read_text())["status"], "failed"
                )

    def test_loader_limits_duplicates_and_plain_json_contract(self):
        sample = dict(id="X", title="Example", steps=[dict(action="http", path="/health")])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            p = root / "a.json"
            with self.assertRaises(ValueError):
                load_external(root, "custom")
            p.write_text(json.dumps(sample))
            (root / "b.json").write_text(json.dumps(sample))
            with self.assertRaisesRegex(ValueError, "Duplicate scenario"):
                load_external(root, "custom")
            (root / "b.json").unlink()
            p.write_text('{"id":"X","id":"Y"}')
            with self.assertRaisesRegex(ValueError, "Duplicate JSON"):
                load_external(root, "custom")
            p.write_text(
                json.dumps(
                    dict(sample, steps=[dict(action="http", path="/x", data={"v": float("nan")})])
                )
            )
            with self.assertRaisesRegex(ValueError, "Non-finite"):
                load_external(root, "custom")
            p.write_text(" " * 65537)
            with self.assertRaisesRegex(ValueError, "64 KiB"):
                load_external(root, "custom")
            p.unlink()
            outside = root / "outside.txt"
            outside.write_text(json.dumps(sample))
            p.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "regular JSON"):
                load_external(root, "custom")
            p.unlink()
            p.write_text(json.dumps(sample))
            with self.assertRaisesRegex(ValueError, "non-settlement"):
                load_external(root, "settlement")
            self.assertEqual(load_external(root, "custom")[0]["target"], "custom")

    def test_broken_replay_implementation_fails_same_external_pack(self):
        sample = Path(__file__).resolve().parents[2] / "examples/scenario_packs/inventory"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with HTTPEnvironment(handler(Inventory(root / "fault.db", True))) as env:
                code = main(
                    [
                        "--suite",
                        "scenarios",
                        "--target",
                        "custom",
                        "--base-url",
                        env.base_url,
                        "--scenario-dir",
                        str(sample),
                        "--report-dir",
                        str(root / "reports"),
                    ]
                )
            self.assertEqual(code, 1)
            failure = json.loads((root / "reports/results.json").read_text())["cases"][0]["steps"][
                -1
            ]
            self.assertEqual(failure["failure"], dict(kind="http_status", expected=200, actual=201))
            self.assertEqual(failure["control"], "replay-original-id")
