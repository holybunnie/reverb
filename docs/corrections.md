# Corrections to the supplied build specification

These findings amend the original Reverb v1 specification. A
DOCUMENTED statement describes a source, not a tested account capability.

| Original premise | Evidence and consequence |
| --- | --- |
| Bitget only supports long calls and long puts. | DOCUMENTED correction: [Bitget announced short calls and short puts on 1 September 2026](https://www.bitget.com/support/articles/12560603893942). Reverb deliberately keeps long-only options; the short-option margin and assignment exposure do not fit a capped-loss earnings budget. |
| Traditional brokers cannot trade at 16:05; Bitget alone can. | DOCUMENTED contradiction: [Bitget itself describes broker after-hours access](https://www.bitget.com/academy/tokenized-stocks-vs-brokers-trading-hours-2026-guide). Lead with unattended earnings response and integrated access, not exclusivity. |
| 16:05 New York is 04:05 Jakarta / 05:05 Manila. | OBSERVABLE via IANA timezone conversion: during New York daylight time it is 03:05 / 04:05 the following day, and 21:05 Lagos. Standard time shifts each by one hour. Compute for each event date. |
| All companies announce at 16:05. | ASSUMED, not a universal rule. Require company-specific calendar evidence and preserve date-only or before/after-market uncertainty. |
| Stock+ documentation is not publicly indexed; IV unknown. | DOCUMENTED: [options quotes](https://www.bitget.com/docs/catalog/stock-plus/options-quotes) now document impliedVolatility. Derivation can be a model check, not a claim that no field exists. Greeks are not established by this finding. |
| A tradeable option implies API prices are accessible. | DOCUMENTED: the same API docs require OPRA card activation and whitelisting for option quotes. That is a product/data entitlement, not a separate Stock+ checkbox in the API-key screen; app access does not establish API data access. |
| fee-group gives the user's effective fee. | OBSERVED: the public `fee-group` response includes group labels and group-level tier tables (the captured `rtoken` label is in `GROUP_A`), but does not identify the account's selected rate. DOCUMENTED: [the account fee-rate endpoint](https://www.bitget.com/api-doc/uta/account/Get-Account-Fee-Rate) returns account-specific maker/taker rates and requires UTA Management read permission. Never treat group membership alone as the user's applied fee. |
| Zero commission implies no cost; premium alone covers the budget. | DOCUMENTED: [option rules](https://www.bitget.com/support/articles/12560603889520) list platform and third-party charges and automatic exercise. Include charges and avoid unverified exercise funding exposure. Fetch applicable costs before sizing. |
| An option's premium cap protects the whole strategy. | ASSUMED and invalid as a budget model: an additional token position uses additional capital. Reserve a combined worst-case budget; a stop order is not a guaranteed price. |
| A market order is safe after the close because the rToken is available. | DOCUMENTED: Bitget describes lower or different liquidity outside regular exchange hours. Reverb must measure the book and use a limit order when the configured session requires one; availability alone does not imply a fill. |
| European Black-Scholes plus token price is sufficient for every option. | ASSUMED modeling approximation: validate contract exercise style, dividends, quote synchronization and token/underlying basis before using a model-derived IV. Post-event volatility is a scenario input, not an observed fact. |
| Beat / miss alone supplies expected move magnitude. | Missing input: direction is not a numeric thesis. Ask the user for a magnitude or use a clearly stated deterministic data rule; the model must not invent it. |
| Keys never transmitted anywhere. | Clarify: secret and passphrase stay in local handling; authenticated requests necessarily send the API identifier and required authentication material directly to Bitget. Never send credentials to a Reverb-operated host. |
| Reverb should submit a private order directly from its Bitget REST client. | Build decision: live writes use the local Agent Hub `bgc` execution surface only. The Bitget client remains a read adapter; the account permission layer underneath Agent Hub is not a second order transport. |
| The account-scoped Reality book must be the required depth source. | OBSERVED correction on 23 September 2026: `BITGET_READ_*` authenticates as read-only with both `uta_trade` and `uta_mgt`; the account-scoped book/fills return `40025`. The earlier EXNIGHT build obtained two-sided Reality depth through the public UTA v3 SPOT order-book endpoint. Reverb now uses that proven route as required event-time depth and treats the account-scoped Reality feeds as optional provenance. |

The official docs also disagree internally on option expiry-date formatting:
the list description says YYMMDD while its example and chain request use
YYYYMMDD. Validate actual responses before normalizing dates.
