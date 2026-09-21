# Reverb

[Open the credential-free demo](https://holybunnie.github.io/reverb/) — once
GitHub Pages is enabled for this repository, it replays a real NVIDIA earnings
window from the issuer's release and Bitget's public Reality candles. No
account or credentials are required.

> The biggest moment in a stock's quarter happens at 4am your time. This is the
> exchange where an unattended agent can be ready for it.

## What it is

Reverb is being built to trade a stock for you on the night it reports earnings,
while you're asleep.

You pick a stock you own. It tells you when that company reports and what time
that is where you live. You say what you think will happen and how much you're
willing to lose. Then you go to bed.

The intended flow is to buy a position before the US market closes, watch how the
price reacts after the results arrive, and tell you in the morning what happened
and why. The public demo is a credential-free historical replay: it shows one
deterministic paper action, one arithmetic-backed refusal, and the morning
report. It is not a live fill or a profitability claim. Live trading remains
behind the feasibility gate.

## The problem

Earnings can arrive after the regular US trading day, when you may be asleep or
away from the market. Access outside regular hours depends on your broker,
location, and the stock. Reverb is intended to watch that moment for you.

DOCUMENTED: many traditional brokers already offer after-hours trading. Reverb
does not claim Bitget is the only place to trade after the close.
[Bitget's comparison](https://www.bitget.com/academy/tokenized-stocks-vs-brokers-trading-hours-2026-guide).

## Why build it on Bitget

DOCUMENTED: Bitget provides tokenized stocks and stock options. Its published
options trading hours end at the regular close; selected stock tokens keep
trading beyond it. Bitget now also supports short options, but Reverb uses only
long calls and long puts because their premium is the defined option-side loss.
The proposed design gives each instrument a separate job.
[Options rules](https://www.bitget.com/support/articles/12560603889520),
[stock trading hours](https://www.bitget.com/support/articles/12560603892041).

## The part that makes it responsible

The intended agent can refuse a trade when its price does not justify the user's
view. Refusals and their arithmetic will be displayed as prominently as entries.
The budget must include fees and both positions; buying an additional stock
token does not inherit the option's risk limit.

The hosted preview will need no account. The real agent will run on your
device with permission to read and trade only. The secret and passphrase stay
local; authentication is sent directly to Bitget. Reverb will never request
withdrawal or transfer permission.

## Demo, trade, and refusal evidence

The credential-free demo replays NVIDIA's 26 August 2026 results. The issuer's
first-party release and timing notice are captured beside 90 contiguous
one-minute `RNVDAUSDT` candles from Bitget. The page shows the baseline, the
first move that crossed the declared trigger, a small paper intent that fits a
declared budget, and a one-unit intent refused because its notional exceeded the
same budget. It deliberately does not call either decision a real order or a
profitable strategy. The `/preview` route remains the live feasibility evidence
surface.

## How it will work

Before the close, the engine will evaluate a long option against the user's view
and budget. It will decline when data is missing, stale, or the cost is too high.
After the company reports, it will evaluate the stock token's price reaction
within a separately budgeted position. Once the options market reopens, it will
manage that leg and append an outcome to the original record.

## Measured evidence

Run `python3 scripts/probe.py capture` to collect public Bitget responses, then
`python3 scripts/probe.py report` to rebuild the measurement report from the
hash-checked evidence ledger. Results belong in [docs/measurements.md](docs/measurements.md).
Current snapshots must never be described as earnings-time measurements.

## What we have not verified

- ASSUMED/UNVERIFIED: account-specific options trading eligibility and OPRA API
  entitlement. App options access is not proof of API data access.
- ASSUMED/UNVERIFIED: runtime options universe and its overlap with continuously
  traded stock tokens; executable option bids and asks; contract metadata.
- ASSUMED/UNVERIFIED: the locally installed Agent Hub catalog for this account,
  account-specific fees, and trading-permission introspection. The write path is
  intentionally fixed to local Agent Hub; Reverb has no raw Bitget order fallback.
- NOT MEASURED: earnings-time spreads and depth versus regular-hours medians;
  live fills, slippage, and profitability. The checked historical replay is
  evidence of the data path, not a performance sample.
- ASSUMED/UNVERIFIED: API-key inactivity expiry and whether IP binding affects it.
- OBSERVED: the configured public Nasdaq calendar returns earnings dates but can
  omit the reporting time; `config/calendar.json` must set
  `default_event_time_et` explicitly before a date-only event can schedule a trade.
- ASSUMED modeling choices: volatility after earnings, risk-free rate, dividend
  treatment, early-exercise effects, and stock-token basis relative to the option
  underlying. The configured post-event volatility is currently unverified, so
  the option gate refuses rather than approving a live trade from that scenario.
- OBSERVED: the local authenticated check reaches Bitget but currently returns
  `40012` for a protected UTA/Stock+ route. That response does not distinguish
  a missing UTA API-key scope from account-level Stock+ eligibility. Bitget's
  Stock+ announcement routes product permissions through the U.S. Stocks
  section; it is not a separate Stock+ checkbox on this API-key screen.
- OBSERVED: Agent Hub `bgc` is installed locally and its catalog is reachable,
  but it exposes no Stock+ options order tool. The option write path therefore
  remains blocked rather than guessing the direct REST payload.

DOCUMENTED: Stock+ options API quotes require separate OPRA access and
whitelisting. [API requirements](https://www.bitget.com/docs/catalog/stock-plus/options-quotes).
See [the feasibility gate](docs/m0.md) and [specification corrections](docs/corrections.md).

## How to run the current build

```sh
cd reverb
uv venv .venv
uv pip install --python .venv/bin/python -e .
python3 scripts/probe.py capture
python3 scripts/probe.py report
./.venv/bin/python scripts/replay_capture.py check
./.venv/bin/python scripts/build_demo.py
./.venv/bin/python -m unittest discover -s tests -v
```

The feasibility probe uses the Python standard library and needs no API keys.
It saves public responses, timestamps, configuration, and checksums under
`evidence/runs/`. It has no order-placement capability. Each invocation creates
new evidence; archived data is never silently replaced. The report command
verifies the ledger and regenerates the published measurement table offline.

The historical demo is regenerated with `./.venv/bin/python
scripts/replay_capture.py capture` (read-only issuer and Bitget requests) and
verified offline with `./.venv/bin/python scripts/replay_capture.py check`.
The capture stores the two first-party issuer pages and the 90 one-minute
Bitget candles under `evidence/replays/`; failed attempts remain incomplete and
cannot be served by `/demo`.

Put the three values in the ignored local `.env` (or export them) and run
`./.venv/bin/python scripts/account_check.py`. It performs a read-only call and
never prints the values. The account check does not request withdrawal or
transfer permission. A successful check still does not enable order placement;
a pre-registration and a guarded limit-order path are required. When that path
is enabled, Reverb invokes the local Agent Hub `bgc` command for the write. It
does not call a raw Bitget order endpoint. The same local account permissions
are still required because Agent Hub signs the request for the account
underneath its execution surface.

Agent Hub is a local prerequisite for live execution. Configure `bgc` on the
machine running Reverb, or set `REVERB_AGENT_HUB_BIN` to its local executable,
then run `./.venv/bin/python scripts/agent_hub_check.py` before enabling writes.
That performs the read-only `bgc discover` preflight. Reverb does not install Agent
Hub globally, send keys to a server, or silently fall back to another order
transport. If `bgc` is missing, the order path halts and records the failure.

Start the local server with `./.venv/bin/python scripts/preview_server.py` and
open `http://127.0.0.1:8000/app` for the phone-first product surface,
`http://127.0.0.1:8000/demo` for the historical replay, or
`http://127.0.0.1:8000/preview` for the evidence view. The JSON conclusion is at
`http://127.0.0.1:8000/api/preview`; `/connect` contains the local-only account
permission steps. The server does not expose raw market data or accept keys.

The included `Dockerfile` runs the same credential-free surface on port 8000.
GitHub Pages deployment is defined in `.github/workflows/pages.yml`; it builds
the static demo from the checked replay evidence and publishes the public URL
above. Enable it once at the repository's Settings → Pages → Build and
deployment → Source → GitHub Actions, then rerun the workflow. Until that
setting is enabled, GitHub returns 404 even though the build artifact passes.
No credential is needed for the demo artifact.

Python dependencies for the engine are declared in `pyproject.toml`.
The MCP decision surface is available after installation:

```sh
export BITGET_API_KEY='local value'
export BITGET_SECRET_KEY='local value'
export BITGET_PASSPHRASE='local value'
export REVERB_OPTION_FEES_PER_CONTRACT='verified value'
./.venv/bin/python scripts/mcp_server.py
```

It exposes `earnings_this_week`, `position_for`, `whats_priced_in`, `react`,
and `my_positions`. It does not expose raw option chains, candles, or order
books. The optional Qwen language layer uses `BITGET_QWEN_API_KEY` only for
plain-language interpretation and narration; it never supplies quantitative
inputs or a trading decision. Keep all values in the local shell or ignored
`.env`, not in global Mac settings.

The UTC scheduler can be exercised for one wake with:

```sh
./.venv/bin/python scripts/scheduler_once.py EVENT_ID EVENT_TIMESTAMP
```

It checks key liveness, writes a heartbeat, records a gap or missed-window
marker, and emits the due action. It never submits an order by itself.

For a guarded reaction evaluation, use `scripts/react_once.py SYMBOL EVENT_AT`.
It replays historical windows from historical candles, requires an explicit
reaction quantity and budget, validates live instrument precision/minimums, and
will not call Agent Hub unless `--enable-live` is supplied and the
hash-verified `docs/m0_gate.json` artifact is `PASSED`. The current repository
intentionally halts before that point.

The UTC scheduler accepts `--dispatch` and invokes the position/reaction
decision path at the due wake; a missing dispatcher or missing thesis inputs is
recorded as a non-success `dispatch_blocked` ledger entry. Stock+ option order
submission remains blocked until its endpoint schema and this account's
entitlement are verified. Full live execution remains gated by
`docs/m0_gate.json`. Playbook is not used because the planned workflow is
driven by individual earnings events rather than grid or recurring trades.
