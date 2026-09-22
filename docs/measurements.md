# Public-data feasibility measurements

Run: `20260922T011228.304604Z-9dc0b95d`.

Ledger head: `26f1b2955c6f24b477415ac7c292b4182fd45fc23556c751f1461dc0f0fa8677`.

OBSERVED: these are capture-time diagnostic snapshots, not earnings-window measurements.
The options intersection, event sample, fills and strategy performance remain unmeasured.

OBSERVED: 2710 spot instruments returned; 2125 online Reality instruments.

OBSERVED: 2125 online Reality candidates came from the live instruments and ticker feeds. The dated weekend source was unavailable from this host, so 24/7 membership remains unverified; this is not the options intersection.

| Symbol | Spread (basis points) | Displayed bid / ask value (quote units) | Book age (ms) | Freshness |
| --- | ---: | ---: | ---: | --- |
| RSPYUSDT | 2.5843 | 64266.854532 / 88704.161809 | 0 | FRESH |
| RNVDAUSDT | 8.7873 | 155303.1204 / 159841.284534 | 0 | FRESH |
| RMETAUSDT | 4.1911 | 46667.0028 / 48042.7980 | 0 | FRESH |

Displayed depth covers only the requested levels and is not a guaranteed fill.
A stale timestamp is retained as a failed freshness gate, never promoted to a live quote.

OBSERVED `RSPYUSDT`: 100 candles returned; 1 nonconsecutive timestamp pairs. This is not a validated earnings baseline.
OBSERVED `RNVDAUSDT`: 100 candles returned; 0 nonconsecutive timestamp pairs. This is not a validated earnings baseline.
OBSERVED `RMETAUSDT`: 100 candles returned; 0 nonconsecutive timestamp pairs. This is not a validated earnings baseline.

## Access and collection failures

- OBSERVED `weekend-source-parse`: Weekend announcement unavailable
- OBSERVED `option-expiry-access`: option-expiry-access: HTTP_400

The public option expiry request carries no credentials. Its response cannot establish account eligibility.
`fee-group` records fee-group data only; it is not the user's applicable fee rate.

Rebuild: `python3 scripts/probe.py report`. Verify the published table: `python3 scripts/probe.py report --check`.
