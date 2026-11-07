# Version-one API

All responses are JSON except static assets. Errors have an `error` string. Validation errors use 422; stale versions, conflicting idempotency keys and invalid state transitions use 409. Missing resources use 404. Invalid JSON uses 400. Maximum request body: 64 KiB.

| Method | Path | Input |
|---|---|---|
| GET | `/api/health` | None |
| GET | `/api/snapshot` | None; trades and latest 100 audit events |
| POST | `/api/trades` | `symbol`, integer `quantity`, string `price`, ISO `trade_date`; `Idempotency-Key` header |
| POST | `/api/trades/{id}/allocate` | `version`, `allocations`: array of `account`, `quantity` |
| POST | `/api/trades/{id}/affirm` | `version`, `instruction` beginning `SYN-` |
| POST | `/api/trades/{id}/fund` | `version`, integer `cash_cents`, integer `securities`; replaces available balances |
| POST | `/api/trades/{id}/settle` | `version` |
| POST | `/api/reconcile` | `statement`: array of `trade_id`, integer `quantity`, integer `amount_cents` |

Every trade command requires its current integer version. Refresh after a 409 before choosing whether to retry. A creation replay returns the original record and does not append a second audit event. Reusing a key with different normalized trade content fails. Other commands use version guards rather than request keys.

`SettlementClient` in `settlementlab.assurance.client` provides a base-URL-configurable client with an explicit timeout and structured HTTP errors. Set `SETTLEMENTLAB_URL` for browser runs and `SETTLEMENTLAB_DB` for the application database.

## Optional AI triage

`POST /api/trades/{id}/analyze` accepts the current integer `version`. It is read-only. Missing server configuration returns 503, stale versions return 409, an occupied AI slot returns 429, and provider/output failures return 502. Successful results include `analysis`, bounded `evidence`, `trade_version`, `provider`, `model`, `prompt_version`, `mode: live-model`, and `advisory_only: true`. See [AI boundaries](AI.md).
