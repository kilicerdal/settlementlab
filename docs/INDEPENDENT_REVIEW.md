# Independent engineering review

Status: **not performed; outside review is not requested for V4.4**. No external reviewer request has been sent. Automated tests, mutation results and AI assistance are not an independent human review. No reviewer identity or approval has been fabricated.

For V4.3, begin with the [isolated incident exercise](V4_3.md#independent-reviewer-exercise), compare original and compensating financial legs, if an independent review is requested in the future.

A reviewer should use a fresh checkout and the evidence commands in `V4_2.md`, then record their name, reviewed commit, environment, findings and disposition in a pull-request review. Review at least:

- Partial posting conserves each asset and follows independently retained terms; balanced wrong-value tampering is detected.
- Amendment cannot rewrite posted terms, reuse old approvals or leave claimed workers authorized.
- Replay, optimistic version checks and role checks survive realistic concurrent commands.
- Failed transaction recovery cannot leave a financial posting without its receipt and event.
- Statement resolution retains original discrepancies and requires corrected numeric evidence.
- Schema upgrade is additive, failure is atomic, and rollback uses a backup rather than schema tampering.
- Standalone installation and scenario extension work without the financial reference application.
- README claims match measured evidence and simulation boundaries.

Open findings should state severity, a reproducible trigger, expected/actual behavior and an acceptance check. Resolve findings in code or document an explicit accepted limitation before release. A checked checklist without an identifiable reviewer and commit is not review evidence.
