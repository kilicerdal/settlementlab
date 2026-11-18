import tempfile
import unittest
from pathlib import Path

from settlementlab.assurance.reporting import write_reports


class ReportNavigation(unittest.TestCase):
    def test_failed_steps_link_to_request_control_and_comparison(self):
        report = dict(
            status="failed",
            duration=0.1,
            generated_at="recorded",
            python="3.13",
            cases=[
                dict(id="PASS", suite="scenarios", status="passed", duration=0),
                dict(
                    id="BROKEN<script>",
                    suite="scenarios",
                    status="failed",
                    duration=0.1,
                    control="reserve-once",
                    detail="Unexpected status",
                    steps=[
                        dict(
                            index=1,
                            action="http",
                            status="failed",
                            control="replay-identity",
                            request=dict(
                                method="POST",
                                path="/reservations",
                                status=201,
                                headers={"Authorization": "DO_NOT_RENDER"},
                                body="DO_NOT_RENDER",
                            ),
                            failure=dict(kind="http_status", expected=200, actual=201),
                        )
                    ],
                ),
            ],
        )
        with tempfile.TemporaryDirectory() as temp:
            write_reports(report, temp)
            page = (Path(temp) / "index.html").read_text()
        self.assertIn('href="#case-2-step-1"', page)
        self.assertIn('id="case-2-step-1"', page)
        self.assertIn("<details open>", page)
        self.assertIn("replay-identity", page)
        self.assertIn("expected", page)
        self.assertIn("actual", page)
        self.assertIn("/reservations", page)
        self.assertNotIn("DO_NOT_RENDER", page)
        self.assertNotIn("<script>", page)
        self.assertLess(page.index('<tr id="case-2"'), page.index('<tr id="case-1"'))
