"""Reuse checks against an independently implemented API and injected defect."""

import copy
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from examples.collateral_service.server import Inventory, handler
from settlementlab.assurance.fixtures import HTTPEnvironment
from settlementlab.assurance.runner import main, run
from settlementlab.assurance.scenarios import catalog, run_scenario
from settlementlab.assurance.targets import TargetProfile


@contextmanager
def collateral(fault=False):
    with tempfile.TemporaryDirectory() as directory:
        store = Inventory(Path(directory) / "inventory.db", fault)
        with HTTPEnvironment(handler(store)) as environment:
            yield store, environment


class ReuseControls(unittest.TestCase):
    def test_second_target_reuses_engine_without_starting_settlement(self):
        with collateral() as (_, environment):
            with patch(
                "settlementlab.bootstrap.create_application",
                side_effect=AssertionError("Financial application must not start"),
            ):
                for spec in catalog("collateral"):
                    result = run_scenario(spec, environment.base_url)
                    self.assertEqual(result["status"], "passed", result)
                    self.assertEqual(result["target"], "collateral")
                    self.assertTrue(all("request" in step for step in result["steps"]))
                    self.assertTrue(
                        all("headers" not in step["request"] for step in result["steps"])
                    )

    def test_injected_duplicate_replay_fails_report_and_exit_gate(self):
        with collateral(True) as (store, environment), tempfile.TemporaryDirectory() as directory:
            report = run(
                "scenarios", ".", directory, TargetProfile("collateral", environment.base_url)
            )
            self.assertEqual(report["status"], "failed")
            failure = next(case for case in report["cases"] if case["status"] == "failed")
            step = failure["steps"][-1]
            self.assertEqual(step["failure"], dict(kind="http_status", expected=200, actual=201))
            self.assertEqual(step["request"]["path"], "/reservations")
            xml = ElementTree.parse(Path(directory) / "junit.xml").getroot()
            self.assertEqual(xml.attrib["failures"], "1")
            self.assertIn("HTTP status differs", (Path(directory) / "index.html").read_text())
            with store.transaction() as db:
                self.assertEqual(
                    sorted(
                        row["available"] for row in db.execute("SELECT available FROM inventory")
                    ),
                    [80, 100],
                )
            self.assertEqual(
                main(
                    [
                        "--suite",
                        "scenarios",
                        "--target",
                        "collateral",
                        "--base-url",
                        environment.base_url,
                        "--report-dir",
                        directory,
                    ]
                ),
                1,
            )

    def test_assertion_failure_retains_path_expected_and_actual(self):
        spec = copy.deepcopy(catalog("collateral")[1])
        spec["steps"][-1]["assert"]["body.available"] = 999
        with collateral() as (_, environment):
            result = run_scenario(spec, environment.base_url)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(
            result["steps"][-1]["failure"],
            dict(kind="assertion", path="body.available", expected=999, actual=90),
        )

    def test_repeated_runs_share_server_without_reusing_data(self):
        with collateral() as (store, environment):
            for _ in range(2):
                self.assertEqual(
                    run_scenario(catalog("collateral")[1], environment.base_url)["status"], "passed"
                )
            with store.transaction() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM inventory").fetchone()[0], 2)

    def test_example_has_no_framework_imports(self):
        import ast

        path = Path(__file__).resolve().parents[2] / "examples/collateral_service/server.py"
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertFalse((node.module or "").startswith("settlementlab"))
            if isinstance(node, ast.Import):
                self.assertFalse(any(item.name.startswith("settlementlab") for item in node.names))
