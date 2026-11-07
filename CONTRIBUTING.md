# Contributing and release workflow

## Local changes

Create a focused branch for changes. Include the reason, observed behavior and verification in a pull request. Public claims must match reproducible execution or clearly labeled records.

Use Python 3.9+ from the repository root. Install the package and pinned development tools in a virtual environment. Keep runtime dependencies at zero unless the project scope explicitly changes.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install . -r requirements-quality.txt
.venv/bin/ruff check src tests scripts examples
.venv/bin/ruff format --check src tests scripts examples
.venv/bin/mypy
.venv/bin/coverage run -m settlementlab.assurance.runner --suite all --root .
.venv/bin/coverage report
PYTHONPATH=src .venv/bin/python -m scripts.showcase
PYTHONPATH=src .venv/bin/python -m scripts.showcase --verify
```

When editing source after installation, use PYTHONPATH=src or reinstall before checking behavior. Add behavioral regression tests for new controls or defects, with independently stated expected results. Avoid tests that merely duplicate implementation. Use only fictional financial inputs. Preserve transactional failure behavior and compatibility contracts.

Read [architecture](docs/ARCHITECTURE.md), [extension contracts](docs/FRAMEWORK.md) and [HTTP target reuse](docs/REUSE.md) before extending layers. The collateral reference service must remain independent of settlementlab imports.

## Release checklist

1. Set the same version in pyproject.toml, settlementlab/__init__.py, the health response and console label. Update CHANGELOG and current documentation.
2. Run quality gates, full suite, coverage, browser workflow and the portable showcase. Local AI is optional and reported separately.
3. Commit source, then rebuild the showcase from the clean commit so its manifest pins the released revision without a dirty flag.
4. Push and require all CI jobs to pass on that exact revision. Build the wheel with `python -m pip wheel . --no-deps --wheel-dir dist` and attach portable reports plus measured quality evidence to the GitHub release.
5. Publish only reviewed synthetic evidence on the portfolio. Verify links, desktop/mobile layout and deployment status. The repository is public; keep credentials and real financial data out of all artifacts.

The showcase is a source-checkout tool. Its ZIP is portable evidence; it does not include an application installer. JSON/HTML/JUnit reports are generated from execution, not manually edited to appear passing. Checksums detect accidental changes relative to the manifest and do not replace signed provenance or independent review.
