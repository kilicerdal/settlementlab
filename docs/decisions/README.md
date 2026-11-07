# Engineering decisions

These records explain decisions visible in the current implementation. They are retrospective documentation, not a claim that a production design review occurred.

| Record | Decision | Evidence to inspect |
|---|---|---|
| [001](001-atomic-settlement.md) | Commit settlement and its financial evidence in one transaction | Injected failure rollback and competing-spend tests |
| [002](002-replay-and-stale-writes.md) | Treat replay identity and expected version as separate controls | Same-key replay, conflicting payload and competing revision tests |
| [003](003-advisory-ai.md) | Give AI bounded facts and no mutation interface | Envelope minimization, citation rejection and unchanged-trade API tests |

Read the tradeoff and limits alongside the evidence. A passing local test is not a throughput benchmark, identity audit or model-quality evaluation.
