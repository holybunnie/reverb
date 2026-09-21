# Reverb

**An earnings-driven trading agent that stays awake after the closing bell.**

[Live dashboard](https://holybunnie.github.io/reverb/) ·
[Verified earnings replay](https://holybunnie.github.io/reverb/demo/) ·
[Evidence view](https://holybunnie.github.io/reverb/preview/)

> The market closes. The numbers land. Reverb acts, holds, or refuses—and shows
> its work in the morning.

## What it is

You choose a stock, state what you expect, and set the most you are willing to
lose. Reverb prepares before the US market closes, watches the stock token after
the company reports, and records the outcome while you sleep.

The refusal matters as much as the trade. If the data is stale, the market has
already priced a larger move, or the position exceeds the budget, Reverb stops
and records why.

The hosted dashboard is a credential-free historical replay. It cannot place an
order. Live account access is local-only and remains behind a machine-verifiable
feasibility gate.

## What the demo proves

The public demo replays NVIDIA's 26 August 2026 results from a captured issuer
release and 90 contiguous one-minute `RNVDAUSDT` candles from Bitget.

| Recorded result | Value |
| --- | ---: |
| Pre-event baseline | `$210.1765` |
| First move through the configured trigger | `-2.97%` |
| Paper intent within the `$50` budget | `$20.394` |
| Oversized intent refused | `$203.94` |
| Orders submitted | `0` |

Every figure above regenerates from the hash-chained replay ledger. This is one
historical event, not evidence of profitability.

## How it works

1. Before the close, Reverb evaluates whether a long option can express the
   user's view within the declared loss budget.
2. It refuses when required inputs are missing, stale, unavailable, or too
   expensive.
3. After the release, it measures the stock token against the pre-event baseline
   and creates a session-aware reaction decision.
4. The ledger preserves the pre-registration, arithmetic, action or refusal, and
   eventual outcome for the morning report.

The language model may interpret a plain-language view and narrate the report.
It never supplies a price, volatility, strike, expiry, size, or trade decision.

## Why Bitget

Bitget exposes tokenized stock markets beyond regular US hours and has added US
stock options. Reverb gives the two instruments separate jobs: options provide a
defined premium risk before the event; the stock token carries the after-hours
reaction. The design does not claim Bitget is the only broker with extended
hours.

## Current status

| Area | Status |
| --- | --- |
| Public dashboard and recorded replay | **Live** |
| Replay evidence and hash-chain verification | **Verified** |
| Deterministic valuation, refusal, reaction, and scheduler tests | **Passing** |
| Public Reality-market discovery | **Observed** |
| Account-specific Stock+ options access | **Unverified** |
| Options × continuously traded token intersection | **Unverified** |
| Three-name earnings-time order-book study | **Not measured** |
| Live option execution through Agent Hub | **Blocked** |
| Live orders submitted | **None** |

The local authenticated check previously returned Bitget code `40012` on a
protected UTA/Stock+ route. That response does not identify whether the missing
condition is an API-key scope, account eligibility, regional access, or a
market-data entitlement. Reverb records the uncertainty instead of guessing.

See [Milestone 0](docs/m0.md), the executable
[gate artifact](docs/m0_gate.json), and the
[specification corrections](docs/corrections.md).

## Run locally

Requires Python 3.11+.

```sh
git clone https://github.com/holybunnie/reverb.git
cd reverb
python3 -m venv .venv
./.venv/bin/pip install -e .
./.venv/bin/python scripts/preview_server.py
```

Open:

- `http://127.0.0.1:8000/app` — dashboard
- `http://127.0.0.1:8000/demo` — verified historical replay
- `http://127.0.0.1:8000/preview` — public feasibility evidence
- `http://127.0.0.1:8000/connect` — local connection guide

## Verify the evidence

```sh
./.venv/bin/python scripts/replay_capture.py check
./.venv/bin/python scripts/probe.py report --check
./.venv/bin/python -m unittest discover -s tests -v
```

To create a new public-data capture:

```sh
./.venv/bin/python scripts/probe.py capture
./.venv/bin/python scripts/probe.py report
```

Captures are appended under `evidence/`; existing evidence is never silently
replaced. The probe has no order-placement capability.

## Connect Bitget locally

The hosted site never accepts credentials.

1. In Bitget API Management, select **Unified account**. If the interface exposes
   a read/write choice, live trading requires read and write.
2. Leave **P2P**, **Wallet**, **Withdraw**, and **Transfer** off. Stock+ is not a
   separate checkbox on the API-key screen.
3. Store the API key, secret, and passphrase in the ignored local `.env` using
   [.env.example](.env.example) as the template.
4. Run the read-only check:

```sh
./.venv/bin/python scripts/account_check.py
```

The command never prints the credential values and never submits an order.

## Agent interface

Reverb exposes conclusions rather than raw market data:

```text
earnings_this_week()
position_for(symbol, view, expected_move_pct, max_loss)
whats_priced_in(symbol)
react(symbol)
my_positions()
```

Start the local MCP server with:

```sh
./.venv/bin/python scripts/mcp_server.py
```

Agent Hub's local `bgc` catalog is available for supported execution paths, but
the current catalog exposes no verified Stock+ options order tool. Reverb does
not guess a private payload or silently fall back to another write transport.

## Architecture

```text
Bitget public data ──► deterministic engine ──► hash-chained ledger
                              │                         │
                              ├──► dashboard            ├──► morning report
                              └──► MCP decisions        └──► evidence replay

UTC scheduler ──► freshness + session gates ──► local Agent Hub execution
                                                (disabled until M0 passes)
```

Key modules:

- `reverb/chooser.py` and `reverb/math.py` — deterministic option valuation
- `reverb/gate.py` — refusal rules
- `reverb/reaction.py` — post-release baseline comparison
- `reverb/ledger.py` — append-only hash chain
- `reverb/scheduler.py` — UTC wake and missed-window handling
- `reverb/service.py` — shared decision surface for app and MCP
- `reverb/app.py` — phone-first dashboard

## Known limits

- The public replay is paper-only; it proves the data and decision path, not a
  fill or profitable strategy.
- Account-specific Stock+ eligibility, OPRA API access, executable option books,
  fees, and the live options/token intersection remain unverified.
- Historical candles cannot reconstruct a historical order book. The required
  three-name 16:05 spread and depth study is still outstanding.
- Post-event volatility, dividends, early exercise, and token/underlying basis
  are model assumptions until verified against contract and market data.
- Full live execution remains disabled while `docs/m0_gate.json` is `BLOCKED`.

## First-party references

- [Bitget Agent Hub](https://www.bitget.com/docs/uta/agent-hub)
- [Stock+ API launch and eligibility](https://www.bitget.com/support/articles/12560603890720)
- [Stock+ option quotes and OPRA requirements](https://www.bitget.com/docs/catalog/stock-plus/options-quotes)
- [Bitget option rules](https://www.bitget.com/support/articles/12560603889520)
- [NVIDIA result release](https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Announces-Financial-Results-for-Second-Quarter-Fiscal-2027/default.aspx)
