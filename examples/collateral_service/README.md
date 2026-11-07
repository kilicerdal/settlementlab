# Independent collateral reservation demonstration

This separate application implements synthetic inventory, reservations, idempotent release and replay conflict handling. It uses its own SQLite schema and imports no SettlementLab modules. It is a local reference target, not a production collateral or custody service.

From the repository root:

```sh
python -m examples.collateral_service.server --port 8090 --db /tmp/collateral-demo.db
```

In another terminal, use the installed framework:

```sh
settlementlab-assure --suite scenarios --target-profile targets/collateral.json --report-dir artifacts/reuse-control
```

The healthy catalog creates a unique synthetic asset per scenario, reserves shares, rejects oversubscription, releases exactly once and checks replay identity/inventory. Expectations are declared in the scenario files, not calculated by importing this service.

For the deliberately broken implementation, start a separate database/port:

```sh
python -m examples.collateral_service.server --port 8091 --db /tmp/collateral-fault.db --fault-duplicate-replay
settlementlab-assure --suite scenarios --target collateral --base-url http://127.0.0.1:8091 --report-dir artifacts/reuse-fault
```

That assurance command should fail: C02 expects HTTP 200 for replay but observes 201. The injected fault creates a second reservation and subtracts inventory twice. It is explicit, opt-in and never enabled for the healthy control. A failed report is the desired detection evidence; it is not presented as a passing test execution.

The example is source-only, separate from the framework wheel. It has no authentication and must use synthetic data on loopback. Stop it with Ctrl+C. A second real production API would require its own contract, authentication adapter and validation.
