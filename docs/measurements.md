# Public-data feasibility measurements

Run: `20260921T101740.309305Z-9ca1210d`.

Ledger head: `f54870514b47bd56b95cc69f9b04730ff438d7a31c0ee0de82f2734d34c113ef`.

OBSERVED: these are capture-time diagnostic snapshots, not earnings-window measurements.
The options intersection, event sample, fills and strategy performance remain unmeasured.

OBSERVED: 2710 spot instruments returned; 2125 online Reality instruments.

OBSERVED: 2125 online Reality candidates came from the live instruments and ticker feeds. The dated weekend source was unavailable from this host, so 24/7 membership remains unverified; this is not the options intersection.

| Symbol | Spread (basis points) | Displayed bid / ask value (quote units) | Book age (ms) | Freshness |
| --- | ---: | ---: | ---: | --- |
| RFOXAUSDT | — | — | — | UNAVAILABLE: Book has an empty side |
| RCORUSDT | — | — | — | UNAVAILABLE: Book has an empty side |
| RRJFUSDT | — | — | — | UNAVAILABLE: Book has an empty side |

Displayed depth covers only the requested levels and is not a guaranteed fill.
A stale timestamp is retained as a failed freshness gate, never promoted to a live quote.

OBSERVED `RFOXAUSDT`: 100 candles returned; 12 nonconsecutive timestamp pairs. This is not a validated earnings baseline.
OBSERVED `RCORUSDT`: 100 candles returned; 14 nonconsecutive timestamp pairs. This is not a validated earnings baseline.
OBSERVED `RRJFUSDT`: 100 candles returned; 16 nonconsecutive timestamp pairs. This is not a validated earnings baseline.

## Access and collection failures

- OBSERVED `weekend-source-parse`: Weekend announcement unavailable
- OBSERVED `option-expiry-access`: option-expiry-access: HTTP_400

The public option expiry request carries no credentials. Its response cannot establish account eligibility.
`fee-group` records fee-group data only; it is not the user's applicable fee rate.

Rebuild: `python3 scripts/probe.py report`. Verify the published table: `python3 scripts/probe.py report --check`.
