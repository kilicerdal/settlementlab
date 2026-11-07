# API contract — V2.1

Responses are JSON except static assets. Errors contain an `error` string. Validation errors use 422; stale versions, conflicting keys, and invalid lifecycle transitions use 409. Missing resources use 404. Invalid JSON uses 400. Request bodies are limited to 64 KiB.

| Method | Path | Input |
|---|---|---|
| GET | `/api/health` | Service version and AI configuration flag (not model readiness) |
| GET | `/api/snapshot` | Trades, manager history, matching results, latest 100 audit events |
| GET | `/api/matching-policy` | Versioned rule definitions and perspective convention |
| POST | `/api/trades` | Broker terms; `matching_mode: two-sided`; `Idempotency-Key` header |
| POST | `/api/trades/{id}/manager` | Complete manager terms, `allocations`, current `version`; `Idempotency-Key` header |
| POST | `/api/trades/{id}/allocate` | Legacy allocation-only trades: `version`, `allocations` |
| POST | `/api/trades/{id}/affirm` | `version`, `instruction` beginning SYN- |
| POST | `/api/trades/{id}/fund` | `version`, integer `cash_cents`, integer `securities`; replaces available demo balances |
| POST | `/api/trades/{id}/settle` | `version` |
| POST | `/api/reconcile` | `statement`: array of `trade_id`, integer `quantity`, integer `amount_cents` |
| POST | `/api/trades/{id}/analyze` | Current `version`; optional read-only local AI |

## Independent terms

Two-sided broker and manager submissions require `symbol`, `side`, integer `quantity`, string `price`, `currency`, ISO `trade_date`, and ISO `settlement_date`. Settlement must follow trade date; no exchange calendar validation is implied. Broker currency is USD; the manager may submit USD, EUR, GBP, CAD, CHF, or JPY for matching. Manager allocations contain account and positive integer quantity. See [matching rules](MATCHING.md).

Example manager submission after the broker creation in README:

```sh
curl http://127.0.0.1:8080/api/trades/SL-000001/manager \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: manager-example' \
  -d '{"version":1,"symbol":"NOVA","side":"BUY","currency":"USD","quantity":100,"price":"42.76","trade_date":"2026-11-06","settlement_date":"2026-11-09","allocations":[{"account":"SYN-ALPHA","quantity":100}]}'
```

The response retains broker price 4275, manager price 4276, state EXCEPTION, a PRICE_MISMATCH finding, and manager revision 1. Corrections use a fresh key and current version. Refresh after a 409 before deciding to retry.

## Replay semantics

Broker creation replay returns the current trade for matching normalized content. Manager replay returns the original response snapshot for that key, not the current trade; inspect `/api/snapshot` for current state. Both replays are read-only and append no audit event. New manager keys require the current version. Other lifecycle commands use version guards rather than request keys.

Omitting `matching_mode` preserves the V1 allocation-only contract, which needs symbol, quantity, price and trade date and derives next-weekday settlement. This compatibility mode cannot be used to alter a two-sided trade.

`SettlementClient` supports `create`, `submit_manager(trade, terms, key)`, and lifecycle `command`. It accepts a configurable base URL and timeout, and preserves HTTP errors as `APIError`.

## Local AI

AI is read-only and reports the analyzed trade version. Disabled AI returns 503, stale versions 409, an occupied inference slot 429, and unavailable runtime or invalid output 502. Successful responses identify provider, model, prompt version, analysis and supplied evidence. AI never receives account names or actor identities and cannot execute commands. See [AI boundaries](AI.md).
