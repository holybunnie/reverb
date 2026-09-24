# Reverb local handoff

This file is a repository handoff for the finishing work; it contains no
credentials or private market capture.

## Submission-fit note

The supplied specification says the deadline is 21 September, but the current
[official S2 guide](https://bitget-ai.gitbook.io/bitgetai_hackathons2) lists the
submission deadline as 27 September 2026 (UTC+8). That guide also has
inconsistent voting/judging dates in different sections; confirm the deadline
in the submission form or with organizers before planning around it.

The guide's current Agentic Trading description asks for the LLM to be the
primary trading decision-maker, plus an event-to-decision-to-execution demo and
paper-trading log. Reverb's supplied safety specification instead gives the
model language-only duties and reserves decisions for deterministic gates. Keep
that safety boundary unless the user explicitly chooses to revise it, but note
that the current design may need a clear track-fit explanation.

## Current checkpoint

Reverb is shipping the verified Reality-token spot-only fallback. The read-only
UTA Trade key, Agent Hub buying-power read, Reality order transport, and one
small manually approved Reality fill are observed. That fill was not a Reverb
pre-registration or an earnings trade. Stock+ option endpoints are unavailable
to this account, so options are a blocked extension rather than a live leg.

The project has a multi-page consumer surface, a credential-free historical
replay, a live local event flow, and a hash-chained private ledger. The latest
offline verification passed 119 unit tests, compileall, replay-capture check,
measurement-report check, and `git diff --check` (rerun after any later edit).

The local event API was smoke-tested against the public calendar and Bitget:
80 named earnings rows were returned. One current-week event matched a
continuous Reality token, but its announcement time was unresolved. Reverb
recorded a watch-only paper pre-registration with `event_time_unresolved`; it
submitted no order. This demonstrates the unresolved-time refusal, not a valid
scheduled trade. BlackBerry's issuer site lists the FY2027 Q2 results event for
24 September at 8:00 AM EDT, so it is not a suitable 16:05 after-close sample.

## Consumer workflow implemented

- Separate landing, workspace/dashboard, events, report, connection, replay,
  and evidence pages with responsive styling and reduced-motion support.
- The report surface now leads with the frozen Costco brief: thesis status,
  pending market/capture gate, market-quality placeholder, deterministic
  `REFUSE`, and a browser-local human-review control that cannot submit an order.
- Current-week ticker/company search, event selection, local-time conversion,
  and displayed exact/assumed/unresolved timing provenance.
- Direction, user-entered expected move and risk budget; Qwen may classify
  direction but may not produce the move, size, or trade decision.
- Deterministic spot-only proposal/refusal, local pre-registration, persistent
  selection, waiting/countdown, manual reaction check, and morning report.
- The app and scheduler use public market data for paper decisions. Neither
  path submits a pre-close spot order.
- Live writes stay behind liveness, pre-registration, runtime constraints,
  buying-power checks, and the machine-readable gate. The present M0 artifact
  remains BLOCKED.

## Fee and Qwen verification

- Bitget's published rToken fee schedule and `fee-group` group-level data are
  verified. One manually submitted RCAPR fill's fee matches the published
  base rate. That is not proof of this account's personalized rate across
  symbols/sessions.
- The account-specific fee-rate API was attempted through Agent Hub and
  returned an error on this Trade-only key. Bitget documents UTA Management
  read access for that endpoint. Do not ask the user to broaden permissions
  unless exact personalized fees become necessary for an explicitly approved
  live step; public paper/demo work needs no permission change.
- The hackathon Qwen key is configured locally. Live direction classification
  and narration both succeeded with the guide-recommended Qwen 3.8 Max model.
  The narration was hash-recorded beside a verified paper decision in a
  temporary ledger; deterministic fallback is also tested. No secret or model
  prose was written here.
- The new Costco thesis-extraction endpoint is unit-tested. Its live sample
  call did not complete: the sandbox attempt could not connect and the
  network-enabled attempt timed out. Do not describe extraction as live-verified
  until a candidate-only call succeeds. The sanitized unavailable attempt is
  recorded in `evidence/qwen/ledger.jsonl`; no candidate claims were used.
- A pre-event estimate survey found the EPS comparison basis unresolved:
  Kiplinger states $6.53/share without naming adjusted vs. reported EPS, while
  TipRanks calls $6.55 adjusted EPS. Reverb must keep the EPS claim visible but
  unscored unless a source, capture timestamp, value, and matching basis are
  frozen before registration.

## Remaining external evidence / blockers

1. Reality book/fills access: the latest sanitized live check says the loaded
   read credential has `uta_trade=true`, `uta_mgt=true`; the account-scoped
   Reality book and fills routes still return `40025`, which is consistent with
   a separate whitelist. Do not bypass it. EXNIGHT proved the public UTA v3
   SPOT order book for Reality-token depth, so the Costco recorder requires
   candles plus that public book. Protected book/fills and generic public fills
   are optional, separately labelled provenance; their failure alone does not
   make a slot incomplete.
2. Exact account-specific fee rate: requires a successful account fee-rate
   response. For now the published schedule plus the single fill are recorded
   separately and no fee-sensitive earnings order is allowed.
3. Earnings-time liquidity: needs a future earnings event for names with
   verified 24/7 Reality-token trading. Capture the order book near 16:05 ET and
   compare against that name's regular-hours median. Current off-window books
   are not a substitute.
4. Costco forward run: the active corrected registration is frozen in
   `evidence/costco/frozen_thesis_v2.json` with hash
   `bcd4e540fa1e2b46d883f6b63734b418cd533641be03f4eed5fc9877666ea4c6`; the
   original v1 artifact is preserved and explicitly superseded. The
   15:30–20:00 ET capture, issuer timestamp, reconciliation, and market-quality
   finding still need to be recorded. A missing candle or public UTA book slot
   keeps the run `INCOMPLETE`; a protected-route `40025` response does not.
5. Submission surface: rerun GitHub Pages after local changes are finalized,
   inspect the deployed `/demo`, and record video. Do not publish private
   ledger data, `.env`, or this local handoff.

## Commands for safe verification

```sh
./.venv/bin/python -m unittest discover -s tests -v
./.venv/bin/python -m compileall -q reverb scripts
./.venv/bin/python scripts/replay_capture.py check
./.venv/bin/python scripts/probe.py report --check
git diff --check
```

The scheduler's pre-event action now revalidates the event against the configured
earnings calendar and dispatches `prepare_spot_position` using public Bitget
Reality data. It has no order executor. Reaction live writes remain separately
gated and must not be enabled without user approval for an exact order.
