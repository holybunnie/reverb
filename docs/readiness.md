# Reverb readiness boundary

This matrix prevents an account-authentication problem from blocking unrelated
work. `PUBLIC/LOCAL` paths must remain usable without Bitget credentials.

| Capability | Dependency | Current state |
| --- | --- | --- |
| Standalone landing and multi-page consumer surface | Checked repository evidence | COMPLETE |
| Public Reality universe and 24/7/session metadata | Public Bitget v3 | COMPLETE |
| Public books, candles, baseline, first-crossing reaction | Public Bitget v3 | COMPLETE |
| Event-time Reality depth and optional platform fills | Raw account-scoped Reality book for required depth; public UTA v3 SPOT book/fills are labelled diagnostics; platform fills are optional provenance | BLOCKED for a complete Costco run: the account-scoped book returns `40025` even though the read key reports both UTA scopes |
| Earnings week and timezone conversion | Public Nasdaq calendar | COMPLETE; assumed/unresolved times labelled |
| Black–Scholes, IV inversion, Greeks, refusal arithmetic | Local deterministic engine | COMPLETE |
| Hash-chained pre-registration and outcome ledger | Local filesystem | COMPLETE |
| UTC scheduler heartbeat, gaps, missed windows, spot paper pre-registration | Local process + current calendar + public Bitget data | COMPLETE; pre-event dispatch never submits an order |
| MCP decision surface and deterministic narration fallback | Local process | COMPLETE |
| Ticker search, thesis inputs, risk settings, local persistence | Browser + live calendar/public Reality API | IMPLEMENTED; smoke test recorded an unresolved-time refusal; current BB issuer event is pre-market, so no qualifying after-close sample is available yet |
| Qwen view classification and narration | Local Qwen key only | VERIFIED in live provider call; sanitized hashes in `evidence/qwen/ledger.jsonl` |
| Thesis-claim and release-fact extraction | Qwen candidate schema + source-grounding code | IMPLEMENTED and unit-tested; live sample timed out with no candidate; unavailable attempt is sanitized in `evidence/qwen/ledger.jsonl` |
| Deterministic thesis reconciliation and pre-freeze hash | Local deterministic code + cited evidence | IMPLEMENTED core and unit-tested; Costco freeze artifact is still the next explicit pre-event action |
| Costco event setup | Costco issuer calendar + live `stock-info` | `RCOSTUSDT` observed after-hours eligible, `weekendTradable: no`; thesis claims are human-reviewed draft input pending freeze |
| Qwen model narration | Local Qwen key + Qwen 3.8 Max | VERIFIED; attached to paper decision and hash-recorded in temporary ledger; deterministic fallback also verified |
| Deterministic report narration fallback | Local ledger | VERIFIED |
| Account liveness and UTA Trade permission | Bitget protected UTA v3 | VERIFIED |
| Buy-side buying power | Agent Hub `maxOpen` | VERIFIED |
| Stock+ option chain, quotes, and option/token intersection | Stock+/OPRA entitlement | BLOCKED for this account; options are a separate extension |
| Reality-token fee schedule | Bitget first-party notice + public `fee-group` | PUBLISHED SCHEDULE VERIFIED; exact account rate unavailable to Trade-only key (UTA Management read required) |
| Reality-stock order transport | UTA Trade + Agent Hub | VERIFIED with one manually approved fill |
| Autonomous earnings orders | Spot-specific pre-close path + event book + account/runtime checks | BLOCKED; scheduler pre-registers paper intent only; no Reverb earnings order has been sent |
| Agent Hub Stock+ option operation | Installed `bgc` catalog | BLOCKED; 22 September search returned no match |
| Reality-book event-time spread/depth and candle/fill provenance | Raw account-scoped Reality book + future earnings window | BLOCKED until the required raw book is available; public book/fills remain separately labelled diagnostics |

Credential-free verification:

```sh
./.venv/bin/python scripts/replay_capture.py check
./.venv/bin/python scripts/probe.py report --check
./.venv/bin/python -m unittest discover -s tests -v
```

Qwen-only verification, after storing the key in the ignored `.env`:

```sh
./.venv/bin/python scripts/qwen_check.py
```

Neither command path can place an order. `--enable-live` remains guarded by the
machine-verifiable event artifact, account liveness, pre-registration, runtime
instrument constraints, and Agent Hub buying power.
