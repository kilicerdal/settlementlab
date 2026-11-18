# V4.1 local-demo security review

Scope: the local Python HTTP adapter, durable operations boundaries, backup utility and portable reports. Automated abuse cases are in [test_security_boundaries.py](../tests/api/test_security_boundaries.py), with existing role/session, pack-validation and report-escaping controls retained.

| Boundary | Implemented behavior | Evidence |
| --- | --- | --- |
| Local browser origin | Host must name a loopback hostname/address; cross-origin writes rejected | Non-loopback and deceptive userinfo Hosts rejected without mutations |
| JSON ambiguity and size | Duplicate keys and NaN/Infinity rejected; object-only body, 64 KiB limit | Invalid requests leave finance and job tables unchanged |
| Role spoofing | Principal resolved from server session, not payload/cookie role text | Forged cookie, maker/auditor actions and unknown identities rejected |
| Review requests | Requeue/retry/redelivery accept only their explicit fields | Extra actor/role fields rejected |
| Operational secrets | Lease tokens omitted from HTTP snapshots and acceptance/replay | Running-job replay test checks absence |
| Static access | Fixed asset map, CSP, no-store, nosniff | Traversal/unlisted endpoints return 404; headers asserted |
| Evidence rendering | HTML escapes values; console text uses DOM text nodes | Script-like error test and desktop/mobile browser journeys |
| Backup replacement | Exclusive destination creation, mode 0600, source read-only | Existing path/symlink/source collision rejected; corrupt partial copy removed |
| Financial effects | Checker approval/version checks, atomic transaction, fenced worker | Generated sequences, crash tests, independent economic oracle |

Intentional limits: demo identities are freely switchable; GET data is public to local clients; the standard-library development server is not production authentication or internet hosting. Reports may contain explicitly asserted synthetic values and server error text. They are not a general confidential-data redaction service. Backups contain all database records and must remain private. No production penetration-test, regulatory certification, or real participant integration is claimed.

No external security service, paid infrastructure, website setting, or production deployment was changed.
