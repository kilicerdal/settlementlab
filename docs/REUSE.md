# V2.6 reuse evidence and target extension

The same installed assurance engine now exercises two separate applications: the SettlementLab financial workflow and the independently implemented collateral reservation reference API. This demonstrates reuse across two owned local services, not independent certification or a third-party production integration.

## Shared components

JsonClient provides bounded JSON transport, isolated cookies, explicit timeouts, typed connection/timeout/JSON/size errors and exact HTTP status metadata. Redirects are not silently followed. Diagnostics omit query strings, request headers and request bodies. Assertion failures retain the explicitly compared path, expected value and observed value; those values are not automatically redacted. Use synthetic inputs and avoid asserting real credentials into reports.

SettlementClient extends this transport with domain-specific commands. The collateral catalog uses generic HTTP steps, so the runner never starts the SettlementLab application for that target. HTTPEnvironment owns a server/thread independently of application setup; LocalEnvironment composes that fixture with the financial service. RunKeys supplies unique namespaces; TradeFactory adds financial payloads only for the financial target.

## Target profiles

`targets/collateral.json` declares target, base_url and timeout. Precedence is defaults < target-profile JSON < SETTLEMENTLAB_TARGET/BASE_URL/TIMEOUT < explicit CLI flags. Base URLs reject embedded credentials, query strings and fragments; timeout must be finite, greater than zero and at most 60 seconds. Invalid configuration returns exit code 2 and produces a failure report. Unknown catalogs and execution failures return a failing report/exit code.

Financial scenarios own fresh local fixtures. Generic HTTP targets use an explicitly supplied running service; the framework does not reset or delete that service's data. Scenario run namespaces prevent collisions for the reference service. No credential configuration or production authentication is provided in this increment.

## Generic HTTP steps

Collateral scenarios are packaged as C01/C02 with target=collateral. HTTP actions declare method (GET/POST), relative path, optional data/idempotency key, expected status and exact assertions. `${run_id}` and `${reservation.id}` substitute data/path values. `{"$ref":"reservation.id"}` references a previously saved JSON response value. `save` names a response alias. Resolution uses JSON dictionaries/lists, not Python evaluation or shell execution.

Expected HTTP responses include successful and rejected operations. Unexpected status is recorded as `failure.kind=http_status`, with expected/actual values. Assertion mismatch records kind, path and values. Requests retain method, sanitized path, observed status and duration. JSON/HTML reports include this evidence, and JUnit records failing cases. Scenarios stop at first unexpected outcome.

## Reproduce the demonstration

Start the independent service and run the commands in examples/collateral_service/README.md, or capture both variants from the checkout:

```sh
PYTHONPATH=src python -m scripts.capture_reuse
```

Outputs: docs/evidence/reuse-v26.json plus artifacts/reuse-control and artifacts/reuse-injected_fault reports. The capture asserts that the healthy service passes and the explicit duplicate-replay fault fails at the expected contract check. CI also starts both services as separate processes and uses the installed CLI. It verifies the exact fault, not merely any nonzero exit.

Tests additionally forbid financial application startup during second-target execution, verify independent source imports, confirm repeated scenario isolation, and check configuration/transport/error-report behavior. The second target's reference code is not bundled in the framework wheel; packaged HTTP scenarios can run against its separately launched endpoint.

## Boundaries

Supported extension surface is JSON over HTTP GET/POST with explicit assertions. It does not yet cover arbitrary authentication, async protocols, distributed load or production service isolation. Runtime dependencies remain standard-library-only; no paid service or live model is required for the reuse scenarios. Existing local AI and financial browser checks remain separate assurance layers.
