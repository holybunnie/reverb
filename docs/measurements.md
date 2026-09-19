# Public-data feasibility measurements

Run: `20260919T094350.291839Z-5d1ec429`.

Ledger head: `f3fc4c8e4f916733d097100703ba67e6889f88e3bd824d804137c819c1b6581e`.

OBSERVED: these are capture-time diagnostic snapshots, not earnings-window measurements.
The options intersection, event sample, fills and strategy performance remain unmeasured.

OBSERVED: 2238 spot instruments returned; 1653 online Reality instruments.

OBSERVED: 1653 online Reality candidates came from the live instruments and ticker feeds. The dated weekend source was unavailable from this host, so 24/7 membership remains unverified; this is not the options intersection.

| Symbol | Spread (basis points) | Displayed bid / ask value (quote units) | Book age (ms) | Freshness |
| --- | ---: | ---: | ---: | --- |
| RSPCXUSDT | 5.2401 | 684.187272 / 1821.659197 | 270 | FRESH |
| RMUUSDT | 0.0994 | 109914.3971552 / 5448.6505447 | 303 | FRESH |
| RQQQUSDT | 1.3865 | 94491.15109 / 7808.751140 | 263 | FRESH |

Displayed depth covers only the requested levels and is not a guaranteed fill.
A stale timestamp is retained as a failed freshness gate, never promoted to a live quote.

OBSERVED `RSPCXUSDT`: 100 candles returned; 68 nonconsecutive timestamp pairs. This is not a validated earnings baseline.
OBSERVED `RMUUSDT`: 100 candles returned; 56 nonconsecutive timestamp pairs. This is not a validated earnings baseline.
OBSERVED `RQQQUSDT`: 100 candles returned; 31 nonconsecutive timestamp pairs. This is not a validated earnings baseline.

## Access and collection failures

- OBSERVED `weekend-source-parse`: Weekend announcement unavailable
- OBSERVED `option-expiry-access`: option-expiry-access: HTTP_400

The public option expiry request carries no credentials. Its response cannot establish account eligibility.
`fee-group` records fee-group data only; it is not the user's applicable fee rate.

Rebuild: `python3 scripts/probe.py report`. Verify the published table: `python3 scripts/probe.py report --check`.
