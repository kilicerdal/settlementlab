# Short SettlementLab walkthrough

[Watch/download the captioned recording](https://github.com/kilicerdal/settlementlab/releases/download/v3.0.0/settlementlab-walkthrough.webm) · [Recording provenance and scene timestamps](https://github.com/kilicerdal/settlementlab/releases/download/v3.0.0/settlementlab-walkthrough.json) · [Engineering decisions](decisions/README.md)

The video records actual local browser actions, followed by reports generated immediately before recording. On-screen captions pace the explanation; pauses do not simulate processing progress. It is silent, with a narration script below for a personal presentation. It does not claim a live AI run, production connectivity or verified human identity.

## Narration script

Use your own voice and adjust the wording naturally. The sequence takes roughly 80–90 seconds; the JSON attachment records the actual scene times.

| Scene | Suggested narration |
|---|---|
| Introduction | “This is SettlementLab, a Python financial assurance framework. This demonstration uses synthetic trades and a visibly simulated business date.” |
| Two matching breaks | “The broker and manager submit terms separately. Here the price differs, and the allocations are short by one hundred shares. Those are two distinct findings.” |
| Manager correction | “Correcting the manager submission creates a new revision. The original broker terms and earlier manager submission remain available.” |
| Maker/checker review | “The maker requests instruction approval. A separate checker approves it. These are switchable demo identities, not production login.” |
| Failed settlement | “Approval does not guarantee settlement capacity. The first attempt fails because the shared balances are insufficient.” |
| Recovery and journal | “After synthetic funding, settlement posts four balanced journal lines in one transaction. Storage-failure and competing-spend regressions test that boundary.” |
| Reconciliation | “The settled trade reconciles against the statement.” |
| Independent service | “The same assurance engine also tests an independently implemented collateral reservation API.” |
| Healthy control and defect | “The healthy control passes. In the deliberately faulty variant, replay creates another reservation. The report detects the exact expected-versus-observed status mismatch.” |
| Closing point | “The important evidence is reproducible: application behavior, independent expected values, failure diagnostics, and documented tradeoffs.” |

## Reproduce without paid services

From the source checkout, use an environment with the package and optional Playwright tooling installed:

```sh
python -m pip install . 'playwright>=1.48,<2'
python -m playwright install chromium
PYTHONPATH=src python -m scripts.record_walkthrough
```

Outputs under artifacts/walkthrough/: walkthrough.webm, poster.png, walkthrough.json, raw browser recording and portable evidence reports. An existing final recording is not overwritten; use `--output artifacts/walkthrough-another-run` for another capture. The script owns its temporary loopback service/database and closes them. It asserts observed lifecycle/report outcomes and makes zero model calls. The source commit, evidence manifest and timestamps are recorded.

Do not imply that the recording itself ran every regression test. The separate full-suite CI and decision records identify those checks. The AI decision is explained through its implementation and contract tests; optional live inference is documented in AI.md.
