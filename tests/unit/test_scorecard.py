import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.reviewer_ready import capture, reuse, verify, write_report


class ScorecardControls(unittest.TestCase):
    def test_failed_execution_remains_failed_and_writes_escaped_evidence(self):
        original = os.environ.get("PYTHONPATH")
        with tempfile.TemporaryDirectory() as d:
            with patch(
                "scripts.reviewer_ready.command",
                side_effect=RuntimeError("<script>failed</script>"),
            ):
                report = capture(d, trades=8)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(os.environ.get("PYTHONPATH"), original)
            page = Path(d, "index.html").read_text()
            self.assertIn("&lt;script&gt;failed&lt;/script&gt;", page)
            self.assertNotIn("<script>failed", page)
            manifest = json.loads(Path(d, "checksums.json").read_text())
            self.assertIn("scorecard.json", manifest)
            self.assertEqual(verify(d)["status"], "passed")
            Path(d, "scorecard.json").write_text("tampered")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                verify(d)
            write_report(dict(status="passed", note="local only"), Path(d))
            self.assertEqual(json.loads(Path(d, "scorecard.json").read_text())["status"], "passed")

    def test_reuse_identifies_the_independent_services_replay_defect(self):
        with tempfile.TemporaryDirectory() as d:
            result = reuse(Path(d))
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["observed"]["injected-defect"], "failed")
            self.assertEqual(result["core_changes_required"], 0)
