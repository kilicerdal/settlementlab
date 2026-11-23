"""Explicit denominators for bounded structured-observation sampling, not prose accuracy."""

import math
from collections import Counter
from statistics import median


def fraction(numerator, denominator):
    return dict(
        numerator=numerator,
        denominator=denominator,
        rate=numerator / denominator if denominator else None,
    )


def observation_coverage(response, evidence):
    expected = {o["code"]: set(o["evidence_ids"]) for o in evidence["observations"]}
    covered = set()
    if isinstance(response, dict) and isinstance(response.get("claims"), list):
        for claim in response["claims"]:
            if not isinstance(claim, dict):
                continue
            code, ids = claim.get("code"), claim.get("evidence_ids")
            if (
                isinstance(code, str)
                and code in expected
                and isinstance(ids, list)
                and ids
                and all(isinstance(i, str) for i in ids)
                and len(set(ids)) == len(ids)
                and set(ids) <= expected[code]
            ):
                covered.add(code)
    return dict(
        expected_codes=sorted(expected),
        covered_codes=sorted(covered),
        missing_codes=sorted(set(expected) - covered),
        **fraction(len(covered), len(expected)),
    )


def summarize(cases, output, repeats):
    requested = len(cases) * repeats
    recorded = [r for r in output if r["status"] == "recorded"]
    valid = [r for r in recorded if r["checks"]["schema"]]
    nonempty = [r for r in valid if not r["expected_abstention"]]
    empty = [r for r in valid if r["expected_abstention"]]
    success = [
        r
        for r in valid
        if r["accepted"]
        and r["correct_abstention"]
        and (r["expected_abstention"] or r["observation_coverage"]["rate"] == 1)
    ]
    consistency, per_context = [], []
    for case in cases:
        runs = [r for r in output if r["id"] == case["id"]]
        schema_runs = [r for r in runs if r["status"] == "recorded" and r["checks"]["schema"]]
        comparable = repeats >= 2 and len(schema_runs) == repeats
        signatures = {
            (
                r["response"]["abstained"],
                tuple(
                    sorted(
                        (c["code"], tuple(sorted(c["evidence_ids"])))
                        for c in r["response"]["claims"]
                    )
                ),
            )
            for r in schema_runs
        }
        # Missing/invalid repetitions are not evidence of stable behavior.
        consistency.append(
            dict(
                id=case["id"],
                comparable=comparable,
                consistent=len(signatures) == 1 if comparable else None,
            )
        )
        per_context.append(
            dict(
                id=case["id"],
                requested=repeats,
                attempted=len(runs),
                schema_valid=len(schema_runs),
                strict_success=fraction(sum(r in success for r in runs), repeats),
                missing_codes=sorted(
                    {
                        code
                        for r in runs
                        for code in r.get("observation_coverage", {}).get("missing_codes", [])
                    }
                ),
            )
        )
    comparable = [c for c in consistency if c["comparable"]]
    latency = sorted(r["elapsed_seconds"] for r in output)
    metrics = dict(
        recording=fraction(len(recorded), requested),
        schema_valid=fraction(len(valid), requested),
        contract_acceptance=fraction(sum(r["accepted"] for r in recorded), requested),
        strict_success=fraction(len(success), requested),
        unsupported_claims=fraction(
            sum(not r["checks"]["supported_claims"] for r in valid), len(valid)
        ),
        invalid_citations=fraction(sum(not r["checks"]["citations"] for r in valid), len(valid)),
        unnecessary_abstention=fraction(
            sum(r["response"]["abstained"] for r in nonempty), len(nonempty)
        ),
        required_abstention=fraction(sum(r["correct_abstention"] for r in empty), len(empty)),
        observation_coverage=fraction(
            sum(r["observation_coverage"]["numerator"] for r in nonempty),
            sum(r["observation_coverage"]["denominator"] for r in nonempty),
        ),
        repeat_consistency=fraction(sum(c["consistent"] for c in comparable), len(comparable)),
    )
    return dict(
        quality_status="passed"
        if len(success) == requested
        else "failed"
        if len(output) == requested
        else "incomplete",
        requested=requested,
        attempted=len(output),
        not_attempted=requested - len(output),
        recorded=len(recorded),
        contexts=len(cases),
        repeats=repeats,
        schema_valid_outputs=len(valid),
        metrics=metrics,
        per_context=per_context,
        failure_categories=dict(
            Counter(
                r.get("failure_category", "contract-rejected")
                for r in output
                if r["status"] != "recorded" or not r["accepted"]
            )
        ),
        latency_seconds=dict(
            count=len(latency),
            median=median(latency) if latency else None,
            p95_nearest_rank=latency[math.ceil(0.95 * len(latency)) - 1] if latency else None,
            includes="All attempted calls, including failed or interrupted calls; wall-clock transport plus validation",
        ),
        repeat_consistency=consistency,
        consistent_context_rate=metrics["repeat_consistency"]["rate"],
        accepted_rate=metrics["contract_acceptance"]["rate"],
        unsupported_claim_rate=metrics["unsupported_claims"]["rate"],
        invalid_citation_rate=metrics["invalid_citations"]["rate"],
        unnecessary_abstention_rate=metrics["unnecessary_abstention"]["rate"],
        correct_abstention_rate=sum(r["correct_abstention"] for r in valid) / len(valid)
        if valid
        else None,
        conditional_accepted_rate=sum(r["accepted"] for r in recorded) / len(recorded)
        if recorded
        else None,
    )
