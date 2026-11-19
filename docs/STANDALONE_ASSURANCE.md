# Reuse the assurance framework independently

Build the generic wheel from canonical domain-free modules:

```sh
python -m pip install 'setuptools>=68' wheel
python -m scripts.build_assurance
python -m scripts.verify_assurance_package
```

The resulting `settlementlab_assurance-4.2.0-py3-none-any.whl` contains only catalog validation, HTTP transport, declarative steps, target profiles, portable reporting and the external runner. There are no runtime dependencies or imports of the financial application. A separate namespace allows both wheels to coexist. Build-time copying avoids committing divergent copies of the generic engine.

Install just this wheel in your own service's virtual environment, then run:

```sh
settlementlab-http-assure --target owned-api --base-url http://127.0.0.1:8091 \
  --scenario-dir examples/scenario_packs/inventory --report-dir artifacts/my-service
```

Start the independent synthetic reservation service separately using its tutorial. Add a JSON file to your pack to extend assurance; no settlement classes or plugins are needed. See `examples/scenario_packs/inventory` and `examples/collateral_service`. Each scenario supports bounded HTTP steps, exact JSON assertions, response aliases and `${run_id}` keys. The allowlist executes no arbitrary Python from a pack.

Evidence is JSON, JUnit and offline escaped HTML. The clean-install check executes the existing pack against healthy and intentionally faulty service instances, verifies the expected 200-versus-201 replay defect, and confirms the reference application is absent. This verifies an actual packaged reuse path rather than only source imports.

Target URLs, timing limits and scenario validation remain authoritative. Do not put credentials or personal data in committed packs or expected assertion values. This runner is an assurance client; it does not deploy the target service or provide production authentication.
