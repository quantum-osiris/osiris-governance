"""Typed error hierarchy for OSIRIS Governance control plane."""

from __future__ import annotations


class GovernanceError(Exception):
    """Base exception for all governance control plane errors."""
    pass


class GovernanceViolation(GovernanceError):
    """Base exception for policy, schema, or authorization violations."""
    pass


class SchemaValidationError(GovernanceViolation):
    """Raised when an action proposal fails structural schema validation."""
    pass


class ExecutionBindingMismatch(GovernanceViolation):
    """Raised when proposal canonical bytes do not match the permit's bound hash."""
    pass


class ActionNotPermitted(GovernanceViolation):
    """Raised when an action kind is not permitted by policy."""
    pass


class CapabilityNotPermitted(GovernanceViolation):
    """Raised when a capability is not granted or allowlisted."""
    pass


class ScopeViolation(GovernanceViolation):
    """Raised when a permit or proposal requests unauthorized scope."""
    pass


class ProposalExpired(GovernanceViolation):
    """Raised when a proposal or permit has expired."""
    pass


class EpochMismatch(GovernanceViolation):
    """Raised when a permit's process epoch does not match the active runtime epoch."""
    pass


class NonceReplayDetected(GovernanceViolation):
    """Raised when a nonce replay attempt is detected within the active process epoch."""
    pass


class FixtureNotFoundError(GovernanceError):
    """Raised when an in-memory replay fixture lookup fails."""
    pass


class SubstitutionViolationError(GovernanceViolation):
    """Raised when evidence from an invalid domain is substituted (e.g., E_FIXTURE for E_DEPLOYED)."""
    pass


class AdjudicationError(GovernanceViolation):
    """Raised when adjudication logic or state transitions are violated."""
    pass


class ConfinementViolationError(GovernanceViolation):
    """Raised when runtime boundary or sandbox confinement criteria are breached."""
    pass


class AuthorityGateError(GovernanceViolation):
    """Raised when execution is attempted without valid release prerequisites or permit."""
    pass


class MutableReferenceError(GovernanceViolation):
    """Raised when a mutable reference (e.g. git branch, tag, latest) is used instead of an immutable content digest."""
    pass


class ClosureValidationError(GovernanceViolation):
    """Raised when a claim closure violates its schema or policy; carries every violation found."""

    def __init__(self, violations):
        self.violations = list(violations)
        super().__init__("; ".join(self.violations) or "closure invalid")


class TelemetryValidationError(GovernanceViolation):
    """Raised when a telemetry record or run violates OSIRIS-TELEMETRY-V1; carries every violation found."""

    def __init__(self, violations):
        self.violations = list(violations)
        super().__init__("; ".join(self.violations) or "telemetry invalid")


class SigningUnavailableError(GovernanceError):
    """Raised when signing or signature verification is requested without the `cryptography` package."""
    pass


class EvidenceIntegrityError(GovernanceViolation):
    """Raised when numbers in a claim cannot be verified or recomputed from raw data."""
    pass


class StatisticalGateError(GovernanceViolation):
    """Raised when a candidate fails the statistical promotion gate or A/A simulation rejects calibration."""
    pass


class SymbolicInvarianceError(GovernanceViolation):
    """Raised when a proposed parameter has zero derivative with respect to target observable (Anti-Seked)."""
    pass


class NoiselessBaselineError(GovernanceViolation):
    """Raised when a claimed physical discovery matches noiseless unitary simulation baselines."""
    pass


class PromotionRollbackError(GovernanceViolation):
    """Raised when a promoted champion exhibits performance regression or drift."""
    pass

