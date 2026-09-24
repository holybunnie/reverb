# Reverb

**An overnight earnings desk for Bitget Reality tokens.**

Write down what you believe before the earnings report. Reverb checks it against what the company actually said, measures how the market reacted, and leaves you a sourced brief in the morning. **You make the decision.**

Most earnings tools tell you what happened. Reverb tells you whether your view survived—and does not score you on facts that were already public when you wrote it.

[Open the workspace](https://holybunnie.github.io/reverb/app/) · [See the verified replay](https://holybunnie.github.io/reverb/demo/) · [Browse the evidence](https://holybunnie.github.io/reverb/preview/)

## Costco forward run

The Costco Q4 FY2026 event is scheduled for 24 September 2026, after the US close. The thesis is now frozen before the event; the market capture and reconciliation are not yet recorded, and no Costco outcome is claimed here. Frozen at `2026-09-24T05:22:56Z` with thesis hash `8f28dd5f4bb4e4fbf70df5a97dd50d1de39fad1a2ab25498720a708c4d45743f`, code commit `a69489b2b860879707409f0e62c8263bdcc12706`. The run will be reported as incomplete if the required capture has a gap or Costco's actual release time cannot be established from its own publication record. [Costco investor events](https://investor.costco.com/events-and-presentations/default.aspx?lv=true).

The approved example thesis is: “I think Costco beats on EPS and membership fee growth stays strong, but margins disappoint because of freight costs. I'd put $100 at risk at most.” For scoring, the agreed operational tests are EPS above a consensus value frozen with its source and timestamp; membership-fee income higher year over year; and gross margin lower year over year. Freight attribution is a separate claim and counts only if Costco explicitly attributes the margin result to freight. These are explicit proxies for this run, not universal definitions of “strong” or “disappointing.”

The pre-event EPS source check is not yet clean enough to freeze a benchmark: [Kiplinger reports $6.53 per share but does not state whether the figure is adjusted or reported](https://www.kiplinger.com/investing/stocks/17494/next-week-earnings-calendar-stocks), while [TipRanks identifies $6.55 as adjusted EPS](https://www.tipranks.com/news/costco-cost-reports-q4-earnings-on-sept-24-heres-what-analysts-expect). Reverb will not compare unlike measures or choose a convenient number; unless a dated estimate with a matching EPS basis is captured before freeze, the EPS claim remains visible and unscored.

Costco had already published its August sales report on 2 September. The registered thesis does not predict comparable sales, so those previously published sales figures will not be added to or scored against it after the fact. [Costco August sales release](https://investor.costco.com/news/news-details/2026/Costco-Wholesale-Corporation-Reports-August-Sales-Results/default.aspx).

The original registration is preserved at [frozen_thesis.json](evidence/costco/frozen_thesis.json). It incorrectly promoted a whitelist-blocked account route over the public UTA depth route already proven by EXNIGHT, so it is being superseded before the event rather than silently edited. The one-minute read-only diagnostic that exposed the regression remains in [the sanitized diagnostic](evidence/costco/diagnostic_20260924T052600Z.json); it is a gate check, not the event result.

## Historical validation

| Evidence | Result |
| --- | --- |
| NVIDIA Q2 FY2027 replay, 26 August 2026 | 90 contiguous one-minute Reality candles; pre-event baseline `$210.1765`; largest observed decline `−2.97%` at `16:21 ET` |
| Production trigger | `3%`; the `−2.97%` move did not cross it, so Reverb held and did not act |
| Orders in the replay | `0` |
| Replay verification | Rebuilt from the captured issuer pages and Bitget candles; checked ledger at `evidence/replays/20260923T122959.089784Z-448cf031/` |
| Historical corpus inventory | `1` distinct verified event after deduplication; `INSUFFICIENT_FOR_VALIDATION`. Threshold crossings: 1% `1`, 2% `1`, 3% `0`, 4% `0`, 5% `0`; full report at `evidence/historical/corpus.json` |
| Extraction accuracy subset | `NOT MEASURED`; no hand-verified multi-event extraction subset exists yet |
| Qwen live check | Verified on 23 September 2026; sanitized hashes at `evidence/qwen/ledger.jsonl`; no Bitget account or order calls |
| Live Qwen thesis extraction | Attempted with the configured key; first sandbox call could not connect, and the network-enabled call timed out. No candidate extraction was produced; the sanitized unavailable attempt is recorded in `evidence/qwen/ledger.jsonl`. The frozen claim set is explicitly human-approved, not model-authored |
| Costco Reality token | `RCOSTUSDT` appeared in the live Reality instrument list; Bitget `stock-info` returned `tradingPeriod` including after-hours and `weekendTradable: no`, captured at `evidence/runs/20260923T115045.662310Z-11d40a83/` |

The NVIDIA result is one historical replay, not a strategy test or profitability evidence. The separate 22 September `RCAPRUSDT` fill proved the human-approved Agent Hub transport only; it was not a Reverb earnings trade. Its receipt is in `evidence/live/20260922T103212Z/`.

## How it works

Before a report, the user writes a thesis and reviews the claims Reverb extracts. The claims, knowledge snapshot, comparison rules, and capture plan are frozen with a timestamp and hash. After the report, source-grounded facts are reconciled by deterministic code; claims already public at freeze are excluded. Reverb measures the Reality-token reaction and presents a recommendation with its evidence. The user makes the decision, and no order is placed without explicit confirmation.

## Track and user

**AI Trading Desk → Personalized research workstation.** Reverb analyzes; the human decides. If supported, execution is a separate human-confirmed Agent Hub handoff. The target user is a Bitget Reality-token trader who wants to record a view before an earnings report and review it honestly afterwards.

## Evidence and known limits

- **OBSERVED:** a small, manually approved Reality-stock limit order filled through Agent Hub. This is transport proof only, not an earnings strategy result.
- **OBSERVED:** the checked NVIDIA historical event did not reach the production 3% trigger. No order was submitted.
- **OBSERVED:** Bitget's public instrument and `stock-info` endpoints list `RCOSTUSDT` and show after-hours trading eligibility; `weekendTradable` is `no`.
- **OBSERVED:** the dedicated read key authenticates as read-only with both UTA Trade and UTA Management enabled, but the account-scoped Reality book/fills routes return `40025`. The successful EXNIGHT build established Bitget's public UTA v3 SPOT order book as the working Reality-token depth route, so candles plus that public book are required; protected book/fills and generic public fills are optional, separately labelled provenance. [Sanitized access evidence](evidence/reality-access/ledger.jsonl).
- **OBSERVED, public depth snapshot:** the 14:14 UTC read-only probe recorded 0 public bid/ask levels for RCOST and 50/50 levels for RNVDA. An empty successful RCOST response is a measured no-visible-depth state, not an authentication failure. These are off-window diagnostics in [the access ledger](evidence/reality-access/ledger.jsonl), not event-time measurements.
- **NOT YET MEASURED:** the Costco event capture, actual issuer release timestamp, spread and depth at the event, the historical earnings corpus size, and extraction accuracy on a hand-verified subset.
- **UNVERIFIED:** Costco claims and the live morning reconciliation. No event result is pre-asserted. The frozen knowledge snapshot marks all four registered claims `UNKNOWN`; the August comparable-sales context is not one of the registered claims and is not scored.
- **BLOCKED EXTENSION:** Stock+ options. This account's protected Stock+ routes return `100001` (“U.S. stock trading is not enabled for this account”); the option/token intersection and an Agent Hub options write tool are unverified. Options are not part of the current product path.

Reverb does not claim Bitget is the only venue with extended-hours trading, and it makes no profitability claim. See the [feasibility record](docs/m0.md), [readiness matrix](docs/readiness.md), and [specification corrections](docs/corrections.md).

## Run and verify

Requires Python 3.11+.

```sh
git clone https://github.com/holybunnie/reverb.git
cd reverb
python3 -m venv .venv
./.venv/bin/pip install -e .
./.venv/bin/python scripts/preview_server.py
```

Open `/` for the landing page, `/events` for the local event search and thesis desk, `/demo` for the credential-free replay, `/report` for the morning brief, or `/preview` for public feasibility evidence.

```sh
./.venv/bin/python scripts/replay_capture.py check
./.venv/bin/python scripts/probe.py report --check
./.venv/bin/python -m unittest discover -s tests -v
```

The public data probes need no Bitget credentials. Qwen uses the local `QWEN_API_KEY` when configured; the sanitized live check is reproducible with `./.venv/bin/python scripts/qwen_check.py`. Never put credentials in the hosted Pages build.

For authenticated Reality-feed diagnostics and the read-only Costco recorder, set all three optional `BITGET_READ_API_KEY`, `BITGET_READ_SECRET_KEY`, and `BITGET_READ_PASSPHRASE` values in the ignored local `.env`. These workflows prefer that separate key and fall back to `BITGET_*` only when the read-key fields are all unset. The trading key remains separate and unchanged.

## Blocked extension: options

The original options workflow is retained as future work, not as the product's promise. Bitget returned `100001` for this account's protected Stock+ routes; the available options and Reality-token intersection is not verified; and no supported Agent Hub options order operation has been found. Revisit this only after account eligibility, OPRA access, the live contract universe, contract terms, fees, and a supported order path are independently verified. The current research product remains spot-market analysis with a human deciding.
