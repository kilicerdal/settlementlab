"""Real financial-position worker and UI: historical delivery survives net correction."""

import json
import os
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from settlementlab.assurance.durable_data import CHECKER, approved_trade, entry
from settlementlab.assurance.fixtures import LocalEnvironment
from settlementlab.assurance.incident_export import verify

output = Path("artifacts/v44-browser")
output.mkdir(parents=True, exist_ok=True)
with LocalEnvironment() as env, sync_playwright() as playwright:
    trade = approved_trade(env.app.service)
    env.app.operations.enqueue_batch([dict(entry(trade), quantity=20)], "ui-position", CHECKER)
    assert env.app.operations.process_one("settlement-worker")["status"] == "SUCCEEDED"
    assert env.app.operations.deliver_one("historical-observer")["status"] == "DELIVERED"
    browser = playwright.chromium.launch()
    page = browser.new_page(viewport=dict(width=1440, height=1080), accept_downloads=True)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def deliver():
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "settlementlab.position_worker",
                "--db",
                env.app.settings.database,
                "--once",
            ],
            env=dict(os.environ, PYTHONPATH=str(Path("src").resolve())),
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["status"] == "DELIVERED"

    page.goto(env.base_url + "/investigation")
    expect(page.locator("#position-status")).to_contain_text("LAGGING")
    deliver()
    page.get_by_role("button", name="Refresh evidence").click()
    expect(page.locator("#position-status")).to_contain_text("CURRENT")
    page.get_by_label("Demo identity").select_option("maker-alex")
    page.get_by_label("Correction reason", exact=True).fill("Review explicit UI correction")
    page.get_by_role("button", name="Request reversal", exact=True).click()
    expect(page.locator("#pending")).to_contain_text("Pending CR-")
    page.get_by_label("Demo identity").select_option("checker-sam")
    page.get_by_label("Checker review reason").fill("Confirmed exact compensating impacts")
    page.get_by_label(
        "I reviewed the original entries and the proposed compensating impacts."
    ).check()
    page.get_by_role("button", name="Approve compensation", exact=True).click()
    expect(page.locator("#position-status")).to_contain_text("LAGGING")
    self_observed = json.loads(page.locator("#position-observed").inner_text())
    assert self_observed["net_quantity"] == 20
    deliver()
    page.get_by_role("button", name="Refresh evidence").click()
    expect(page.locator("#position-status")).to_contain_text("CURRENT")
    assert json.loads(page.locator("#position-observed").inner_text())["net_quantity"] == 0
    historical = env.app.operations.snapshot()["observer"]
    assert historical[0]["state"] == "PARTIALLY_SETTLED"
    graph = env.client.request("/api/trades/" + trade["id"] + "/investigation")
    original = graph["trade"]["execution_slices"][0]["batch_id"]
    plan = dict(
        format_version=1,
        trade_id=trade["id"],
        terms=dict(
            buyer_id=trade["buyer_id"],
            seller_id=trade["seller_id"],
            symbol="NOVA",
            price_cents=4275,
            quantity=100,
        ),
        executions=[dict(batch_id=original, quantity=20)],
        compensations=[original],
    )
    plan_path = output / "accepted.json"
    plan_path.write_text(json.dumps(plan))
    with page.expect_download() as download:
        page.get_by_role("link", name="Download incident evidence").click()
    path = output / "incident.zip"
    download.value.save_as(path)
    assert verify(path, plan_path)["status"] == "passed"
    page.screenshot(path=str(output / "position-desktop.png"), full_page=True)
    page.set_viewport_size(dict(width=390, height=844))
    page.screenshot(path=str(output / "position-mobile.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    assert not errors, errors
    (output / "results.json").write_text(
        json.dumps(
            dict(
                status="passed",
                historical_delivery_retained=True,
                observed_net_quantity=0,
                external_expectations_verified=True,
                javascript_errors=errors,
            ),
            indent=2,
        )
    )
    browser.close()
