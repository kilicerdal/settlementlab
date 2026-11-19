"""Reproducible incident-AI rubric checks and optional bounded local-model sampling."""

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ..adapters.ai import send_request
from ..adapters.investigator import assess_response
from ..core.validation import DomainError


def corpus():
    path = Path(__file__).with_name("datasets") / "incident_investigator.json"
    return json.loads(path.read_text())


def evaluate_case(case, response):
    checks = assess_response(response, case["evidence"])
    return dict(
        id=case["id"],
        checks=checks,
        accepted=all(checks.values()),
        expected_accepted=case["expected_accepted"],
        correct=all(checks.values()) == case["expected_accepted"],
    )


def evaluate(cases):
    results = [evaluate_case(case, case["response"]) for case in cases]
    unsupported = [(c, r) for c, r in zip(cases, results) if not c["expected_accepted"]]
    insufficient = [
        (c, r) for c, r in zip(cases, results) if c["category"] == "insufficient-evidence"
    ]
    unsupported_claims = [
        r for r in results if r["checks"]["schema"] and not r["checks"]["supported_claims"]
    ]
    bad_citations = [r for r in results if r["checks"]["schema"] and not r["checks"]["citations"]]
    return dict(
        status="passed" if results and all(r["correct"] for r in results) else "failed",
        cases=results,
        metrics=dict(
            cases=len(results),
            unsupported_claim_cases=len(unsupported_claims),
            unsupported_claim_acceptance_rate=sum(r["accepted"] for r in unsupported_claims)
            / len(unsupported_claims)
            if unsupported_claims
            else None,
            invalid_citation_cases=len(bad_citations),
            invalid_citation_acceptance_rate=sum(r["accepted"] for r in bad_citations)
            / len(bad_citations)
            if bad_citations
            else None,
            negative_cases=len(unsupported),
            false_acceptance_rate=sum(r["accepted"] for _, r in unsupported) / len(unsupported)
            if unsupported
            else None,
            insufficient_evidence_accuracy=sum(r["correct"] for _, r in insufficient)
            / len(insufficient)
            if insufficient
            else None,
        ),
        scope="Declared fixture responses and deliberately adversarial mutations; contract/rubric detection, not measured model quality or independent human review",
    )


def sample(model, transport=send_request):
    cases = [c for c in corpus()["cases"] if c.get("sample")]
    output = []
    for case in cases:
        started = time.perf_counter()
        evidence = case["evidence"]
        # Use the same production validator and transport. Fixture evidence is already minimized.
        from ..adapters.investigator import INSTRUCTIONS, SCHEMA

        try:
            response = transport(
                dict(
                    model=model,
                    stream=False,
                    format=SCHEMA,
                    options=dict(temperature=0, num_predict=1000, num_ctx=4096),
                    messages=[
                        dict(role="system", content=INSTRUCTIONS),
                        dict(role="user", content=json.dumps(evidence)),
                    ],
                )
            )
            raw = response["message"]["content"]
            if (
                response.get("done") is not True
                or response.get("done_reason") not in ("stop", None)
                or not isinstance(raw, str)
                or len(raw) > 16384
            ):
                raise ValueError("Incomplete or oversized sample")

            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("Duplicate output field")
                    result[key] = value
                return result

            parsed = json.loads(raw, object_pairs_hook=unique)
            checks = assess_response(parsed, evidence)
            expected_abstention = not evidence["observations"]
            output.append(
                dict(
                    id=case["id"],
                    elapsed_seconds=time.perf_counter() - started,
                    status="recorded",
                    response=parsed,
                    checks=checks,
                    accepted=all(checks.values()),
                    expected_abstention=expected_abstention,
                    correct_abstention=parsed.get("abstained") == expected_abstention,
                )
            )
        except (DomainError, ValueError, TypeError, KeyError, AttributeError) as error:
            output.append(dict(id=case["id"], status="unavailable-or-invalid", detail=str(error)))
    recorded = [r for r in output if r["status"] == "recorded"]
    return dict(
        mode="live-local-model",
        generated_at=datetime.now(timezone.utc).isoformat(),
        prompt_version="incident-v43.1",
        corpus_sha256=hashlib.sha256(json.dumps(corpus(), sort_keys=True).encode()).hexdigest(),
        model=model,
        cases=output,
        recorded=len(recorded),
        requested=len(cases),
        accepted_rate=sum(r["accepted"] for r in recorded) / len(recorded) if recorded else None,
        correct_abstention_rate=sum(r["correct_abstention"] for r in recorded) / len(recorded)
        if recorded
        else None,
        scope="Small synthetic sample; validator/rubric measurements do not establish open-ended factual accuracy",
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/v43-ai")
    parser.add_argument(
        "--live-model",
        help="Optional already installed local Ollama model; no downloads or paid calls",
    )
    args = parser.parse_args(argv)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    report = evaluate(corpus()["cases"])
    report["live"] = (
        sample(args.live_model)
        if args.live_model
        else dict(
            mode="not-run",
            reason="No local model sampling requested; offline fixtures are not model outputs",
        )
    )
    (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return int(
        report["status"] != "passed"
        or bool(args.live_model and report["live"]["recorded"] != report["live"]["requested"])
    )


if __name__ == "__main__":
    raise SystemExit(main())
