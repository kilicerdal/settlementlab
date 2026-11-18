# Framework-depth implementation handoff

Prepared November 18, 2026 for branch codex/framework-depth. This is a review snapshot; the upgrade is not merged or released and does not modify the website.

## Completed

- External scenario folders run with the installed CLI, using bounded preflight validation, saved response references, run namespaces and exact JSON assertions.
- Recovery checks reproduce a lost response after commit, a timeout after commit, a hard restart of an owned child process and a truncated response that would otherwise contain valid JSON.
- The packaged AI corpus contains four preserved historical model responses and five synthetic controls. Agent-reviewed criterion labels and deterministic scoring explicitly retain failures. No live inference was run.
- Six additional complete assurance modules are covered by strict mypy, for 14 checked source files total. Explicit Any remains at dynamically validated JSON boundaries; the financial workflow is not claimed fully typed.
- Offline HTML places failures first and links to the exact failing step, declared control, sanitized request metadata and expected/actual comparison. JSON/JUnit remain available.

## Verified locally

110 deterministic cases passed. Combined statement/branch coverage: **87.66%**, above the existing 85% gate. Ruff lint and formatting, strict mypy, wheel build and local documentation links passed.

A fresh environment outside the checkout installed the wheel without runtime dependencies. Its external user pack passed against the healthy independent service and failed specifically with expected 200 / actual 201 against the deliberately faulty variant. The packaged offline AI evaluator also ran there.

The financial browser journey passed desktop/mobile submission, approval, recovery, reconciliation, role restrictions and filters. Separate browser checks passed failure-anchor navigation and narrow-screen overflow handling for the new reports. No browser check invoked a model.

The AI rubric review classifies **2 responses as meeting all bounded checks and 7 as not meeting them**. Harness agreement with labels passes. These counts are not model accuracy, and review is not independent human review. See [evaluation limits](AI_EVALUATION.md).

Exact local totals and assurance source hashes: [verification snapshot](evidence/framework-depth-review.json). Local reproducible outputs are under artifacts/reports, artifacts/coverage and artifacts/upgrade; CI uploads its own independently generated evidence.

## Remaining boundaries

General authentication, distributed load/processing, official market calendars and full application typing remain outside this branch. Regex rubric checks are limited to the reviewed examples and cannot establish general semantic accuracy. A human/independent review and a new live-model campaign are separate future work.

The original checkout's uncommitted README and failure-explainer files were not edited, staged or moved. Work is isolated in its own managed checkout. No paid service, production configuration, website source or release tag was changed. The next decision is review/merge of the draft PR, followed by a separately authorized release if desired.
