# Bring your own HTTP scenario pack

The installed runner can test a running API without changing framework source. These are explicit GET/POST requests to the target you select; use a synthetic non-production service. The runner does not clear an external service's data and does not automatically retry mutations.

Start the owned example from the checkout:

```sh
python -m examples.collateral_service.server --port 8090 --db /tmp/my-inventory-demo.db
```

In another terminal, using an installed framework:

```sh
settlementlab-assure --suite scenarios \
  --target owned-api --base-url http://127.0.0.1:8090 \
  --scenario-dir examples/scenario_packs/inventory \
  --report-dir artifacts/my-api
```

Open artifacts/my-api/index.html. Copy that JSON pack to your own folder, change its relative paths, inputs and expected values, and run it from outside the checkout. The framework wheel includes the loader and reports; user packs stay user-owned. The example API is source-only.

## Contract

Each top-level .json file contains one object with id, title and steps. Optional target must match the selected target; optional control declares a stable identifier. HTTP steps accept action=http, method=GET/POST, path, data, key, status, save, assert and control. Unknown fields/actions are rejected. Relative paths start with one slash. Expected status defaults to 200. Assertions map dot paths (such as body.available) to exact JSON values; booleans, numbers and nested structures are type-sensitive.

`${run_id}` provides a unique namespace. `${original.id}` inserts a previously saved response value into a string. `{"$ref":"original.id"}` preserves the saved JSON value's type. save introduces an alias for later steps; aliases cannot overwrite run_id or each other. Forward and unknown alias references are rejected before execution. An existing alias with a nonexistent response field fails at runtime with a report; the loader cannot know a future server response's shape.

The entire selected pack is structurally validated before sending any request. Duplicate IDs, duplicate JSON keys, nonfinite JSON values, unknown fields, invalid status/methods and unsupported actions fail. Limits are 100 top-level files, 64 KiB per file and 200 steps per scenario. Symlink pack roots/files are rejected. No Python imports, shell steps or evaluated expressions are supported.

External packs require a non-settlement target and --suite scenarios or all. Settlement's packaged catalog owns financial fixtures; it cannot be redirected to an arbitrary server. An external pack replaces packaged scenarios for that run. Configuration and target-profile precedence are unchanged. Invalid pack/setup and scenario failures return nonzero with JSON/HTML/JUnit evidence; target configuration errors use exit 2.

## Diagnostics and control identity

Reports retain source basenames, target, declared control, request method/path/status/duration, and assertion expected/actual values. Query strings, request headers and request bodies are excluded from request diagnostics. Explicitly asserted values and server error text are not a general secret-redaction system: never use real credentials or confidential records in scenarios.

A declared control is a label supplied by the scenario author, not certification that the control is complete. Link it to an independent expected result and a testable rule. Failures appear first with links to the actual failing step; raw JSON/JUnit remain available offline.
