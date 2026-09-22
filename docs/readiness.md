# Reverb readiness boundary

This matrix prevents an account-authentication problem from blocking unrelated
work. `PUBLIC/LOCAL` paths must remain usable without Bitget credentials.

| Capability | Dependency | Current state |
| --- | --- | --- |
| Static dashboard and verified replay | Checked repository evidence | COMPLETE |
| Public Reality universe and 24/7/session metadata | Public Bitget v3 | COMPLETE |
| Public books, candles, baseline, first-crossing reaction | Public Bitget v3 | COMPLETE |
| Earnings week and timezone conversion | Public Nasdaq calendar | COMPLETE; assumed/unresolved times labelled |
| Black–Scholes, IV inversion, Greeks, refusal arithmetic | Local deterministic engine | COMPLETE |
| Hash-chained pre-registration and outcome ledger | Local filesystem | COMPLETE |
| UTC scheduler heartbeat, gaps, missed windows, paper/research dispatch | Local process + public data | COMPLETE |
| MCP decision surface and deterministic narration fallback | Local process | COMPLETE |
| Qwen view classification and report narration | Local Qwen key only | IMPLEMENTED; live key verification pending |
| Account liveness and permission introspection | Bitget protected UTA v3 | BLOCKED by v3 key activation |
| Stock+ option chain, quotes, fees, intersection | UTA v3 + Stock+/OPRA entitlement | BLOCKED behind authentication/entitlement |
| Live option and rToken orders | Passed M0 + liveness + Agent Hub | BLOCKED intentionally |
| Agent Hub Stock+ option operation | Installed `bgc` catalog | BLOCKED; 22 September search returned no match |
| Three-name earnings-time book comparison | A future real earnings window | NOT YET MEASURED |

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
machine-verifiable M0 artifact and account liveness.
