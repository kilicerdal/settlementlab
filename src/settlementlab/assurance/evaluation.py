"""Offline, bounded rubric checks over reviewed response fixtures, not model accuracy."""

import argparse
import html
import json
import re
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any, Optional, Union

CHECKS = ("schema", "citations", "facts", "uncertainty", "safe_next_step", "stage_relevance")
TEXT_FIELDS = ("summary", "likely_cause", "next_step", "uncertainty")


def assess(case: dict[str, Any]) -> dict[str, bool]:
    answer = case["response"]
    schema = (
        isinstance(answer, dict)
        and set(answer) == {*TEXT_FIELDS, "evidence_ids"}
        and all(isinstance(answer.get(k), str) and 1 <= len(answer[k]) <= 1200 for k in TEXT_FIELDS)
        and isinstance(answer.get("evidence_ids"), list)
        and 1 <= len(answer["evidence_ids"]) <= 20
    )
    if not schema:
        return dict.fromkeys(CHECKS, False)
    ids = {fact["id"] for fact in case["evidence"]["facts"] + case["evidence"].get("events", [])}
    references = answer["evidence_ids"]
    rubric = case["rubric"]
    text = " ".join(answer[k] for k in TEXT_FIELDS)
    citations = all(isinstance(ref, str) and ref in ids for ref in references)
    citations = citations and set(rubric.get("required_ids", [])).issubset(references)

    def matches(pattern: str, value: str) -> bool:
        return re.search(pattern, value, re.I) is not None

    next_step = answer["next_step"]
    automatic = re.finditer(r"automatically\s+(?:approve|settle|fund)(?:d|ed)?\b", next_step, re.I)
    unsafe_action = any(
        re.search(
            r"(?:\b(?:should|must)\s+not\s+be|\bdo\s+not|\bnever)\s+$",
            next_step[: match.start()],
            re.I,
        )
        is None
        for match in automatic
    )
    return dict(
        schema=True,
        citations=citations,
        facts=all(matches(p, text) for p in rubric["required_patterns"])
        and not any(matches(p, text) for p in rubric["forbidden_patterns"]),
        uncertainty=matches(rubric["uncertainty_pattern"], answer["uncertainty"]),
        safe_next_step=not unsafe_action
        and not matches(r"guarantee.*success", next_step)
        and not any(matches(p, next_step) for p in rubric.get("unsafe_next_step_patterns", [])),
        stage_relevance=not any(matches(p, text) for p in rubric.get("stage_forbidden", [])),
    )


def evaluate(corpus: dict[str, Any]) -> dict[str, Any]:
    if (
        corpus.get("schema_version") != 1
        or not isinstance(corpus.get("cases"), list)
        or not 1 <= len(corpus["cases"]) <= 100
    ):
        raise ValueError("Evaluation requires schema version 1 and 1–100 cases")
    seen: set[str] = set()
    results = []
    for case in corpus["cases"]:
        if case["id"] in seen:
            raise ValueError("Duplicate evaluation case ID")
        seen.add(case["id"])
        if set(case["expected_checks"]) != set(CHECKS) or any(
            type(v) is not bool for v in case["expected_checks"].values()
        ):
            raise ValueError("Each response needs explicit reviewed labels for every criterion")
        rubric = case["rubric"]
        patterns = [
            *rubric["required_patterns"],
            *rubric["forbidden_patterns"],
            *rubric.get("stage_forbidden", []),
            *rubric.get("unsafe_next_step_patterns", []),
            rubric["uncertainty_pattern"],
        ]
        if any(not isinstance(p, str) or len(p) > 200 for p in patterns):
            raise ValueError("Rubric patterns must be strings of at most 200 characters")
        checks = assess(case)
        results.append(
            dict(
                id=case["id"],
                source=case["source"],
                review=case["review"],
                checks=checks,
                meets_rubric=all(checks.values()),
                expected_checks=case["expected_checks"],
                annotation_matches=checks == case["expected_checks"],
                response=case["response"],
            )
        )
    return dict(
        schema_version=1,
        generated_at=datetime.now(timezone.utc).isoformat(),
        mode="offline-reviewed-corpus",
        model_calls=0,
        scope="Curated recorded and synthetic responses; deterministic rubric conformance, not model accuracy",
        review_method=corpus["review_method"],
        status="passed" if all(row["annotation_matches"] for row in results) else "failed",
        responses_meeting_rubric=sum(row["meets_rubric"] for row in results),
        responses_not_meeting_rubric=sum(not row["meets_rubric"] for row in results),
        criteria={
            check: dict(passed=sum(row["checks"][check] for row in results), total=len(results))
            for check in CHECKS
        },
        cases=results,
    )


def load_corpus(path: Optional[Union[str, Path]] = None) -> dict[str, Any]:
    resource = (
        Path(path)
        if path
        else files("settlementlab.assurance").joinpath("datasets/triage-reviewed-v1.json")
    )
    with resource.open("rb") as stream:
        raw = stream.read(524289)
    if len(raw) > 524288:
        raise ValueError("Evaluation corpus exceeds 512 KiB")
    result: dict[str, Any] = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("Evaluation corpus must be a JSON object")
    return result


def write_evaluation(report: dict[str, Any], directory: Union[str, Path]) -> None:
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    (output / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    rows = "".join(
        "<tr><td>"
        + html.escape(case["id"])
        + "</td><td>"
        + html.escape(case["source"]["kind"])
        + "</td><td>"
        + html.escape(
            ", ".join(k for k, v in case["checks"].items() if not v) or "Meets bounded rubric"
        )
        + "</td><td>"
        + html.escape(case["review"])
        + "</td></tr>"
        for case in report["cases"]
    )
    page = (
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SettlementLab AI rubric review</title><style>body{font:16px/1.6 system-ui;background:#0a111c;color:#dbe6ef;max-width:1100px;margin:40px auto;padding:0 20px}a{color:#a3dfca}td,th{padding:14px;border-bottom:1px solid #456;text-align:left}table{width:100%;border-collapse:collapse}.scroll{overflow:auto}</style><h1>AI response review / offline corpus</h1><p>No model calls. Recorded historical failures remain visible alongside synthetic controls. This is not an accuracy benchmark or independent human audit.</p><p>'
        + str(report["responses_meeting_rubric"])
        + " responses meet the bounded rubric; "
        + str(report["responses_not_meeting_rubric"])
        + " do not. Harness annotation agreement: "
        + html.escape(report["status"])
        + '.</p><p><a href="evaluation.json">Full responses, labels and criteria</a></p><div class="scroll"><table><tr><th>Case</th><th>Origin</th><th>Unmet criteria</th><th>Review</th></tr>'
        + rows
        + "</table></div></html>"
    )
    if "error" in report:
        page = page.replace(
            "<h1>", "<p>Configuration error: " + html.escape(report["error"]) + "</p><h1>", 1
        )
    (output / "index.html").write_text(page, encoding="utf-8")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset")
    parser.add_argument("--report-dir", default="artifacts/ai-evaluation")
    args = parser.parse_args(argv)
    try:
        report = evaluate(load_corpus(args.dataset))
        write_evaluation(report, args.report_dir)
    except (ValueError, OSError, KeyError, TypeError, re.error) as error:
        failure = dict(
            schema_version=1,
            mode="offline-reviewed-corpus",
            model_calls=0,
            status="failed",
            error=str(error),
            cases=[],
            responses_meeting_rubric=0,
            responses_not_meeting_rubric=0,
        )
        try:
            write_evaluation(failure, args.report_dir)
        except OSError:
            pass  # The nonzero exit remains authoritative when the output path is unwritable.
        print("EVALUATION FAILED: " + str(error))
        return 2
    print(report["status"].upper() + ": offline rubric review; zero model calls")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
