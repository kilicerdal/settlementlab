# Compatibility, verification and dependency policy

## Supported setup

Python 3.9+; CI exercises Python 3.9 and 3.13. The application uses the standard library. Ruff, mypy and coverage are pinned development tools. Browser checks additionally require Playwright and Chromium; Docker and PostgreSQL are not required.

From a fresh checkout at the repository root, after installing those prerequisites:

```sh
python3 -m venv .venv && .venv/bin/python -m pip install . -r requirements-quality.txt
```

Python examples use POSIX virtual-environment paths; Windows uses `.venv\Scripts\python.exe`.

## Quick check and complete validation

Quick, bounded check:

```sh
.venv/bin/settlementlab-assure --suite scenarios --root .
```

Complete deterministic checks:

```sh
.venv/bin/ruff check src tests scripts examples
.venv/bin/ruff format --check src tests scripts examples
.venv/bin/mypy
.venv/bin/coverage run -m settlementlab.assurance.runner --suite all --root .
.venv/bin/coverage report
```

[Architecture](../docs/ARCHITECTURE.md) · [Evidence and reproduction](../docs/SHOWCASE.md). This is a local synthetic simulator, with switchable demo identities. Expected negative-control failures are not passing application behavior. Browser and optional local-model checks are separate from the core suite.

Commands resolve pinned requirements/lockfiles where supplied. A runtime major or supported Python floor is a deliberate compatibility decision, not an automatic dependency update. Container major/patch tags can receive upstream updates unless an exact version is stated; this is not a bit-for-bit image reproducibility claim.

## Update decisions

Review recorded: **2026-11-17**. This is a policy review date, not a claim that every optional live integration was rerun that day. Current hosted execution appears in Actions; historical counts retain their dates and source identifiers.

| Update | Decision | Reason |
|---|---|---|
| [mypy 2.4.1, PR #3](https://github.com/kilicerdal/settlementlab/pull/3) | Declined under current compatibility policy | Requires Python >=3.10 and fails the Python 3.9 job. Keep the validated toolchain while the application supports 3.9. |
| [coverage 7.16.2, PR #4](https://github.com/kilicerdal/settlementlab/pull/4) | Declined under current compatibility policy | Requires Python >=3.10 and fails the Python 3.9 job. Raising the supported floor is a separate documented change. |

Dependabot checks application/tool dependencies weekly and GitHub Actions monthly. Updates are reviewed in PRs and are not auto-merged. Monthly, review deferred PRs, runtime support, security advisories and the oldest open genuine defects. Record the tested version and run link before changing a compatibility boundary. Remove an ignore rule when its migration is approved; do not keep it silently forever. Security fixes may require raising a runtime floor rather than bypassing tests.

A green CI badge describes that workflow's current result, not a security, accessibility or production-readiness certification. Framework and license badges identify tools/terms, not test results. Do not publish a static passing test-count badge without a dated run.

### Python metadata boundary check

Official PyPI release metadata also excludes Python 3.9 for mypy 1.20.2 and coverage 7.15.4. Dependabot therefore excludes mypy >=1.20 and coverage >=7.11. The latest releases whose metadata permits Python 3.9 at this review are mypy 1.19.1 and coverage 7.10.7; this is a metadata observation, not a claim those candidates passed this project’s tests. The installed, validated pins remain mypy 1.15.0 and coverage 7.8.2 until a candidate passes the complete matrix.

## Runner decision

The Ubuntu 22.04 assurance runner is retained for this pass with the existing Python 3.9/3.13 matrix. Changing the runner is a separate compatibility change: compare installed-package, Chromium, coverage and independent-service results on the proposed image before switching. A newer runner label by itself is not additional correctness evidence.
