"""Rubric controls retain real failures; annotation agreement is not model accuracy."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from settlementlab.assurance.evaluation import assess, evaluate, load_corpus, main


class EvaluationControls(unittest.TestCase):
    def test_reviewed_corpus_keeps_recorded_and_synthetic_origins_separate(self):
        corpus = load_corpus()
        report = evaluate(corpus)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["model_calls"], 0)
        self.assertEqual(len(report["cases"]), 9)
        self.assertGreater(report["responses_not_meeting_rubric"], 0)
        self.assertEqual(
            sum(c["source"]["kind"] == "recorded-local-model" for c in report["cases"]), 4
        )
        root = Path(__file__).resolve().parents[2]
        for case in corpus["cases"]:
            if case["source"]["kind"] == "recorded-local-model":
                path = root / case["source"]["path"]
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(), case["source"]["sha256"]
                )
                original = json.loads(path.read_text())
                original = original["analysis"] if "matching" in path.name else original
                self.assertEqual(case["response"], original["analysis"])
        first = next(c for c in report["cases"] if c["id"] == "recorded-matching-first")
        self.assertTrue(first["checks"]["citations"])
        self.assertFalse(first["checks"]["facts"])

    def test_matching_a_known_annotation_does_not_make_bad_response_good(self):
        corpus = load_corpus()
        case = copy.deepcopy(corpus["cases"][4])
        self.assertTrue(all(assess(case).values()))
        case["response"]["summary"] = "Broker quantity 100; allocation total 100."
        self.assertTrue(assess(case)["citations"])
        self.assertFalse(assess(case)["facts"])
        corpus["cases"] = [case]
        self.assertEqual(evaluate(corpus)["status"], "failed")

    def test_negated_automatic_action_is_not_false_positive(self):
        case = copy.deepcopy(load_corpus()["cases"][4])
        for text, expected in [
            ("Never automatically settle the trade.", True),
            ("The trade should not be automatically settled or funded.", True),
            ("Automatically settle the trade.", False),
            ("Never say no; automatically settle the trade.", False),
        ]:
            case["response"]["next_step"] = text
            with self.subTest(text=text):
                self.assertEqual(assess(case)["safe_next_step"], expected)

    def test_cli_reports_and_rejects_bad_annotation_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(main(["--report-dir", str(root / "reports")]), 0)
            self.assertEqual(
                json.loads((root / "reports/evaluation.json").read_text())["model_calls"], 0
            )
            corpus = load_corpus()
            corpus["cases"][0]["expected_checks"] = {}
            path = root / "bad.json"
            path.write_text(json.dumps(corpus))
            self.assertEqual(
                main(["--dataset", str(path), "--report-dir", str(root / "reports")]), 2
            )
            failed = json.loads((root / "reports/evaluation.json").read_text())
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["cases"], [])
            self.assertIn("Configuration error", (root / "reports/index.html").read_text())
