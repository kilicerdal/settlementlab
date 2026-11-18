# Failure and recovery assurance

Run `python -m unittest tests.api.test_recovery_faults -v` from an installed source checkout. The checks use disposable loopback services and temporary SQLite stores.

| Fault | Independently checked outcome |
|---|---|
| Connection closes after reservation commits, before any response | Client reports connection failure; database already has one reservation and inventory 90 from 100. Explicit same-key replay returns the original ID with HTTP 200 and no second debit. Changed content conflicts. |
| Response stalls after commit until the client times out | Event synchronization proves the mutation committed. There is one stored reservation before the explicit replay; the framework did not retry automatically. |
| Service process is killed after an acknowledged commit | A new process reopens the same database. Same-key replay preserves ID and inventory 90; releasing twice restores 100 once. |
| Body is shorter than advertised, even if received bytes form valid JSON | Typed incomplete_response failure rather than success. |

A failed/timeout response does not establish transaction rollback. The caller must reconcile the uncertain outcome or replay under a service-defined identity contract. The generic runner never assumes that a timed-out POST is safe to repeat automatically.

The hard restart check kills only its own disposable child process and starts another against the same temporary file. It does not kill an operator's service, claim distributed exactly-once processing or prove correctness at every possible database crash point. Existing financial rollback, journal consistency and competing-spend controls remain separate evidence.

No network fault CLI is exposed on the financial application. Response-loss/stall handlers are test-only subclasses. The existing explicit faulty collateral replay variant remains a controlled negative demonstration.
