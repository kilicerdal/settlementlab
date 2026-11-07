import ast
import json
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree

from settlementlab.assurance.reporting import write_reports
from settlementlab.configuration import Settings
from settlementlab.core.postings import balanced_changes
from settlementlab.core.validation import DomainError


class FrameworkControls(unittest.TestCase):
    def test_configuration_precedence_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(dict(port=8000, model="")))
            settings = Settings.load(path, {"SETTLEMENTLAB_PORT": "8001"}, port=8002)
            self.assertEqual((settings.port, settings.model), (8002, ""))
            path.write_text('{"unexpected":true}')
            with self.assertRaises(DomainError):
                Settings.load(path, {})
        for value in [True, -1, 65536, "8080"]:
            with self.assertRaises(DomainError):
                Settings(port=value)
        with self.assertRaises(DomainError):
            Settings(database=":memory:")
        with self.assertRaises(DomainError):
            Settings.load(environ={"SETTLEMENTLAB_PORT": "invalid"})

    def test_assets_must_balance_independently(self):
        with self.assertRaises(DomainError):
            balanced_changes([("A", "CASH:USD", 100), ("B", "SEC:NOVA", -100)])
        changes = balanced_changes(
            [
                ("A", "CASH:USD", -100),
                ("B", "CASH:USD", 100),
                ("B", "SEC:NOVA", -2),
                ("A", "SEC:NOVA", 2),
            ]
        )
        self.assertEqual(changes[("A", "SEC:NOVA")], 2)
        self.assertEqual(changes[("A", "CASH:USD")], -100)

    def test_reports_preserve_failure_and_escape_html(self):
        report = dict(
            status="failed",
            duration=0.2,
            generated_at="2026-11-07T00:00:00Z",
            python="3.9",
            cases=[
                dict(
                    id="case.<script>",
                    suite="test",
                    status="failed",
                    duration=0.2,
                    detail="<script>example</script>",
                )
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            write_reports(report, directory)
            output = Path(directory)
            self.assertEqual(json.loads((output / "results.json").read_text())["status"], "failed")
            xml = ElementTree.parse(output / "junit.xml").getroot()
            self.assertEqual(xml.attrib["failures"], "1")
            self.assertEqual(len(xml.findall("testcase/failure")), 1)
            page = (output / "index.html").read_text()
            self.assertNotIn("<script>", page)
            self.assertIn("&lt;script&gt;", page)

    def test_layer_dependencies_and_sql_stay_in_adapters(self):
        root = Path(__file__).resolve().parents[2] / "src/settlementlab"
        for layer in ["core", "application"]:
            for path in (root / layer).glob("*.py"):
                tree = ast.parse(path.read_text())
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        module = node.module or ""
                        self.assertFalse(
                            any(
                                part in module.split(".") for part in ["infrastructure", "adapters"]
                            ),
                            str(path),
                        )
                    if isinstance(node, ast.Import):
                        self.assertFalse(
                            any(
                                item.name in ["sqlite3", "http.server", "urllib.request"]
                                for item in node.names
                            ),
                            str(path),
                        )
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                        self.assertNotIn(
                            node.func.attr,
                            ["execute", "executescript", "fetchone", "fetchall"],
                            str(path),
                        )
