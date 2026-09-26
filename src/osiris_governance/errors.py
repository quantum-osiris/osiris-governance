"""Error hierarchy for OSIRIS Governance Replay Core.

All exceptions inherit from GovernanceError and define explicit failure codes.
"""


class GovernanceError(Exception):
    """Base exception for all OSIRIS governance violations."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        self.message = message or code
        super().__init__(self.message)


class GovernanceViolation(GovernanceError):
    """Raised when an authorization invariant or boundary is breached."""
    pass


class CanonicalizationError(GovernanceError):
    """Raised when proposal canonicalization or strict JSON parsing fails."""
    pass


class ReplayError(GovernanceError):
    """Raised when fixture replay cannot be performed."""
    pass
