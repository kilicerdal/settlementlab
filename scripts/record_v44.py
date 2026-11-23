"""Record a real captioned V4.4 incident; no model, product UI edits or simulated video."""

import argparse
import hashlib
import html
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from settlementlab import __version__
from settlementlab.assurance.durable_data import CHECKER, approved_trade, entry
from settlementlab.assurance.fixtures import LocalEnvironment


def record(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root))
    child_env = dict(os.environ, PYTHONPATH=str(root / "src"))
    scenes, commands, errors = [], [], []
    started = datetime.now(timezone.utc).isoformat()

    def run(arguments, name, expected=0):
        result = subprocess.run(
            [sys.executable, "-m"] + arguments,
            env=child_env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        (output / (name + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
        commands.append(dict(module=arguments[0], exit_code=result.returncode, log=name + ".log"))
        if result.returncode != expected:
            raise RuntimeError(name + ": " + result.stdout + result.stderr)
        return result

    with LocalEnvironment() as env, sync_playwright() as playwright:
        trade = approved_trade(env.app.service, "recording-v44", quantity=100)
        env.app.operations.enqueue_batch([dict(entry(trade), quantity=40)], "recording-40", CHECKER)
        worker = ["settlementlab.worker", "--db", env.database, "--business-date", "2026-11-09"]
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport=dict(width=1440, height=1080),
            record_video_dir=str(output / "raw"),
            record_video_size=dict(width=1440, height=1080),
            accept_downloads=True,
        )
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        video = page.video
        clock = time.monotonic()

        def scene(title, detail, seconds=11):
            page.evaluate(
                """({title, detail}) => {
                  let caption = document.getElementById('recording-caption');
                  if (!caption) { caption=document.createElement('aside');
                    caption.id='recording-caption';document.body.append(caption); }
                  caption.style.cssText='position:fixed;bottom:0;left:0;right:0;z-index:2147483647;background:#06131ff5;color:#e8f3ef;padding:18px 32px;border-top:2px solid #a3dfca;font:17px/1.5 system-ui;pointer-events:none';
                  caption.replaceChildren();
                  const heading=document.createElement('strong');heading.textContent=title;
                  heading.style.cssText='display:block;color:#a3dfca;font-size:23px';
                  const text=document.createElement('span');text.textContent=detail;
                  caption.append(heading,text);
                }""",
                dict(title=title, detail=detail),
            )
            scenes.append(
                dict(at_seconds=round(time.monotonic() - clock, 2), title=title, text=detail)
            )
            print(title, flush=True)
            page.wait_for_timeout(seconds * 1000)

        try:
            page.goto(env.base_url + "/operations")
            scene(
                "SettlementLab / V4.4",
                "Actual local execution • synthetic USD equities • captioned, silent • AI disabled",
            )
            scene(
                "01 / An approved obligation enters the queue",
                "100 shares at $42.75. The queued instruction executes 40 shares, not the full obligation.",
            )
            run(
                worker
                + [
                    "--worker-id",
                    "interrupted-worker",
                    "--lease",
                    "0.1",
                    "--mode",
                    "process",
                    "--once",
                    "--fault",
                    "after-claim",
                ],
                "worker-interruption",
                73,
            )
            page.reload()
            scene(
                "02 / Interrupt a real child worker",
                "Injected checkpoint exit 73 occurs after claim commit. No financial execution has occurred yet.",
            )
            time.sleep(0.15)
            run(
                worker + ["--worker-id", "recovery-worker", "--mode", "process", "--once"],
                "worker-recovery",
            )
            assert env.app.operations.deliver_one("historical-observer")["status"] == "DELIVERED"
            page.goto(env.base_url + "/investigation")
            expect(page.locator("#gross")).to_contain_text("40")
            expect(page.locator("#timeline")).to_contain_text("LEASE_EXPIRED")
            page.get_by_label("Timeline filter").select_option("worker")
            page.locator("#timeline").scroll_into_view_if_needed()
            scene(
                "03 / Recover the expired claim",
                "A fresh worker completes one execution. LEASE_EXPIRED remains in the attempt history; recovery does not erase it.",
            )
            page.get_by_label("Timeline filter").select_option("all")
            page.locator("#position").scroll_into_view_if_needed()
            expect(page.locator("#position-status")).to_contain_text("LAGGING")
            scene(
                "04 / Posting and observation are separate",
                "Authoritative quantity is 40. The financial-position observer has not consumed its event yet.",
            )
            run(
                ["settlementlab.position_worker", "--db", env.database, "--once"],
                "observe-execution",
            )
            page.get_by_role("button", name="Refresh evidence").click()
            expect(page.locator("#position-status")).to_contain_text("CURRENT")
            page.locator("#position").scroll_into_view_if_needed()
            scene(
                "05 / Deliver the financial-position event",
                "The real position worker brings the observed quantity to 40. Historical settlement delivery is a separate stream.",
            )
            page.get_by_label("Demo identity").select_option("maker-alex")
            page.get_by_label("Correction reason", exact=True).fill(
                "Synthetic exercise: compensate the original 40-share execution"
            )
            page.get_by_role("button", name="Request reversal", exact=True).click()
            expect(page.locator("#pending")).to_contain_text("Pending CR-")
            page.locator("#pending").scroll_into_view_if_needed()
            scene(
                "06 / Request a controlled correction",
                "Alex requests reversal of the original batch. The UI uses freely switchable demo identities, not production authentication.",
            )
            page.get_by_label("Demo identity").select_option("checker-sam")
            page.get_by_label("Checker review reason").fill(
                "Reviewed original batch and exact inverse cash/security impacts"
            )
            page.get_by_label(
                "I reviewed the original entries and the proposed compensating impacts."
            ).check()
            page.get_by_role("button", name="Approve compensation", exact=True).click()
            expect(page.locator("#position-status")).to_contain_text("LAGGING")
            observed = json.loads(page.locator("#position-observed").inner_text())
            authoritative = json.loads(page.locator("#position-truth").inner_text())
            assert observed["net_quantity"] == 40 and authoritative["net_quantity"] == 0
            page.locator("#position").scroll_into_view_if_needed()
            scene(
                "07 / Compensation commits; observation lags",
                "Sam approves. Gross 40, reversed 40, authoritative net zero. The observer still shows 40 until delivery.",
            )
            run(
                ["settlementlab.position_worker", "--db", env.database, "--once"],
                "observe-compensation",
            )
            page.get_by_role("button", name="Refresh evidence").click()
            expect(page.locator("#position-status")).to_contain_text("CURRENT")
            observed = json.loads(page.locator("#position-observed").inner_text())
            assert observed["net_quantity"] == observed["net_amount_cents"] == 0
            assert env.app.operations.snapshot()["observer"][0]["state"] == "PARTIALLY_SETTLED"
            page.locator("#position").scroll_into_view_if_needed()
            scene(
                "08 / Observed net zero; history retained",
                "The observer is current at zero. The original execution receipt remains PARTIALLY_SETTLED; no history was overwritten.",
            )
            page.screenshot(path=str(output / "poster.png"))
            graph = env.client.request("/api/trades/" + trade["id"] + "/investigation")
            original = graph["trade"]["execution_slices"][0]["batch_id"]
            assert len(graph["trade"]["execution_slices"]) == 1
            plan = dict(
                format_version=1,
                trade_id=trade["id"],
                terms=dict(
                    buyer_id=trade["buyer_id"],
                    seller_id=trade["seller_id"],
                    symbol="NOVA",
                    quantity=100,
                    price_cents=4275,
                ),
                executions=[dict(batch_id=original, quantity=40)],
                compensations=[original],
            )
            (output / "accepted-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
            with page.expect_download() as download:
                page.get_by_role("link", name="Download incident evidence").click()
            download.value.save_as(output / "incident.zip")
            scene(
                "09 / Export evidence with a separate plan",
                "Expected terms come from declared scenario inputs; the command receipt supplies batch identity. The plan stays outside the ZIP.",
            )
            result = run(
                [
                    "settlementlab.assurance.incident_demo",
                    "--verify",
                    str(output / "incident.zip"),
                    "--expectations",
                    str(output / "accepted-plan.json"),
                ],
                "verification",
            )
            verification = json.loads(result.stdout)
            assert verification["status"] == "passed"
            assert verification["verification_level"] == "INTEGRITY_AND_SCOPED_ECONOMICS"
            report = (
                "<!doctype html><meta charset=utf-8><title>V4.4 verification output</title><style>body{background:#06131f;color:#e8f3ef;font:20px/1.5 system-ui;padding:40px}pre{font:18px/1.5 monospace;white-space:pre-wrap}h1{color:#a3dfca}</style><h1>Separate-process verification / actual JSON output</h1><p>Checksums plus scoped economic checks against the external scenario plan. No human attestation.</p><pre>"
                + html.escape(result.stdout)
                + "</pre>"
            )
            (output / "verification.html").write_text(report, encoding="utf-8")
            page.goto((output / "verification.html").as_uri())
            scene(
                "10 / Verify in a separate process",
                "Passed: content integrity plus scoped economics. Balanced entries alone are insufficient; participants, assets, signs and amounts must match.",
                14,
            )
            page.goto(env.base_url + "/investigation")
            page.locator("#position").scroll_into_view_if_needed()
            scene(
                "11 / What this demonstrates",
                "Recovery, separate observers, controlled compensation and portable verification. Local simulation; no real money, production identity or live AI call.",
                14,
            )
            assert not errors, errors
            elapsed = round(time.monotonic() - clock, 2)
        finally:
            context.close()
            video.save_as(str(output / "walkthrough.webm"))
            video.delete()
            browser.close()
    files = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()
    }
    metadata = dict(
        status="passed",
        framework_version=__version__,
        source_commit=source,
        working_tree_dirty=dirty,
        started_at=started,
        python=platform.python_version(),
        duration_seconds=elapsed,
        audio="none; visible captions",
        scope="Actual browser actions, real child workers and separate-process verifier; synthetic inputs; no live AI",
        commands=commands,
        scenes=scenes,
        javascript_errors=errors,
        files=files,
    )
    (output / "walkthrough.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print("Saved " + str(output / "walkthrough.webm"), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/v44-walkthrough")
    record(parser.parse_args().output)


if __name__ == "__main__":
    main()
