"""Ledger models for OSIRIS Dynamic Evidence Ledger and Invariant Enforcement."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional

from ..canonical import canonical_sha256, canonicalize_json
from ..errors import MutableReferenceError


class EvidencePlane(str, Enum):
    """The 5 orthogonal evidence planes defining authority boundaries.
    
    Hard Invariant:
    Evidence class A -/-> claim class B without explicit approved mapping.
    """
    RUNTIME_SECURITY = "RUNTIME_SECURITY"
    SCIENTIFIC_EXPERIMENTAL = "SCIENTIFIC_EXPERIMENTAL"
    GOVERNANCE = "GOVERNANCE"
    HARDWARE_EXECUTION = "HARDWARE_EXECUTION"
    REPRODUCIBILITY = "REPRODUCIBILITY"


class ClaimType(str, Enum):
    """Explicitly typed conclusions with strict evidence requirements."""
    REPLAY_MATCH = "REPLAY_MATCH"
    RUNTIME_EGRESS_BLOCKED = "RUNTIME_EGRESS_BLOCKED"
    SANDBOX_ATTESTED = "SANDBOX_ATTESTED"
    ANALYSIS_REPRODUCED = "ANALYSIS_REPRODUCED"
    COMPUTATIONAL_REPRODUCED = "COMPUTATIONAL_REPRODUCED"
    HARDWARE_EXECUTION_CONFIRMED = "HARDWARE_EXECUTION_CONFIRMED"
    SCIENTIFIC_CLAIM_SUPPORTED = "SCIENTIFIC_CLAIM_SUPPORTED"
    RELEASE_AUTHORIZED = "RELEASE_AUTHORIZED"
    EVIDENCE_INTEGRITY_VERIFIED = "EVIDENCE_INTEGRITY_VERIFIED"
    PROMOTION_GATE_PASSED = "PROMOTION_GATE_PASSED"


class LedgerEventType(str, Enum):
    """Append-only audit event types."""
    REQUEST_VALIDATED = "REQUEST_VALIDATED"
    POLICY_DECISION_ISSUED = "POLICY_DECISION_ISSUED"
    REPLAY_PERMIT_ISSUED = "REPLAY_PERMIT_ISSUED"
    FIXTURE_REPLAY_COMPLETED = "FIXTURE_REPLAY_COMPLETED"
    RESULT_SCHEMA_VALIDATED = "RESULT_SCHEMA_VALIDATED"
    EVIDENCE_RECORD_SEALED = "EVIDENCE_RECORD_SEALED"
    CHAIN_LINK_VERIFIED = "CHAIN_LINK_VERIFIED"
    RUNTIME_PROBE_OBSERVED = "RUNTIME_PROBE_OBSERVED"
    INDEPENDENT_ADJUDICATION_RECORDED = "INDEPENDENT_ADJUDICATION_RECORDED"
    RELEASE_AUTHORIZATION_RECORDED = "RELEASE_AUTHORIZATION_RECORDED"
    CLAIM_ASSERTED = "CLAIM_ASSERTED"
    CLAIM_EVALUATED = "CLAIM_EVALUATED"
    INVARIANT_VIOLATION_RECORDED = "INVARIANT_VIOLATION_RECORDED"
    RAW_DATA_VERIFIED = "RAW_DATA_VERIFIED"
    PROMOTION_EVALUATED = "PROMOTION_EVALUATED"
    CHAMPION_PROMOTED = "CHAMPION_PROMOTED"
    CHAMPION_ROLLED_BACK = "CHAMPION_ROLLED_BACK"


class ViolationType(str, Enum):
    """Granular categories of Evidence Non-Substitution Invariant violations."""
    CROSS_PLANE_SUBSTITUTION = "CROSS_PLANE_SUBSTITUTION"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    STALE_EVIDENCE = "STALE_EVIDENCE"
    MISSING_PREREQUISITE = "MISSING_PREREQUISITE"
    INTEGRITY_FAILURE = "INTEGRITY_FAILURE"
    AUTHORITY_FAILURE = "AUTHORITY_FAILURE"
    CONTRADICTORY_EVIDENCE = "CONTRADICTORY_EVIDENCE"
    UNSUPPORTED_INFERENCE = "UNSUPPORTED_INFERENCE"
    INDEPENDENCE_FAILURE = "INDEPENDENCE_FAILURE"
    UNVERIFIED_NUMERICAL_CLAIM = "UNVERIFIED_NUMERICAL_CLAIM"
    AA_CALIBRATION_FAILED = "AA_CALIBRATION_FAILED"
    WINNERS_CURSE_DETECTED = "WINNERS_CURSE_DETECTED"
    PSEUDO_REPLICATION_DETECTED = "PSEUDO_REPLICATION_DETECTED"
    SYMBOLIC_INVARIANCE_VIOLATION = "SYMBOLIC_INVARIANCE_VIOLATION"


class ClaimStatus(str, Enum):
    """Adverse-first status values.
    
    Precedence: FALSE > BLOCKED > UNVERIFIED > TRUE
    """
    FALSE = "FALSE"
    BLOCKED = "BLOCKED"
    UNVERIFIED = "UNVERIFIED"
    TRUE = "TRUE"


def resolve_status_precedence(statuses: List[ClaimStatus]) -> ClaimStatus:
    """Computes the overall status using adverse-evidence precedence:
    FALSE > BLOCKED > UNVERIFIED > TRUE
    """
    if not statuses:
        return ClaimStatus.UNVERIFIED
    if any(s == ClaimStatus.FALSE for s in statuses):
        return ClaimStatus.FALSE
    if any(s == ClaimStatus.BLOCKED for s in statuses):
        return ClaimStatus.BLOCKED
    if any(s == ClaimStatus.UNVERIFIED for s in statuses):
        return ClaimStatus.UNVERIFIED
    return ClaimStatus.TRUE


@dataclass(frozen=True)
class ScopeBinding:
    """The 4 essential bindings that constrain evidence authority."""
    artifact_digest: str  # e.g. sha256:...
    environment_digest: str  # host/runtime/namespace config digest
    time_interval_start: str  # ISO 8601 UTC
    time_interval_end: str  # ISO 8601 UTC
    policy_ref: str
    authority_id: str

    def __post_init__(self) -> None:
        raw_art = self.artifact_digest.strip().lower()
        # Prohibit mutable tokens like latest, main, master, head
        for mutable_token in ("latest", "main", "master", "head", "nightly", "dev"):
            if mutable_token in raw_art:
                raise MutableReferenceError(
                    f"MUTABLE_REFERENCE_FORBIDDEN: Artifact digest contains mutable token '{mutable_token}'"
                )
        if not (raw_art.startswith("sha256:") or raw_art.startswith("sha512:") or len(raw_art) == 64):
            raise MutableReferenceError(
                f"MUTABLE_REFERENCE_FORBIDDEN: Artifact reference '{self.artifact_digest}' must be an immutable cryptographic content digest (e.g. sha256:...)"
            )

    def matches(self, other: ScopeBinding) -> bool:
        """Determines if scope bindings match identically."""
        return (
            self.artifact_digest == other.artifact_digest
            and self.environment_digest == other.environment_digest
            and self.policy_ref == other.policy_ref
        )


@dataclass(frozen=True)
class LedgerEvent:
    """Append-only, cryptographically chained evidence ledger record."""
    event_id: str
    event_type: LedgerEventType
    plane: EvidencePlane
    recorded_at: str
    actor: Dict[str, str]
    artifact: Dict[str, str]
    scope: ScopeBinding
    payload: Dict[str, Any]
    evidence_refs: List[str] = field(default_factory=list)
    previous_record_digest: str = ""
    record_digest: str = ""

    def canonical_bytes(self) -> bytes:
        data = asdict(self)
        data.pop("record_digest", None)
        return canonicalize_json(data)

    def compute_digest(self) -> str:
        return canonical_sha256(self.canonical_bytes())
