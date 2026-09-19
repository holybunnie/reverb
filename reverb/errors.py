class ReverbError(Exception):
    """Base error for a halted Reverb path."""


class DataUnavailable(ReverbError):
    """A required live input could not be obtained or validated."""


class FreshnessError(DataUnavailable):
    """A quote or event input is outside its allowed age."""


class ConfigurationError(ReverbError):
    """A required configuration value is absent or invalid."""


class LedgerError(ReverbError):
    """The append-only evidence ledger cannot be trusted."""


class ValuationError(ReverbError):
    """A price or volatility cannot be valued without an invalid assumption."""


class BitgetAPIError(DataUnavailable):
    def __init__(self, status: int | None, code: str | None, message: str):
        self.status = status
        self.code = code
        super().__init__(f"Bitget API failure status={status} code={code}: {message}")


class AgentHubError(DataUnavailable):
    """The local Agent Hub execution surface could not complete a command."""
