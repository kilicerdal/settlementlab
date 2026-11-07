"""Record actual local browser actions with captions; optional Playwright only."""

import argparse
import json
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from settlementlab import __version__
from settlementlab.assurance.fixtures import LocalEnvironment

from .showcase import build


def record(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "walkthrough.webm").exists():
        raise ValueError("Recording already exists; choose a new --output directory")
    evidence = build(output / "evidence")
    frames = []
    started = datetime.now(timezone.utc).isoformat()
    with LocalEnvironment() as environment, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            record_video_dir=str(output / "raw"),
            record_video_size={"width": 1440, "height": 1000},
        )
        page = context.new_page()
        video = page.video
        clock = time.monotonic()

        def scene(title, detail, seconds):
            page.evaluate(
                """({title, detail}) => {
                let caption = document.getElementById('recording-caption');
                if (!caption) { caption = document.createElement('div');
                  caption.id = 'recording-caption'; document.body.append(caption); }
                caption.style.cssText = 'position:fixed;bottom:0;left:0;right:0;z-index:2147483647;background:#06131ff5;color:#e8f3ef;padding:18px 32px;border-top:2px solid #a3dfca;font:16px/1.5 system-ui;pointer-events:none';
                caption.replaceChildren();
                const strong = document.createElement('strong'); strong.textContent = title;
                strong.style.cssText='display:block;color:#a3dfca;font-size:21px';
                const text = document.createElement('span'); text.textContent = detail;
                caption.append(strong, text);
                }""",
                dict(title=title, detail=detail),
            )
            frames.append(dict(at_seconds=round(time.monotonic() - clock, 2), title=title))
            page.screenshot(path=str(output / "poster.png")) if len(frames) == 2 else None
            print(title, flush=True)
            page.wait_for_timeout(seconds * 1000)

        try:
            page.goto(environment.base_url)
            expect(page.locator("#business-clock")).to_contain_text("2026-11-09")
            scene(
                "SettlementLab / financial assurance",
                "Actual local execution • synthetic trades • simulated business date • no live AI call",
                5,
            )
            page.get_by_role("button", name="Run showcase scenario").click()
            expect(page.locator("#detail .badge")).to_have_text("EXCEPTION")
            expect(page.locator(".finding")).to_have_count(2)
            page.locator("#detail").scroll_into_view_if_needed()
            scene(
                "01 / Find two independent breaks",
                "Broker price 42.75 vs manager 42.80; allocations total 9,900 against quantity 10,000.",
                8,
            )
            page.get_by_role("button", name="Revise manager submission").click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_label("Price per share").fill("42.75")
            dialog.get_by_label("Fund allocations").fill("SYN-FUND-ALPHA,6000\nSYN-FUND-BETA,4000")
            scene(
                "02 / Correct the manager submission",
                "A new revision preserves the earlier submission and leaves broker economics unchanged.",
                6,
            )
            dialog.get_by_role("button", name="Submit independent terms").click()
            expect(page.locator("#detail .badge")).to_have_text("MATCHED")
            page.get_by_role("button", name="Request instruction approval").click()
            expect(
                page.get_by_role("button", name="Approve instructions", exact=True)
            ).to_be_disabled()
            scene(
                "03 / Separate request from approval",
                "Alex requests review; the maker cannot approve their own instructions. Personas are demo identities.",
                7,
            )
            page.get_by_label("Demo identity", exact=True).select_option("checker-sam")
            page.get_by_role("button", name="Approve instructions", exact=True).click()
            expect(page.locator("#detail .badge")).to_have_text("AFFIRMED")
            scene(
                "04 / Approve the matched terms",
                "Sam is a separate checker identity. Approval and the AFFIRMED transition commit together.",
                5,
            )
            page.get_by_role("button", name="Attempt settlement").click()
            expect(page.locator("#detail .badge")).to_have_text("FAILED")
            scene(
                "05 / Reject insufficient capacity",
                "Approval does not create cash or securities. Failure remains inspectable and recoverable.",
                7,
            )
            page.get_by_role("button", name="Fund shared shortfalls").click()
            page.get_by_role("button", name="Attempt settlement").click()
            expect(page.locator("#detail .badge")).to_have_text("SETTLED")
            expect(page.locator("#journal-entries")).to_contain_text("DVP SETTLEMENT")
            page.locator("#journal-entries").scroll_into_view_if_needed()
            scene(
                "06 / Recover with atomic posting",
                "Synthetic funding enables delivery versus payment: four journal lines balance cash and security separately.",
                8,
            )
            page.get_by_role("button", name="Reconcile statement").click()
            expect(page.get_by_role("status")).to_contain_text("BALANCED")
            expect(page.locator("#ledger-status")).to_have_text("BALANCED")
            page.locator("#detail").scroll_into_view_if_needed()
            scene(
                "07 / Reconcile the settled trade",
                "The statement agrees with the recorded settlement. Rollback and competing-spend checks live in the test suite.",
                6,
            )
            page.goto((output / "evidence/index.html").as_uri())
            scene(
                "08 / Reuse one assurance engine",
                "Freshly executed reports cover settlement and an independent collateral API with its own SQLite store.",
                7,
            )
            page.get_by_role("link", name="Inspect the healthy control").click()
            expect(page.locator("body")).to_contain_text("PASSED · 2 cases · 0 failed")
            scene(
                "09 / Establish the healthy control",
                "Both collateral scenarios pass before demonstrating the deliberately broken variant.",
                6,
            )
            page.goto((output / "evidence/collateral-fault/index.html").as_uri())
            expect(page.locator("body")).to_contain_text("FAILED · 2 cases · 1 failed")
            page.locator("tr").filter(has=page.locator("td", has_text="C02")).locator(
                "summary"
            ).click()
            expect(page.locator("body")).to_contain_text('"actual": 201')
            scene(
                "10 / Detect the exact injected defect",
                "Replay should return 200; the faulty variant returns 201. This expected negative report is proof of detection.",
                9,
            )
            duration = round(time.monotonic() - clock, 2)
        finally:
            context.close()
            try:
                video.save_as(str(output / "walkthrough.webm"))
            finally:
                browser.close()
    metadata = dict(
        framework_version=__version__,
        source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        started_at=started,
        python=platform.python_version(),
        duration_seconds=duration,
        audio="none; captioned recording with a separate narration script",
        scope="Actual local browser commands plus freshly executed reports; no live-model call",
        evidence_manifest=evidence,
        scenes=frames,
    )
    (output / "walkthrough.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print("Recorded " + str(output / "walkthrough.webm"), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/walkthrough")
    args = parser.parse_args()
    record(args.output)


if __name__ == "__main__":
    main()
