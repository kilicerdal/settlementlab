"""Real browser investigation: correlated evidence, export and maker/checker compensation."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from settlementlab.assurance.durable_data import CHECKER, approved_trade
from settlementlab.assurance.fixtures import LocalEnvironment
from settlementlab.assurance.incident_demo import seed
from settlementlab.assurance.incident_export import verify

output = Path("artifacts/v43-browser")
output.mkdir(parents=True, exist_ok=True)
with LocalEnvironment() as environment, sync_playwright() as playwright:
    report = seed(environment.app, output, crash=False)
    fresh = approved_trade(environment.app.service, "browser-correction")
    fresh = environment.app.service.command(
        fresh["id"],
        "settle-partial",
        dict(version=fresh["version"], quantity=20, request_key="ui-slice"),
        principal=CHECKER,
    )
    browser = playwright.chromium.launch()
    page = browser.new_page(viewport=dict(width=1440, height=1080), accept_downloads=True)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(environment.base_url + "/investigation")
    expect(
        page.get_by_role("heading", name="From accepted terms to accounting result")
    ).to_be_visible()
    page.get_by_label("Investigation trade").select_option(report["trade_id"])
    expect(page.locator("#context")).to_contain_text("REVERSED")
    page.get_by_label("Timeline filter").select_option("worker")
    expect(page.locator("#timeline")).to_contain_text("LEASE_EXPIRED")
    page.get_by_label("Timeline filter").select_option("statement")
    expect(page.locator("#timeline")).to_contain_text("Case resolved")
    page.get_by_label("Timeline filter").select_option("financial")
    expect(page.locator("#timeline")).to_contain_text("DVP_REVERSAL")
    page.locator("#timeline button").last.click()
    expect(page.locator("#details")).not_to_be_empty()
    with page.expect_download() as download:
        page.get_by_role("link", name="Download incident evidence").click()
    path = output / "download.zip"
    download.value.save_as(path)
    assert verify(path)["status"] == "passed"
    page.screenshot(path=str(output / "incident-desktop.png"), full_page=True)
    page.get_by_label("Investigation trade").select_option(fresh["id"])
    page.get_by_label("Demo identity").select_option("maker-alex")
    page.get_by_label("Correction reason", exact=True).fill(
        "Review synthetic UI compensation request"
    )
    page.get_by_role("button", name="Request reversal", exact=True).click()
    expect(page.locator("#pending")).to_contain_text("Pending CR-")
    page.get_by_label("Demo identity").select_option("checker-sam")
    page.get_by_label("Checker review reason").fill(
        "Independent checker confirmed original execution and compensating impacts"
    )
    page.get_by_label(
        "I reviewed the original entries and the proposed compensating impacts."
    ).check()
    page.get_by_role("button", name="Approve compensation", exact=True).click()
    expect(page.locator("#net")).to_have_text("0")
    expect(page.locator("#gross")).to_have_text("20")
    expect(page.locator("#reversed")).to_have_text("20")
    expect(page.locator("#corrections")).to_contain_text("APPROVED")
    page.set_viewport_size(dict(width=390, height=844))
    page.screenshot(path=str(output / "incident-mobile.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth<=innerWidth"), (
        "Page overflows mobile viewport"
    )
    assert not errors, errors
    (output / "results.json").write_text(
        json.dumps(
            dict(
                status="passed",
                javascript_errors=errors,
                controls=[
                    "linked interruption and resolution timeline",
                    "portable evidence download",
                    "maker/checker compensation",
                    "gross/reversed/net display",
                    "mobile viewport",
                ],
            ),
            indent=2,
        )
    )
    browser.close()
