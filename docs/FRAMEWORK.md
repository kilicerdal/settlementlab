# Framework extension guide — V3.0

## Run and inspect

`settlementlab-assure --suite all --root .` runs the source control suites and packaged acceptance scenarios. Select unit, integration or api for focused checks. `--suite scenarios` works outside the checkout after installation. The browser journey remains `python tests/browser/smoke.py` against a running application; the older browser command remains a wrapper.

Outputs: results.json for machine consumption, junit.xml for CI, and index.html for human review. A failed case or setup produces a failed report and exit status. Expected HTTP rejection can pass only when the scenario declares its exact status. Scenarios stop at the first unexpected outcome. Browser/live-model evidence is separate and is never implied by a passing core report.

## Add an acceptance scenario

Add a JSON file under src/settlementlab/assurance/catalog. It needs id, title and a nonempty steps array. Actions are identity, create, manager, request, approve, fund, settle and snapshot. Data supplies action inputs; assert maps dot paths to exact expected values. For example, matching.findings.0.code can equal PRICE_MISMATCH. expect_status declares an expected HTTP rejection. No shell, Python evaluation or arbitrary executable step is supported.

Each scenario runs in LocalEnvironment with an AI-disabled application, temporary database, real local HTTP server and independent cookie jar. TradeFactory supplies complete synthetic terms and unique request keys. Expected values belong in the scenario and must not be calculated by importing the application's business rules. The catalog includes matching correction and maker/checker settlement recovery examples.

## Add application behavior

Pure decisions belong in core. Orchestration belongs in application/service.py and depends on application-owned repository/store protocols. SQL belongs in infrastructure/repository.py or the journal adapter, and migrations in infrastructure/schema.py. bootstrap.create_application wires concrete adapters; the HTTP layer does not own persistence setup. Compatibility facades are retained for existing consumers and fault-injection tests, not as the preferred new composition API.

Some journal persistence operations remain a coarse repository capability, including shared settlement and funding. This is a local SQLite implementation, not a claim that another database can be substituted without implementing and verifying those transactional semantics.

## Configuration

Settings accepts database, port, model and reports. JSON files reject unknown fields. Environment overrides are SETTLEMENTLAB_DB, SETTLEMENTLAB_PORT, SETTLEMENTLAB_MODEL and SETTLEMENTLAB_REPORTS. CLI overrides apply last. Empty model disables local AI. Network binding remains loopback. Separate SQLite connections require a file-backed database; :memory: is intentionally rejected.

## Verification boundaries

Architecture controls prohibit SQL/cursor operations and infrastructure/adapter imports in core/application. Fixture tests verify temporary database removal, independent sessions and server teardown. Report controls verify failure preservation and HTML escaping. Negative acceptance tests deliberately assert a wrong state and verify that the scenario fails rather than reporting success.

Runtime remains standard-library-only. Production identity, participant isolation, scale, durable workers and market calendars remain separate work. Layer separation does not establish production readiness.

## Reproducible business time

LocalEnvironment defaults to simulated 2026-11-09 for the catalog inputs. Scenarios can supply business_date and closed_dates; reports record the actual configured clock. S03 proves early settlement fails with 409. The browser journey uses environments/showcase.json or an equivalent --business-date override. Calendar tests cover weekend, closure, leap-year, policy pinning and invalid fingerprint behavior.

## Generic targets and portable demonstration

For a non-financial target use the generic `http` action, explicit target profile and response references described in [REUSE.md](REUSE.md). Its fixture does not start the financial application. GET/POST are the supported transport surface; there is no arbitrary auth/protocol plugin system.

`python -m scripts.showcase` executes both applications from a checkout, creates portable evidence and checks the deliberately negative result. `--verify` rechecks artifacts without starting services. See [SHOWCASE.md](SHOWCASE.md) for exact scope and manifest limits. This source tool is not included as an installed framework command.
