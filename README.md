# Reverb

**An overnight earnings desk for Bitget Reality tokens.**

Write down what you believe before the earnings report. Reverb checks it against what the company actually said, measures how the market reacted, and leaves you a sourced brief in the morning. **You make the decision.**

Most earnings tools tell you what happened. Reverb tells you whether your view survived—and does not score you on facts that were already public when you wrote it.

### It ran on a live earnings report

On 24 September 2026, Reverb froze a Costco thesis about 14 hours before Q4 results and hashed it. Then it recorded the Reality-token market through the release and scored the thesis against Costco's own SEC filing.

| | |
| --- | --- |
| **Thesis frozen** | `06:30 UTC`, hash `bcd4e540…`, before any result was public |
| **Market captured** | `270/270` one-minute RCOSTUSDT slots, `0` gaps, hash-chained ledger |
| **Claims scored** | Frozen rules: `1/1` confirmed, membership fees `$1,850M` vs `$1,724M` ([8-K Exhibit 99.1](https://www.sec.gov/Archives/edgar/data/909832/000090983226000084/costex9918-k92426.htm)). With one disclosed post-release rule: `2/2`, adding margin, which Costco itself states as `11.02%, -11 bps vs Q4 FY'25` ([Exhibit 99.2](https://www.sec.gov/Archives/edgar/data/909832/000090983226000084/costex9928-k92426.htm)) |
| **Freight** | **Not attributed.** Costco's release and deck never link the margin change to freight, so that part of the thesis did not survive |
| **EPS** | **No fair benchmark.** Reported `$6.75` includes a stated `$0.15` one-off; no consensus on a matching basis was frozen in advance, so Reverb declines to grade it rather than pick a number after the fact |
| **Market reaction** | Peak `+1.17%` at 16:15 ET, under the `3%` trigger |
| **Decision** | **HOLD**, with `0` orders. The human decides |
| **Model, measured** | Live Qwen thesis extraction matched the human claim set on variable and comparison `4/4`. On the release, `4/5` live runs returned valid facts but `0/5` chose the quarter: every run cited 52-week fees. The code caught it, which is why the model never scores |

Everything above regenerates from committed evidence. Where the evidence was missing, the brief says so: the exact release time and event-time depth are marked not measured, and the run is honestly labelled `INCOMPLETE`.

[Read the Costco morning brief](https://holybunnie.github.io/reverb/report/) · [Open the workspace](https://holybunnie.github.io/reverb/app/) · [See the verified replay](https://holybunnie.github.io/reverb/demo/) · [Browse the evidence](https://holybunnie.github.io/reverb/preview/)

### Why this design

The language model reads and explains; it never supplies a number or picks a trade. Every score comes from deterministic code checking verbatim issuer text, so the brief can't invent a result. For a desk that will eventually touch real orders, that boundary is the feature.

## Costco forward run

The Costco Q4 FY2026 event ran on 24 September 2026, after the US close, against a thesis frozen at `2026-09-24T06:30:01Z` with hash `bcd4e540fa1e2b46d883f6b63734b418cd533641be03f4eed5fc9877666ea4c6`, code commit `301ab3225dc0cbe1cd806e76e92f206db88f5a89`.

| Result | Evidence |
| --- | --- |
| Capture | `270` of `270` one-minute slots, `0` gaps; recorder status `COMPLETE` ([summary](evidence/costco/capture_summary.json)) |
| Reaction | Baseline `$896.48` (candle ending 16:00 ET); peak `+1.17%` at `16:15 ET`, low `−0.30%`, last `+0.17%` at `19:58 ET` |
| Decision | The `3%` trigger was not crossed, so Reverb held; orders `0` |
| Thesis | Frozen rules: `1` of `1` scoreable claims confirmed (membership fees `$1,850M` vs `$1,724M`). Disclosed addendum `ISSUER_STATED_CHANGE`, added 28 Sep after the release and reported separately: `2` of `2`, margin `-11 bps` per Exhibit 99.2 ([reconciliation](evidence/costco/post_event/reconciliation.json)) |
| Not graded | EPS: no fair benchmark was frozen (reported `$6.75` includes a stated `$0.15` one-off). Freight: not attributed by Costco in the release or deck |
| Release time | Costco's [8-K Exhibit 99.1](https://www.sec.gov/Archives/edgar/data/909832/000090983226000084/costex9918-k92426.htm) was accepted by EDGAR at `16:17:37 ET`, an upper bound only |
| Depth | All `270` public order-book snapshots returned `0` levels while RCOST traded, so event-time spread and depth are **not measured** |

Under the pre-registered protocol the run is reported **`INCOMPLETE`**: the exact release time could not be established from Costco's own publication record (its investor site blocks automated capture from this host, and the 8-K acceptance time is only an upper bound).

The approved example thesis is: “I think Costco beats on EPS and membership fee growth stays strong, but margins disappoint because of freight costs. I'd put $100 at risk at most.” For scoring, the agreed operational tests are EPS above a consensus value frozen with its source and timestamp; membership-fee income higher year over year; and gross margin lower year over year. Freight attribution is a separate claim and counts only if Costco explicitly attributes the margin result to freight. These are explicit proxies for this run, not universal definitions of “strong” or “disappointing.”

The pre-event EPS source check is not yet clean enough to freeze a benchmark: [Kiplinger reports $6.53 per share but does not state whether the figure is adjusted or reported](https://www.kiplinger.com/investing/stocks/17494/next-week-earnings-calendar-stocks), while [TipRanks identifies $6.55 as adjusted EPS](https://www.tipranks.com/news/costco-cost-reports-q4-earnings-on-sept-24-heres-what-analysts-expect). Reverb will not compare unlike measures or choose a convenient number; unless a dated estimate with a matching EPS basis is captured before freeze, the EPS claim remains visible and unscored.

Costco had already published its August sales report on 2 September. The registered thesis does not predict comparable sales, so those previously published sales figures will not be added to or scored against it after the fact. [Costco August sales release](https://investor.costco.com/news/news-details/2026/Costco-Wholesale-Corporation-Reports-August-Sales-Results/default.aspx).

The active registration is [frozen_thesis_v2.json](evidence/costco/frozen_thesis_v2.json) with its [registration manifest](evidence/costco/registration_manifest_v2.json). The original [v1 artifact](evidence/costco/frozen_thesis.json) is preserved: it named an account-scoped route instead of the public UTA depth route. The capture route was chosen from prior testing of Bitget's public order-book endpoint. A live one-minute v2 proof captured its required candle and public-book requests with no gaps and finished `COMPLETE`; the public RCOST book was empty at that off-window instant. [Sanitized v2 diagnostic](evidence/costco/diagnostic_v2_20260924T063700Z.json). This is a gate check, not the event result.

## Historical validation

| Evidence | Result |
| --- | --- |
| NVIDIA Q2 FY2027 replay, 26 August 2026 | 90 contiguous one-minute Reality candles; pre-event baseline `$210.1765`; largest observed decline `−2.97%` at `16:21 ET` |
| Production trigger | `3%`; the `−2.97%` move did not cross it, so Reverb held and did not act |
| Orders in the replay | `0` |
| Replay verification | Rebuilt from the captured issuer pages and Bitget candles; checked ledger at `evidence/replays/20260923T122959.089784Z-448cf031/` |
| Historical corpus inventory | `1` distinct verified event after deduplication; `INSUFFICIENT_FOR_VALIDATION`. Threshold crossings: 1% `1`, 2% `1`, 3% `0`, 4% `0`, 5% `0`; full report at `evidence/historical/corpus.json` |
| Extraction accuracy | Measured on one event (Costco): thesis `4/4`, release quarter `0/5`. Not yet measured across multiple past events |
| Qwen live check | Verified on 23 September 2026; sanitized hashes at `evidence/qwen/ledger.jsonl`; no Bitget account or order calls |
| Live Qwen thesis extraction | Verified on 28 September 2026 after disabling the reasoning trace for schema-bound calls (it had caused the earlier timeouts). Candidates matched the approved claims on variable and comparison `4/4`; claim type differed (`FORWARD_EXPECTATION` vs approved `QUARTER_FACT`). Sanitized hashes in `evidence/qwen/ledger.jsonl`; the frozen claims remain human-approved |
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
- **OBSERVED:** the dedicated read key authenticates as read-only with both UTA Trade and UTA Management enabled. Reverb's own probe returned a 50-by-50 two-sided RNVDA book from Bitget's public UTA v3 SPOT order book, establishing it as the working Reality-token depth route, so candles plus that public book are required; other feeds are optional, separately labelled provenance. [Sanitized access evidence](evidence/reality-access/ledger.jsonl).
- **OBSERVED, public depth snapshot:** the 14:14 UTC read-only probe recorded 0 public bid/ask levels for RCOST and 50/50 levels for RNVDA. An empty successful RCOST response is a measured no-visible-depth state, not an authentication failure. These are off-window diagnostics in [the access ledger](evidence/reality-access/ledger.jsonl), not event-time measurements.
- **NOT MEASURED:** the exact Costco release timestamp (the 16:17:37 ET 8-K acceptance is an upper bound) and event-time depth on the public book route, which returned no RCOST levels. The recorder now captures the ticker's best bid/ask and has been verified live.
- **NOT YET MEASURED:** the historical earnings corpus size, and extraction accuracy beyond the single Costco event.
- **OBSERVED:** the Costco reconciliation confirms the one claim scoreable under the frozen rules (membership fees). A disclosed post-release addendum also confirms margin from Costco's own Exhibit 99.2 statement; it is reported separately and never overwrites a frozen result. EPS stays unscored and freight is not attributed; the August comparable-sales context is not a registered claim and is not scored.
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

The forward recorder uses the pre-registered UTC window and has no order path:

```sh
./.venv/bin/python scripts/costco_recorder.py \
  --start-at 2026-09-24T19:30:00Z \
  --end-at 2026-09-25T00:00:00Z
```

Start it before 19:30 UTC / 20:30 WAT. It records 270 required minute slots and reports `INCOMPLETE` rather than backfilling a late or missing slot.

After the event, derive the sanitized summary and reconcile against the issuer filing:

```sh
./.venv/bin/python scripts/costco_capture_summary.py data/private/costco-recordings/<run-id>
./.venv/bin/python scripts/costco_reconcile.py
```

## Blocked extension: options

The original options workflow is retained as future work, not as the product's promise. Bitget returned `100001` for this account's protected Stock+ routes; the available options and Reality-token intersection is not verified; and no supported Agent Hub options order operation has been found. Revisit this only after account eligibility, OPRA access, the live contract universe, contract terms, fees, and a supported order path are independently verified. The current research product remains spot-market analysis with a human deciding.
