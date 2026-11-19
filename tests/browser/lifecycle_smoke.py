"""Exercise real V4.2 UI commands and imported evidence in desktop/mobile layouts."""

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from settlementlab.assurance.durable_data import approved_trade
from settlementlab.assurance.fixtures import LocalEnvironment

output = Path("artifacts/v42/browser")
output.mkdir(parents=True, exist_ok=True)
with LocalEnvironment() as environment, sync_playwright() as playwright:
    trade = approved_trade(environment.app.service, "browser-lifecycle")
    browser = playwright.chromium.launch()
    page = browser.new_page(viewport=dict(width=1440, height=1080))
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(environment.base_url + "/lifecycle")
    expect(page.get_by_role("heading", name="Aging and executed value")).to_be_visible()
    page.get_by_label("Demo identity").select_option("checker-sam")
    page.get_by_role("button", name="Partial execution", exact=True).click()
    page.get_by_label("Execution quantity").fill("25")
    page.get_by_role("button", name="Confirm command").click()
    expect(page.locator("#trades")).to_contain_text("PARTIALLY_SETTLED")
    expect(page.locator("#trades")).to_contain_text("25 / 75")
    page.get_by_label("Statement CSV").fill(
        "trade_id,quantity,amount_cents\n" + trade["id"] + ",24,102600\n"
    )
    page.get_by_role("button", name="Import statement", exact=True).click()
    expect(page.locator("#cases")).to_contain_text("VALUE_MISMATCH")
    page.get_by_label("Statement CSV").fill(
        "trade_id,quantity,amount_cents\n" + trade["id"] + ",25,106875\n"
    )
    page.get_by_role("button", name="Import statement", exact=True).click()
    expect(page.locator("#statement-id")).to_contain_text("0 discrepancy cases")
    followup = (
        page.locator("#statement-id").inner_text().split("Imported evidence: ")[1].split(" · ")[0]
    )
    page.get_by_role("button", name="Resolve with evidence").click()
    page.get_by_label("Imported follow-up statement ID").fill(followup)
    page.get_by_label("Review reason", exact=True).last.fill(
        "Counterparty supplied corrected statement"
    )
    page.get_by_role("button", name="Verify and resolve").click()
    expect(page.locator("#cases")).to_contain_text("RESOLVED")
    page.screenshot(path=str(output / "desktop.png"), full_page=True)
    page.get_by_role("button", name="Cancel remainder", exact=True).click()
    page.get_by_label("Review reason", exact=True).first.fill(
        "Counterparty withdrew remaining obligation"
    )
    page.get_by_role("button", name="Confirm command").click()
    expect(page.locator("#trades")).to_contain_text("CANCELLED")
    page.set_viewport_size(dict(width=390, height=844))
    page.screenshot(path=str(output / "mobile.png"), full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
        "Mobile page overflows viewport"
    )
    assert not errors, errors
    (output / "results.json").write_text(
        json.dumps(
            dict(
                status="passed",
                javascript_errors=errors,
                controls=[
                    "partial execution",
                    "external CSV discrepancy",
                    "corrected evidence resolution",
                    "cancellation retains partial value",
                    "mobile viewport",
                ],
            ),
            indent=2,
        )
    )
    browser.close()
