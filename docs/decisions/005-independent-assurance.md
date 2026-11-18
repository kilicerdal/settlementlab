# 005 — retain independent economic expectations

Decision: derive expected DVP movements from a seeded input plan, keep the oracle free of settlement/posting imports, and read the full database in one read-only snapshot. Store exact expected/observed movement comparisons in reviewer evidence.

Reason: a journal may conserve every asset and match its materialized balances while transferring the wrong economic amount. Tests that derive expected values from the implementation under test can repeat the same defect. The mutation control preserves conservation/projection while changing both cash legs; the separate oracle must reject it.

Tradeoff: the oracle understands the lab schema and simplified BUY/SELL conventions. It is separate code, not an independent financial institution or market rule authority. It checks funding conservation but not external funding authorization. A bug in the input plan can still affect expectations, so inputs, seeds, implementation and explicit scope remain inspectable.

Keep measurements descriptive: SQLite serializes writes, and the scorecard records actual worker participation rather than implying linear scaling. Generated tests are bounded, reproducible samples rather than exhaustive proof. Offline AI rubric agreement and live model outcomes remain separate.

Evidence: [oracle](../../src/settlementlab/assurance/oracle.py), [economic mutation](../../tests/integration/test_independent_oracle.py), [campaign](../../src/settlementlab/assurance/campaign.py), and [reviewer guide](../V4_1_ASSURANCE.md).
