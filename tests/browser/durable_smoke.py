"""Actual local operations UI with real child-worker crashes; no live AI calls."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from settlementlab.assurance.durable_data import approved_trade, fund_trade
from settlementlab.assurance.fixtures import LocalEnvironment

root = Path(__file__).resolve().parents[2]
output = root / "artifacts/durable-browser"
output.mkdir(parents=True, exist_ok=True)
stages = []
with LocalEnvironment() as environment, sync_playwright() as playwright:
    app = environment.app
    trades = [approved_trade(app.service, "ui-trade-" + str(i)) for i in range(3)]
    browser = playwright.chromium.launch()
    context = browser.new_context(
        viewport={"width": 1440, "height": 1000},
        record_video_dir=str(output / "raw"),
        record_video_size={"width": 1440, "height": 1000},
    )
    page = context.new_page()
    video = page.video

    def run_worker(mode="both", fault=None, lease=30):
        command = [
            sys.executable,
            "-m",
            "settlementlab.worker",
            "--db",
            app.settings.database,
            "--business-date",
            "2026-11-09",
            "--once",
            "--mode",
            mode,
            "--lease",
            str(lease),
        ]
        if fault:
            command.extend(["--fault", fault])
        result = subprocess.run(
            command,
            cwd=root,
            env=dict(os.environ, PYTHONPATH=str(root / "src")),
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == (73 if fault else 0), result.stdout + result.stderr
        return result

    def wait_lease(until):
        deadline = time.monotonic() + 5
        while time.time() <= until:
            assert time.monotonic() < deadline, "Owned lease did not expire"
            time.sleep(0.02)

    def refresh():
        page.get_by_role("button", name="Refresh evidence").click()

    def capture(name):
        stages.append(dict(name=name, at=time.time(), snapshot=app.operations.snapshot()))
        page.screenshot(path=str(output / (name + ".png")), full_page=True)
        page.wait_for_timeout(1500)  # Presentation pacing only; assertions establish outcomes.

    try:
        page.goto(environment.base_url + "/operations")
        expect(page.get_by_role("heading", name="Accepted work. Accounted for.")).to_be_visible()
        expect(page.locator("#clock")).to_contain_text("SIMULATED BUSINESS DATE: 2026-11-09")
        expect(page.get_by_role("button", name="Queue selected trades")).to_be_disabled()
        page.get_by_label("Demo identity", exact=True).select_option("checker-sam")
        expect(page.get_by_role("checkbox").first).to_be_enabled()
        for box in page.get_by_role("checkbox").all():
            box.check()
        page.get_by_role("button", name="Queue selected trades").click()
        expect(page.locator("#pending")).to_have_text("3")
        capture("01-accepted-batch")
        financial = app.service.snapshot()
        run_worker("process", "before-commit", 1)
        assert app.service.snapshot() == financial
        leased = next(
            job for job in app.operations.snapshot()["jobs"] if job["status"] == "RUNNING"
        )
        refresh()
        expect(page.locator("#running")).to_have_text("1")
        capture("02-worker-crashed-before-commit")
        wait_lease(leased["lease_until"])
        for _ in range(3):
            run_worker("process")
        refresh()
        expect(page.locator("#succeeded")).to_have_text("3")
        capture("03-recovered-settlements")
        financial = app.service.snapshot()
        run_worker("deliver", "after-consume", 1)
        event = next(e for e in app.operations.snapshot()["outbox"] if e["status"] == "LEASED")
        refresh()
        expect(page.locator("#inbox")).to_have_text("1")
        capture("04-observer-committed-before-ack")
        wait_lease(event["lease_until"])
        first = run_worker("deliver")
        assert json.loads(first.stdout)["delivered"]["applied"] is False
        for _ in range(2):
            run_worker("deliver")
        refresh()
        expect(page.locator("#inbox")).to_have_text("3")
        page.get_by_role("button", name="Redeliver (dedupe check)").first.click()
        expect(page.get_by_role("status")).to_contain_text("Duplicate event ignored")
        assert app.service.snapshot() == financial
        page.get_by_label("Operation timeline", exact=True).select_option(leased["id"])
        expect(page.locator("#history")).to_contain_text("LEASE_EXPIRED")
        capture("05-duplicate-delivery-ignored")
        # Capacity exception requires a separately approved trade, explicit funding and review.
        fourth = approved_trade(app.service, "ui-review", False)
        refresh()
        expect(page.get_by_role("checkbox")).to_have_count(1)
        page.get_by_role("checkbox").check()
        page.get_by_role("button", name="Queue selected trades").click()
        expect(page.locator("#pending")).to_have_text("1")
        run_worker("process")
        refresh()
        expect(page.locator("#dead")).to_have_text("1")
        capture("06-needs-operator-review")
        current = next(t for t in app.service.snapshot()["trades"] if t["id"] == fourth["id"])
        fund_trade(app.service, current, "ui-review-funding")
        page.get_by_label("Demo identity", exact=True).select_option("auditor-casey")
        expect(page.get_by_role("button", name="Review and requeue")).to_be_disabled()
        page.get_by_label("Demo identity", exact=True).select_option("checker-sam")
        expect(page.get_by_role("button", name="Review and requeue")).to_be_enabled()
        page.get_by_role("button", name="Review and requeue").click()
        expect(page.get_by_role("dialog")).to_be_visible()
        page.get_by_label("Reason", exact=True).fill("Reviewed after synthetic funding")
        page.get_by_role("button", name="Confirm reviewed retry").click()
        expect(page.get_by_role("dialog")).not_to_be_visible()
        run_worker("process")
        for _ in range(2):
            run_worker("deliver")
        refresh()
        expect(page.locator("#succeeded")).to_have_text("4")
        expect(page.locator("#inbox")).to_have_text("5")
        final = app.operations.snapshot()
        reviewed = next(j for j in final["jobs"] if j["trade_id"] == fourth["id"])
        assert reviewed["generation"] == 2 and final["receipts"] == 5
        page.get_by_label("Operation timeline", exact=True).select_option(reviewed["id"])
        expect(page.locator("#history")).to_contain_text("REQUEUE_REQUESTED")
        capture("07-reviewed-recovery")
        page.set_viewport_size({"width": 390, "height": 844})
        page.evaluate("window.scrollTo(0,0)")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(output / "mobile.png"), full_page=True)
        page.get_by_label("Queue status filter", exact=True).select_option("DEAD_LETTER")
        expect(page.locator("#jobs")).to_contain_text("No work in this view")
        assert app.service.snapshot()["treasury"]["controls"]["status"] == "BALANCED"
    finally:
        context.close()
        try:
            video.save_as(str(output / "durable-recovery.webm"))
        finally:
            browser.close()
(output / "journey.json").write_text(
    json.dumps(
        dict(scope="Actual local browser and child-worker execution; no model call", stages=stages),
        indent=2,
    )
    + "\n"
)
print(
    "Durable operations desktop/mobile journey passed: crash → restart → lost ack → deduplication → reviewed recovery."
)
