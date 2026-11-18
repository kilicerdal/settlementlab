# Extend the framework to a second service

Goal: test a collateral reservation API using the installed generic runner and a user-owned JSON pack. No settlement application, financial oracle, or framework-core edits are required. The reference service is independent source code under `examples/collateral_service`.

## 1. Install and start an isolated target

From the checkout:

```sh
python3 -m venv /tmp/settlementlab-extension-venv
/tmp/settlementlab-extension-venv/bin/python -m pip install .
/tmp/settlementlab-extension-venv/bin/python -m examples.collateral_service.server \
  --port 8090 --db /tmp/my-collateral-v41.db
```

Use an unused database path for a fresh demonstration; the runner never deletes target data. Keep the server running in that terminal.

## 2. Copy a scenario into your own folder

In another terminal, from the checkout:

```sh
mkdir -p /tmp/my-collateral-pack
cp examples/scenario_packs/inventory/reservation.json /tmp/my-collateral-pack/
cd /tmp
/tmp/settlementlab-extension-venv/bin/settlementlab-assure --suite scenarios \
  --target my-collateral --base-url http://127.0.0.1:8090 \
  --scenario-dir /tmp/my-collateral-pack --report-dir /tmp/collateral-v41-control
```

Open `/tmp/collateral-v41-control/index.html`. The pack starts with an independently specified stock of 100, reserves 10, repeats the same request key and checks that the original reservation identifier is returned with HTTP 200. The final expected available stock is **90**, calculated in the pack rather than read back as its own expected value. `${run_id}` gives each run a unique asset/key namespace.

## 3. Prove that a real defect is detected

Start the deliberately broken service in a third terminal, from the checkout:

```sh
/tmp/settlementlab-extension-venv/bin/python -m examples.collateral_service.server \
  --port 8091 --db /tmp/my-collateral-v41-broken.db --fault-duplicate-replay
```

Repeat the installed runner command with port 8091 and a different report directory. It must exit 1: the replay returns HTTP 201 instead of expected 200. The failure-first report points to that HTTP step with the declared `replay-original-id` control. An unreachable target or malformed pack is not equivalent evidence that this replay defect was caught.

The one-command reviewer workflow runs both services in isolated temporary databases, asserts the exact replay failure, and retains both reports. Existing CI also executes the installed external-pack command from the wheel.

## 4. Adapt your own API

Copy the pack, replace paths/request fields, independently determine expected status and JSON values, and name each business control. Use `save` and `$ref` to relate responses without deriving the economic expectation from the response being checked. Avoid embedding credentials or confidential records. The runner supports declarative GET/POST requests, bounded preflight validation, and type-exact assertions; it does not execute expressions, shell commands or arbitrary Python from packs.

See [the external-pack contract](EXTERNAL_SCENARIOS.md) for supported fields, interpolation, limits, failure codes and diagnostic-redaction boundaries. For other protocols, implement a separate transport/adapter rather than putting domain-specific behavior into the generic HTTP assertion engine.
