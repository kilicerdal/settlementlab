# Engineering decisions

These records explain decisions visible in the current implementation. They are retrospective documentation, not a claim that a production design review occurred.

| Record | Decision | Evidence to inspect |
|---|---|---|
| [001](001-atomic-settlement.md) | Commit settlement and its financial evidence in one transaction | Injected failure rollback and competing-spend tests |
| [002](002-replay-and-stale-writes.md) | Treat replay identity and expected version as separate controls | Same-key replay, conflicting payload and competing revision tests |
| [004](004-durable-settlement.md) | Persist work and separate atomic financial effects from at-least-once observation | Six real process crash checkpoints and reviewed recovery |
| [003](003-advisory-ai.md) | Give AI bounded facts and no mutation interface | Envelope minimization, citation rejection and unchanged-trade API tests |

| [005](005-independent-assurance.md) | Retain independent economic expectations and report measured limits | Balanced-but-wrong mutation, generated sequences and full-day scorecard |

| [006](006-versioned-obligations.md) | Bind approvals to economic revisions; preserve posted slices and imported discrepancies | Amendment fencing, partial atomicity, statement evidence and schema 6 upgrade |

| [007](007-incident-and-compensation.md) | Link incident evidence and authorize immutable compensating batches | Real worker interruption, inverse-leg oracle, reviewer fixture and local AI abstention samples |

Read the tradeoff and limits alongside the evidence. A passing local test is not a throughput benchmark, identity audit or model-quality evaluation.
