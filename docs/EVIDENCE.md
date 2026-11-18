# Evidence provenance

Documentation review: **2026-11-17**. This date records a documentation/source review, not a rerun of every example.

## Read the labels

- **Current CI** means the workflow outcome for the specific commit shown in Actions. A moving badge is not an immutable release record.
- **Recorded local** means a saved execution under its original environment and date; a screenshot never reruns itself.
- **Historical release** means evidence for an older version. Its count and dependency versions must not be rewritten to resemble current CI.
- **Authored / deterministic** means an intentionally specified scenario or fixture. It is not a newly generated model output.
- **Recorded model experiment** means calls made under the saved protocol; it does not prove live provider availability or general accuracy.

[Current Actions runs](https://github.com/kilicerdal/settlementlab/actions?query=branch%3Amain) · [Reviewer journey](REVIEWER_GUIDE.md) · [Supported setup](MAINTENANCE.md).

## Recorded evidence inventory

| Item | Label and scope | Inspect |
|---|---|---|
| V3.0 screenshot / walkthrough | Recorded local V3.0 release, not current CI; passing controls plus expected collateral replay failure | [Release](https://github.com/kilicerdal/settlementlab/releases/tag/v3.0.0) |
| Portable showcase generated on your machine | Fresh local execution only after `python -m scripts.showcase`; manifest records commit/dirty state, runtime and checksums | [Reproduce and verify](REVIEWER_GUIDE.md) |
| Python controls, browser and package checks | Current per-commit hosted CI; Python 3.9 and 3.13 controls | [Assurance workflow](../.github/workflows/assurance.yml) |

The screenshot itself does not supply an independent capture commit/date; the V3.0 release is the historical publication anchor. Generated manifests provide finer provenance for a fresh run. A failed collateral C02 report is deliberately required (expected 200 / actual 201); unrelated errors must not be presented as defect detection. Checksums establish integrity rather than publisher identity. Local AI observations are separate from deterministic controls.

## Immutable documentation snapshot

[Files as reviewed at `65d218f4379a`](https://github.com/kilicerdal/settlementlab/tree/65d218f4379a91b8d65d9d3483bb70c594ce38c0). This identifies the containing source snapshot, not an inferred capture commit. Historical artifacts are preserved unchanged.
