# Public-data feasibility measurements

Run: `20260923T115045.662310Z-11d40a83`.

Ledger head: `940cb0acdb5ab07c33b09381e6225fb004ce07259195e3eaa713a86c00ee2b47`.

OBSERVED: these are capture-time diagnostic snapshots, not earnings-window measurements.
The options intersection, event sample, fills and strategy performance remain unmeasured.

OBSERVED: 3172 spot instruments returned; 2587 online Reality instruments.

OBSERVED: 2587 online Reality candidates came from the live instruments and ticker feeds. Bitget's live stock-info metadata verified 90 of them for weekend plus after-hours trading; this still is not the options intersection.

| Symbol | Spread (basis points) | Displayed bid / ask value (quote units) | Book age (ms) | Freshness |
| --- | ---: | ---: | ---: | --- |
| RQQQUSDT | 6.7043 | 88018.1856 / 101529.630986 | 0 | FRESH |
| RSPYUSDT | 6.3372 | 88653.9768 / 96166.0680 | 0 | FRESH |
| RMUUSDT | 2.8542 | 62452.0006434 / 72373.2660171 | 0 | FRESH |

Displayed depth covers only the requested levels and is not a guaranteed fill.
A stale timestamp is retained as a failed freshness gate, never promoted to a live quote.

OBSERVED `RQQQUSDT`: 100 candles returned; 1 nonconsecutive timestamp pairs. This is not a validated earnings baseline.
OBSERVED `RSPYUSDT`: 100 candles returned; 1 nonconsecutive timestamp pairs. This is not a validated earnings baseline.
OBSERVED `RMUUSDT`: 100 candles returned; 0 nonconsecutive timestamp pairs. This is not a validated earnings baseline.

## Fee-group observation

OBSERVED: `fee-group` returned GROUP_A (11 group-level tiers). These are group schedules, not the account's selected fee rate.

## Access and collection failures

- OBSERVED `option-expiry-access`: option-expiry-access: HTTP_400

The public option expiry request carries no credentials. Its response cannot establish account eligibility.
The authenticated account-specific fee-rate endpoint is not called by this public probe; Bitget documents UTA Management read permission for it.

Rebuild: `python3 scripts/probe.py report`. Verify the published table: `python3 scripts/probe.py report --check`.
