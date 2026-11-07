# V3.0 showcase guide

## Choose the experience

- Website visitors: [recorded case study](https://www.eai.engineering/engineering/settlementlab). No local service or model is exposed through that page.
- Reviewers with the repository: run the model-free evidence package, then inspect the application.
- Framework contributors: use the full assurance suite and target extension guide.

## Reproduce the evidence

From the repository root, install with `.venv/bin/python -m pip install .`, then:

```sh
.venv/bin/python -m scripts.showcase
.venv/bin/python -m scripts.showcase --verify
```

Open `artifacts/showcase/index.html`. Copy the entire directory to share it or inspect it offline. No runtime service is needed to read the reports. `--output PATH` selects another directory. The command runs four financial scenarios, two healthy collateral scenarios and two scenarios against the explicit faulty variant. It requires loopback TCP permissions, uses temporary SQLite databases, and closes its services before returning. Repeated runs create unique collateral inventory keys.

Success requires all six positive scenarios to pass, C01 to remain passing against the faulty variant, and C02 to fail specifically because replay returns 201 instead of 200. Broken setup, missing cases or an unrelated 500 response fail the showcase. The failed negative report is evidence of detection, not a broken showcase.

`manifest.json` records UTC generation time, framework/Python versions, Git HEAD and dirty state, and SHA-256 for the HTML entry page and nine report artifacts. Source provenance uses the current checkout and requires Git. Offline verification compares these checksums and validates report outcomes without starting services. The manifest is unsigned: someone able to replace both it and the artifacts can replace the evidence. It is not a trust certificate.

## Five-minute presentation

| Time | Demonstration | Engineering point |
|---|---|---|
| 0:00–0:45 | Open the portable entry page and explain the two services | Assurance engine is reusable independently of the main application |
| 0:45–1:30 | Open healthy collateral and negative replay reports | Exact expected/actual evidence; unrelated failure cannot count as detection |
| 1:30–3:30 | Run the console journey below | Financial invariants, controlled transitions and recoverable exceptions |
| 3:30–4:15 | Show architecture and target profile/catalog | Extension surface and separation of responsibilities |
| 4:15–5:00 | Show CI and explain local AI boundaries | Measured evidence, optional inference and honest scope |

## Live console journey

Start `.venv/bin/settlementlab --config environments/showcase.json --db /tmp/settlementlab-presentation.db` with an unused database filename. Open http://127.0.0.1:8085. Confirm the visible simulated business date is 2026-11-09; real audit time is separate.

1. **Run showcase scenario.** Inspect the broker price 42.75 versus manager price 42.80 and manager allocations totaling 9,900 against quantity 10,000. Two breaks are distinct.
2. Optionally **Analyze exception with AI** if a local model is installed. Explain that the output is advisory and references supplied facts; do not represent it as an accuracy measurement.
3. **Revise manager submission** to price 42.75 and allocations `SYN-FUND-ALPHA,6000` / `SYN-FUND-BETA,4000`. State becomes MATCHED; earlier terms remain in revision history.
4. As **Alex · Maker**, request approval. Self-approval is unavailable. Switch to **Sam · Checker**, inspect and approve. State becomes AFFIRMED.
5. Attempt settlement. Insufficient capacity yields FAILED without settlement postings. Fund synthetic shared shortfalls, retry, and inspect SETTLED with four balanced journal lines.
6. Reconcile the statement and inspect BALANCED. Switch to **Casey · Auditor** to show read-only controls. Explain that freely switchable personas demonstrate role rules, not verified human identities.

The calendar rejection scenarios in the portable reports use separate fixed clocks; the funded live trade is already date-eligible. Do not claim the calendar uses official market holidays. To repeat on a fresh database, stop the server and use a new filename; do not delete another working database.

## Browser and AI verification

Start the showcase server separately. Install optional browser tooling:

```sh
.venv/bin/python -m pip install 'playwright>=1.48,<2'
.venv/bin/python -m playwright install chromium
SETTLEMENTLAB_URL=http://127.0.0.1:8085 .venv/bin/python tests/browser/smoke.py
# Optional real local inference, with Ollama and the model already installed:
SETTLEMENTLAB_URL=http://127.0.0.1:8085 SETTLEMENTLAB_TEST_LOCAL_AI=1 .venv/bin/python tests/browser/smoke.py
```

The browser journey tests desktop/mobile independent submissions, approvals, recovery, reconciliation and role/filter controls. It writes screenshots and a trace to artifacts/. CI does not require Ollama. The model-free showcase manifest does not imply browser execution, full-suite coverage or a live-model run; those records remain separate.

## Evidence publication

Public website reports contain synthetic data only. Do not publish coverage HTML that renders private repository source. The private release can hold detailed coverage and source evidence. Keep historical V1/V2 screenshots labeled; do not present old captures as current runs. Never publish the loopback application as a shared authenticated production service.
