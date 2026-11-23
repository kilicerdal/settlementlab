"""Regressions for the retained model prose error and the actual serving boundary."""

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from settlementlab.adapters.investigator import Investigator, assess_response, render_analysis
from settlementlab.assurance.investigator_evaluation import corpus, sample


class InvestigatorPresentationControls(unittest.TestCase):
    def setUp(self):
        self.case = copy.deepcopy(
            next(c for c in corpus()["cases"] if c["id"] == "lagging-position")
        )

    def test_actual_retained_wrong_prose_never_reaches_served_analysis(self):
        path = Path(__file__).resolve().parents[2] / "docs/examples/incident-ai-evaluation-v2.json"
        record = json.loads(path.read_text())
        for name in ("development_run", "final_run"):
            runs = [r for r in record[name]["live"]["cases"] if r["id"] == self.case["id"]]
            self.assertEqual(len(runs), 2)
            for run in runs:
                raw = run["response"]
                self.assertTrue(all(assess_response(raw, self.case["evidence"]).values()))

                def transport(payload):
                    return dict(done=True, message=dict(content=json.dumps(raw)))

                with patch(
                    "settlementlab.adapters.investigator.observations",
                    return_value=self.case["evidence"],
                ):
                    served = Investigator("retained-output-replay", transport).analyze({})
                self.assertNotEqual(served["analysis"]["summary"], raw["summary"])
                self.assertIn("POSITION_LAG [position:event2]:", served["analysis"]["summary"])
                self.assertIn(
                    "COMPENSATION_POSTED [journal:inverse]:", served["analysis"]["summary"]
                )
                self.assertNotIn("respectively", served["analysis"]["summary"])
                self.assertFalse(served["presentation"]["model_prose_displayed"])
                self.assertEqual(served["analysis"]["claims"], raw["claims"])

    def test_reordering_claims_preserves_explicit_per_claim_bindings(self):
        response = self.case["response"]
        response["claims"].reverse()
        response["summary"] = "The network explains the incident."
        response["uncertainty"] = "Underlying cause is not established; model-written extra prose."
        result = render_analysis(response, self.case["evidence"])
        self.assertIn("POSITION_LAG [position:event2]:", result["summary"])
        self.assertIn("COMPENSATION_POSTED [journal:inverse]:", result["summary"])
        self.assertNotIn("network", result["summary"])
        self.assertNotIn("extra prose", result["uncertainty"])
        result["claims"][0]["evidence_ids"].append("unrelated")
        self.assertNotIn("unrelated", response["claims"][0]["evidence_ids"])

    def test_invalid_bindings_and_unknown_canonical_codes_fail_closed(self):
        invalid = copy.deepcopy(self.case["response"])
        invalid["claims"][0]["evidence_ids"] = ["position:event2"]
        with self.assertRaises(ValueError):
            render_analysis(invalid, self.case["evidence"])
        evidence = dict(observations=[dict(code="NEW_CODE", evidence_ids=["event:1"])])
        unknown = dict(
            self.case["response"], claims=[dict(code="NEW_CODE", evidence_ids=["event:1"])]
        )
        with self.assertRaises(ValueError):
            render_analysis(unknown, evidence)

    def test_empty_evidence_and_multi_reference_claims_keep_truthful_scope(self):
        empty = next(c for c in corpus()["cases"] if c["id"] == "correct-abstention")
        result = render_analysis(empty["response"], empty["evidence"])
        self.assertTrue(result["abstained"])
        self.assertEqual(result["claims"], [])
        self.case["evidence"]["observations"][0]["evidence_ids"].append("journal:inverse-2")
        self.case["response"]["claims"][0]["evidence_ids"].append("journal:inverse-2")
        result = render_analysis(self.case["response"], self.case["evidence"])
        self.assertEqual(
            result["claims"][0]["evidence_ids"], ["journal:inverse", "journal:inverse-2"]
        )

    def test_sampler_retains_raw_prose_but_records_the_same_rendered_presentation(self):
        def transport(payload):
            evidence = json.loads(payload["messages"][1]["content"])
            response = dict(
                summary="The network explains the incident.",
                uncertainty="Underlying cause is not established by supplied evidence.",
                abstained=not evidence["observations"],
                claims=[
                    dict(code=o["code"], evidence_ids=o["evidence_ids"])
                    for o in evidence["observations"]
                ],
            )
            return dict(done=True, message=dict(content=json.dumps(response)))

        report = sample("injected", transport, repeats=1)
        self.assertEqual(report["requested"], 6)
        for row in report["cases"]:
            self.assertEqual(row["presentation_status"], "rendered")
            self.assertIn("network", row["response"]["summary"])
            self.assertNotIn("network", row["displayed_analysis"]["summary"])
