## What it is

Reverb is being built to trade a stock for you on the night it reports earnings,
while you're asleep.

You pick a stock you own. It tells you when that company reports and what time
that is where you live. You say what you think will happen and how much you're
willing to lose. Then you go to bed.

The intended flow is to buy a position before the US market closes, watch how the
price reacts after the results arrive, and tell you in the morning what happened
and why. The public `/preview` is a live evidence preview; live trading remains
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

## Live preview, trade, and refusal evidence

The credential-free `/preview` route presents a real, hash-checked public-data
capture. It shows live data reachability, book freshness, the blocked gate, and
the access failures. It deliberately does not call this an earnings event, a
real order, or a profitable strategy. A data access failure is not an economic
refusal, and a replay is not a real order.

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
- ASSUMED/UNVERIFIED: Stock+ execution through Agent Hub, account-specific fees,
  and trading-permission introspection.
- NOT MEASURED: earnings-time spreads and depth versus regular-hours medians;
  earnings event replay; fills, slippage, and profitability.
- ASSUMED/UNVERIFIED: API-key inactivity expiry and whether IP binding affects it.
- ASSUMED modeling choices: volatility after earnings, risk-free rate, dividend
  treatment, early-exercise effects, and stock-token basis relative to the option
  underlying. None is currently used to approve a trade.

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
./.venv/bin/python -m unittest discover -s tests -v
```

The feasibility probe uses the Python standard library and needs no API keys.
It saves public responses, timestamps, configuration, and checksums under
`evidence/runs/`. It has no order-placement capability. Each invocation creates
new evidence; archived data is never silently replaced. The report command
verifies the ledger and regenerates the published measurement table offline.

To verify a real account, export the three local variables from `.env.example`
in your own shell and run `./.venv/bin/python scripts/account_check.py`. This
performs a read-only call and never prints the values. The account check does
not request withdrawal or transfer permission. A successful check still does
not enable order placement; a pre-registration and a guarded limit-order path
are required.

Start the public preview locally with `./.venv/bin/python scripts/preview_server.py`
and open `http://127.0.0.1:8000/preview`. The JSON conclusion is at
`http://127.0.0.1:8000/api/preview`; it does not expose raw market data.

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

Full live order execution remains gated by `docs/m0.md`. Playbook is not used
because the planned workflow is driven by individual earnings events rather
than grid or recurring trades.
