# Corrections to the supplied build specification

These findings amend the original BELLRING v1 specification for Reverb. A
DOCUMENTED statement describes a source, not a tested account capability.

| Original premise | Evidence and consequence |
| --- | --- |
| Traditional brokers cannot trade at 16:05; Bitget alone can. | DOCUMENTED contradiction: [Bitget itself describes broker after-hours access](https://www.bitget.com/academy/tokenized-stocks-vs-brokers-trading-hours-2026-guide). Lead with unattended earnings response and integrated access, not exclusivity. |
| 16:05 New York is 04:05 Jakarta / 05:05 Manila. | OBSERVABLE via IANA timezone conversion: during New York daylight time it is 03:05 / 04:05 the following day, and 21:05 Lagos. Standard time shifts each by one hour. Compute for each event date. |
| All companies announce at 16:05. | ASSUMED, not a universal rule. Require company-specific calendar evidence and preserve date-only or before/after-market uncertainty. |
| Stock+ documentation is not publicly indexed; IV unknown. | DOCUMENTED: [options quotes](https://www.bitget.com/docs/catalog/stock-plus/options-quotes) now document impliedVolatility. Derivation can be a model check, not a claim that no field exists. Greeks are not established by this finding. |
| A tradeable option implies API prices are accessible. | DOCUMENTED: the same API docs require OPRA card activation and separate API whitelisting. App access does not establish API entitlement. |
| fee-group gives the user's fee tier. | DOCUMENTED: [Bitget's fee API announcement](https://www.bitget.com/support/articles/12560603850208) describes fee-group as market-maker grouping/weights and account/fee-rate as user fees. Never turn a group weight into an execution fee. |
| Zero commission implies no cost; premium alone covers the budget. | DOCUMENTED: [option rules](https://www.bitget.com/support/articles/12560603889520) list platform and third-party charges and automatic exercise. Include charges and avoid unverified exercise funding exposure. Fetch applicable costs before sizing. |
| An option's premium cap protects the whole strategy. | ASSUMED and invalid as a budget model: an additional token position uses additional capital. Reserve a combined worst-case budget; a stop order is not a guaranteed price. |
| European Black-Scholes plus token price is sufficient for every option. | ASSUMED modeling approximation: validate contract exercise style, dividends, quote synchronization and token/underlying basis before using a model-derived IV. Post-event volatility is a scenario input, not an observed fact. |
| Beat / miss alone supplies expected move magnitude. | Missing input: direction is not a numeric thesis. Ask the user for a magnitude or use a clearly stated deterministic data rule; the model must not invent it. |
| Keys never transmitted anywhere. | Clarify: secret and passphrase stay in local handling; authenticated requests necessarily send the API identifier and required authentication material directly to Bitget. Never send credentials to a Reverb-operated host. |

The official docs also disagree internally on option expiry-date formatting:
the list description says YYMMDD while its example and chain request use
YYYYMMDD. Validate actual responses before normalizing dates.
