# Dependency maintenance

## Automated proposals

[Dependabot configuration](../.github/dependabot.yml): pip project/development requirements weekly; GitHub Actions monthly.

New configurations limit open version-update PRs to three per application ecosystem and two per monthly ecosystem. Security-update handling is separate from these version-update limits. Scheduling a check does not guarantee an update is available or that a hosted update job succeeds; inspect Dependabot logs and PRs on GitHub.

## Review before merging

1. Read upstream release notes, advisories, license changes and breaking changes. Check supported Node/Python versions and changes to install scripts.
2. Keep related manifest/lockfile changes together. Preserve third-party notices. A bot PR is a proposal, not approval to merge or publish a new release.
3. Run the relevant checks below and investigate failures without weakening business assertions. Do not automatically accept generated visual baselines or rewrite historical passing evidence.
4. Merge only after review. If behavior or dependencies changed, record fresh verification before a release. Keep the old release evidence tied to its original commit.

Follow the exact installation, lint, typing, coverage and showcase commands in [CONTRIBUTING.md](../CONTRIBUTING.md). Keep the standard-library runtime dependency policy. Validate the Python 3.9 compatibility floor as well as the current CI Python targets. Browser tool upgrades require the matching Chromium installation and the documented browser flow.

No automatic merge is configured by these files. Never attach API keys, real customer data, local databases or raw sensitive traces to a PR. Dependency checks do not require paid model calls or production cloud access.
