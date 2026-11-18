"""Portable JSON/JUnit and navigable, escaped, offline HTML evidence."""

import html
import json
from pathlib import Path
from typing import Any, Union
from xml.etree.ElementTree import Element, ElementTree, SubElement


def escaped(value: Any) -> str:
    return html.escape(str(value), quote=True)


def evidence_table(values: dict[str, Any]) -> str:
    return (
        '<dl class="facts">'
        + "".join(
            "<dt>"
            + escaped(key)
            + "</dt><dd><pre>"
            + escaped(json.dumps(value, ensure_ascii=True, indent=2))
            + "</pre></dd>"
            for key, value in values.items()
        )
        + "</dl>"
    )


def write_reports(report: dict[str, Any], directory: Union[str, Path]) -> Path:
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    cases = report["cases"]
    failures = sum(c["status"] == "failed" for c in cases)
    suite = Element(
        "testsuite",
        name="SettlementLab assurance",
        tests=str(len(cases)),
        failures=str(failures),
        time=str(report["duration"]),
    )
    for case in cases:
        entry = SubElement(
            suite, "testcase", classname=case["suite"], name=case["id"], time=str(case["duration"])
        )
        if case["status"] == "failed":
            SubElement(entry, "failure", message=case.get("detail", "Failed")).text = case.get(
                "detail", "Failed"
            )
        if case["status"] == "skipped":
            SubElement(entry, "skipped")
    ElementTree(suite).write(output / "junit.xml", encoding="utf-8", xml_declaration=True)
    rows = []
    navigation = []
    # Numeric anchors stay valid even when user-supplied IDs contain markup or duplicates.
    for ordinal, case in sorted(
        enumerate(cases, 1), key=lambda pair: pair[1]["status"] != "failed"
    ):
        anchor = "case-" + str(ordinal)
        if case["status"] == "failed":
            failed_step = next((s for s in case.get("steps", []) if s["status"] == "failed"), None)
            destination = anchor + ("-step-" + str(failed_step["index"]) if failed_step else "")
            navigation.append(
                '<li><a href="#'
                + destination
                + '">'
                + escaped(case["id"])
                + "</a> — "
                + escaped(case.get("detail", "Failed"))
                + "</li>"
            )
        steps = []
        for step in case.get("steps", []):
            request = {
                key: step["request"][key]
                for key in ("method", "path", "status", "duration")
                if key in step.get("request", {})
            }
            values = dict(control=step.get("control", case.get("control", "Not supplied")))
            if request:
                values["request"] = request
            if "failure" in step:
                values.update(step["failure"])
            if "expected_http_status" in step:
                values["expected_http_status"] = step["expected_http_status"]
            steps.append(
                '<li id="'
                + anchor
                + "-step-"
                + str(step["index"])
                + '"><strong>Step '
                + escaped(step["index"])
                + " / "
                + escaped(step["action"])
                + " / "
                + escaped(step["status"])
                + "</strong>"
                + evidence_table(values)
                + "</li>"
            )
        metadata = {
            key: case[key] for key in ("target", "source", "control", "environment") if key in case
        }
        status = case["status"]
        status_class = status if status in ("passed", "failed", "skipped") else "unknown"
        rows.append(
            '<tr id="'
            + anchor
            + '"><td>'
            + escaped(case["suite"])
            + "</td><td>"
            + escaped(case["id"])
            + '</td><td class="'
            + status_class
            + '">'
            + escaped(status)
            + "</td><td>"
            + format(case["duration"], ".3f")
            + "s</td><td><details"
            + (" open" if status == "failed" else "")
            + "><summary>Evidence</summary><pre>"
            + escaped(case.get("detail", ""))
            + "</pre>"
            + evidence_table(metadata)
            + "<ol>"
            + "".join(steps)
            + '</ol><a href="#report-top">Back to summary</a></details></td></tr>'
        )
    page = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SettlementLab assurance report</title><style>body{background:#0a111c;color:#dbe6ef;font:14px/1.6 system-ui;margin:40px auto;padding:0 24px;max-width:1250px}h1{font-size:36px;color:#a3dfca}a,.passed{color:#a3dfca}.failed{color:#f0ad91}.skipped{color:#d9c788}table{border-collapse:collapse;width:100%}td,th{padding:12px;text-align:left;vertical-align:top;border-bottom:1px solid #304050}pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:0}summary{cursor:pointer}.scroll{overflow:auto}small{color:#9baebe}.facts{display:grid;grid-template-columns:minmax(90px,1fr) minmax(0,3fr);gap:8px}.facts dd{margin:0}.facts dt{color:#9baebe}li{scroll-margin-top:20px;margin-bottom:24px}nav{padding:20px;border:1px solid #304050}td:nth-child(2){overflow-wrap:anywhere} @media(max-width:600px){body{padding:0 12px}h1{font-size:28px}.facts{display:block}.facts dt{margin-top:12px}}</style><main id="report-top"><h1>SettlementLab / Assurance evidence</h1>"""
    page += (
        "<p>"
        + escaped(report["status"].upper())
        + " · "
        + str(len(cases))
        + " cases · "
        + str(failures)
        + " failed · Target: "
        + escaped(report.get("target", "settlement"))
        + "</p><small>"
        + escaped(report["generated_at"])
        + " · Python "
        + escaped(report["python"])
        + '</small><p><a href="results.json">JSON evidence</a> · <a href="junit.xml">JUnit evidence</a></p>'
    )
    page += (
        '<p>Executed synthetic controls; not a model-accuracy or production-readiness claim. Expected rejection is distinct from an unexpected failure.</p><nav aria-label="Failure navigation"><h2>Failures first</h2>'
        + (
            "<ul>" + "".join(navigation) + "</ul>"
            if navigation
            else "<p>No unexpected failures recorded.</p>"
        )
        + "</nav>"
    )
    page += (
        '<div class="scroll"><table><thead><tr><th>Suite</th><th>Case</th><th>Status</th><th>Duration</th><th>Details</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></div></main></html>"
    )
    (output / "index.html").write_text(page, encoding="utf-8")
    return output / "index.html"
