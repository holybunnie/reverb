# Public-data feasibility measurements

Run: `20260922T014245.703699Z-92c20c78`.

Ledger head: `29447128ee1be476fca0c3b97847536b779d681bea72192145ccf4221e2bc8e6`.

OBSERVED: these are capture-time diagnostic snapshots, not earnings-window measurements.
The options intersection, event sample, fills and strategy performance remain unmeasured.

OBSERVED: 2710 spot instruments returned; 2125 online Reality instruments.

OBSERVED: 2125 online Reality candidates came from the live instruments and ticker feeds. Bitget's live stock-info metadata verified 90 of them for weekend plus after-hours trading; this still is not the options intersection.

| Symbol | Spread (basis points) | Displayed bid / ask value (quote units) | Book age (ms) | Freshness |
| --- | ---: | ---: | ---: | --- |
| RSPYUSDT | 4.1338 | 88878.649572 / 86788.1904 | 0 | FRESH |
| RNVDAUSDT | 1.7564 | 64702.223496 / 57337.024977 | 0 | FRESH |
| RMETAUSDT | 3.7846 | 45849.85664 / 32851.036129 | 0 | FRESH |

Displayed depth covers only the requested levels and is not a guaranteed fill.
A stale timestamp is retained as a failed freshness gate, never promoted to a live quote.

OBSERVED `RSPYUSDT`: 100 candles returned; 3 nonconsecutive timestamp pairs. This is not a validated earnings baseline.
OBSERVED `RNVDAUSDT`: 100 candles returned; 0 nonconsecutive timestamp pairs. This is not a validated earnings baseline.
OBSERVED `RMETAUSDT`: 100 candles returned; 0 nonconsecutive timestamp pairs. This is not a validated earnings baseline.

## Access and collection failures

- OBSERVED `option-expiry-access`: option-expiry-access: HTTP_400

The public option expiry request carries no credentials. Its response cannot establish account eligibility.
`fee-group` records fee-group data only; it is not the user's applicable fee rate.

Rebuild: `python3 scripts/probe.py report`. Verify the published table: `python3 scripts/probe.py report --check`.
