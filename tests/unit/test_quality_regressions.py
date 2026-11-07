import io
import unittest

from settlementlab.assurance.runner import EvidenceResult
from settlementlab.core.calendar import BusinessCalendar
from settlementlab.core.validation import DomainError


class ReportingRegressions(unittest.TestCase):
    def test_skipped_subtest_cannot_hide_previous_failure(self):
        class Example(unittest.TestCase):
            def runTest(self):
                with self.subTest("failure"):
                    self.fail("must remain failed")
                with self.subTest("skip"):
                    self.skipTest("later skip")

        result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=EvidenceResult).run(
            unittest.TestSuite([Example()])
        )
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(result.cases[0]["status"], "failed")
        self.assertEqual(result.cases[0]["skipped_subtests"], 1)

    def test_invalid_pinned_policy_is_rejected(self):
        for policy in [
            [],
            {},
            dict(id="weekday-v1", weekend=[0]),
            dict(id="weekday-v1", fingerprint=""),
            dict(id="weekday-v1", closed_dates="2026-11-09"),
            dict(id="weekday-v1", unexpected=True),
        ]:
            with self.subTest(policy=policy):
                with self.assertRaises(DomainError) as error:
                    BusinessCalendar.from_dict(policy)
                self.assertEqual(error.exception.status, 409)
