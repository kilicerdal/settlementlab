# Release and database compatibility

| Surface | V4.2 behavior | Executable evidence |
| --- | --- | --- |
| Populated V4.1 schema 5 | Additive transactional migration to schema 6 | `python -m scripts.v42_compatibility` |
| Existing balances and journal rows | Preserved exactly during upgrade | Compatibility comparison |
| Existing claimed job | Expired lease reclaimed; one successful receipt | Compatibility recovery |
| Old release opening schema 6 | Refuses newer schema | Old release subprocess |
| Rollback | Restore a verified pre-upgrade backup into a separate path | Old release opens backup |
| Existing generic HTTP scenario packs | Same allowlisted JSON DSL | Clean standalone-wheel second-service check |
| Reference-app imports | Existing `settlementlab.assurance` imports retained | Full regression suite |
| Standalone engine | Separate `settlementlab_assurance` namespace | Isolated environment has no `settlementlab` package |

Before upgrading, stop writers, create an online backup with the shipped backup tool, verify it, and retain the V4.1 artifact and dependency environment. Validate restoration to a separate path. Rehearse on a copy of the database with the intended business clock. Migration failure must roll back both DDL and schema version; existing migration safety tests remain required.

Do not point V4.1 at an upgraded database or manually lower `PRAGMA user_version`. New execution and reconciliation records have no backward representation. If new work was accepted after upgrade, restoring an older backup loses that work: preserve the newer database for investigation and reconcile the recovery point before resuming. The test backup contains only synthetic records and is an artifact, not a committed fixture.

The standalone engine version is `4.2.0`. Both wheels have standard-library-only runtime requirements and distinct namespaces. The standalone build copies a fixed allowlist from canonical generic modules; it imports no reference application. This is build-time separation, not a separately maintained source fork. No package-registry publication is implied by a successful local build.
