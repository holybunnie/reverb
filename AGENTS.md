# Reverb

Repository owner and sole commit identity: holybunnie. Set author and committer
locally to holybunnie; publish and push using that GitHub account only. Do not
inherit another account's identity or change global Git configuration.

Read docs/m0.md and docs/corrections.md before implementation. The feasibility
gate is unresolved. Deterministic math, parsing, freshness, reaction, and ledger
code may be built, but no live trading path is enabled until the gate has a
verified account response. Do not fabricate an options chain, market quote,
recorded earnings event, fill, or eligibility result to advance the gate.

Use Python 3.11+, httpx, pydantic, numpy, scipy, pandas. Product rules require
first-party sources or live API responses. Keep parameters in config/ and record
their checksum on every run. Missing or stale data must halt the affected path.
All eventual engine outputs must be structured. LLMs may interpret and narrate;
they must not select trades or supply quantitative inputs.

Credentials remain local. Never log secrets, request withdrawal/transfer scopes,
or place orders until a specific risk budget and pre-registration exist. All
future live Reality writes must use `reverb.agent_hub.AgentHubExecutor`; the
Bitget client is read-only and must not regain a raw order method.
