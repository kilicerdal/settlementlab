import copy
import json
import tempfile
import unittest

from settlementlab.assurance.ai_review import main, review_cases, run
from settlementlab.assurance.evaluation import evaluate


class AdversarialAI(unittest.TestCase):
    def test_bad_answers_are_detected_without_becoming_model_accuracy_claim(self):
        corpus = review_cases()
        result = evaluate(corpus)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["responses_meeting_rubric"], 1)
        self.assertEqual(result["responses_not_meeting_rubric"], 6)
        with tempfile.TemporaryDirectory() as d:
            report = run(d)
            self.assertEqual(report["live_local"]["status"], "not-run")
            self.assertEqual(report["historical_corpus"]["model_calls"], 0)
            self.assertEqual(main(["--report-dir", d]), 0)

    def test_loopback_sampler_reports_actual_results_and_provider_failure(self):
        answer = copy.deepcopy(review_cases()["cases"][0]["response"])

        def transport(payload):
            self.assertEqual(payload["model"], "test-local")
            return {"done": True, "message": {"content": json.dumps(answer)}}

        with tempfile.TemporaryDirectory() as d:
            report = run(d, "test-local", transport)
            self.assertEqual(report["live_local"]["model_calls"], 2)
            self.assertTrue(all(report["live_local"]["cases"][0]["checks"].values()))

            def fail(payload):
                raise RuntimeError("unavailable")

            report = run(d, "test-local", fail)
            self.assertEqual(report["live_local"]["cases"][0]["error"], "unavailable")
