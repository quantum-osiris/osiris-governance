"""Dynamic Evidence Ledger: Append-only, tamper-evident audit ledger enforcing the Non-Substitution Invariant.

Governing Invariant:
  Evidence Class A -/-> Claim Class B
  Supports(e, c) <=> ClassAllowed(e, c) ^ ScopeMatches(e, c) ^ IntegrityValid(e) ^ AuthoritySufficient(e, c)

Precedence Order:
  FALSE > BLOCKED > UNVERIFIED > TRUE
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from .canonical import canonical_sha256
from .contracts import AuthorityPermit, PermitAuthority, PROMOTION_SCOPE, VERIFICATION_SCOPE
from .errors import (
    AuthorityGateError,
    ExecutionBindingMismatch,
    GovernanceViolation,
    NonceReplayDetected,
    ProposalExpired,
    ScopeViolation,
)
from .models.ledger import (
    ClaimStatus,
    ClaimType,
    EvidencePlane,
    LedgerEvent,
    LedgerEventType,
    ScopeBinding,
    ViolationType,
    resolve_status_precedence,
)

GENESIS_DIGEST = "sha256:0000000000000000000000000000000000000000000000000000000000000000"

# Explicit Plane-to-Claim Mapping Table
# Prevents cross-plane substitution
PERMITTED_PLANES_BY_CLAIM_TYPE: Dict[ClaimType, Set[EvidencePlane]] = {
    ClaimType.REPLAY_MATCH: {EvidencePlane.REPRODUCIBILITY},
    ClaimType.RUNTIME_EGRESS_BLOCKED: {EvidencePlane.RUNTIME_SECURITY},
    ClaimType.SANDBOX_ATTESTED: {EvidencePlane.RUNTIME_SECURITY},
    ClaimType.ANALYSIS_REPRODUCED: {EvidencePlane.SCIENTIFIC_EXPERIMENTAL},
    ClaimType.COMPUTATIONAL_REPRODUCED: {
        EvidencePlane.REPRODUCIBILITY,
        EvidencePlane.SCIENTIFIC_EXPERIMENTAL,
    },
    ClaimType.HARDWARE_EXECUTION_CONFIRMED: {EvidencePlane.HARDWARE_EXECUTION},
    ClaimType.SCIENTIFIC_CLAIM_SUPPORTED: {EvidencePlane.SCIENTIFIC_EXPERIMENTAL},
    ClaimType.RELEASE_AUTHORIZED: {EvidencePlane.GOVERNANCE},
    ClaimType.EVIDENCE_INTEGRITY_VERIFIED: {
        EvidencePlane.SCIENTIFIC_EXPERIMENTAL,
        EvidencePlane.REPRODUCIBILITY,
        EvidencePlane.HARDWARE_EXECUTION,
    },
    ClaimType.PROMOTION_GATE_PASSED: {
        EvidencePlane.SCIENTIFIC_EXPERIMENTAL,
        EvidencePlane.GOVERNANCE,
    },
}


PRIVILEGED_EVENT_TYPES: Set[LedgerEventType] = {
    LedgerEventType.CHAMPION_PROMOTED,
    LedgerEventType.CHAMPION_ROLLED_BACK,
    LedgerEventType.RAW_DATA_VERIFIED,
    LedgerEventType.PROMOTION_EVALUATED,
}


@dataclass(frozen=True)
class ClaimEvaluationResult:
    """The adjudicated result of testing a claim against cited ledger evidence."""
    claim_type: ClaimType
    subject: str
    status: ClaimStatus
    violations: List[ViolationType]
    cited_evidence_ids: List[str]
    evaluation_event_id: str
    details: Dict[str, Any] = field(default_factory=dict)


class DynamicEvidenceLedger:
    """Tamper-evident, hash-chained ledger that tracks all claims and enforces non-substitution."""

    def __init__(self, ledger_id: str = "ledger-001", permit_authority: Optional[PermitAuthority] = None):
        self.ledger_id = ledger_id
        self._permit_authority = permit_authority
        self._used_permit_nonces: Set[str] = set()
        self._events: List[LedgerEvent] = []
        self._events_by_id: Dict[str, LedgerEvent] = {}
        self._latest_digest: str = GENESIS_DIGEST

    @property
    def latest_digest(self) -> str:
        return self._latest_digest

    @property
    def event_count(self) -> int:
        return len(self._events)

    @property
    def events(self) -> List[LedgerEvent]:
        return list(self._events)

    def record_event(
        self,
        event_type: LedgerEventType,
        plane: EvidencePlane,
        actor: Dict[str, str],
        artifact: Dict[str, str],
        scope: ScopeBinding,
        payload: Dict[str, Any],
        authority_permit: Optional[Any] = None,
        evidence_refs: Optional[List[str]] = None,
        event_id: Optional[str] = None,
        recorded_at: Optional[str] = None,
    ) -> LedgerEvent:
        """Appends a new event to the ledger, computing its canonical hash and chaining to predecessor."""
        if recorded_at is None:
            recorded_at = datetime.now(timezone.utc).isoformat()

        # Fail-closed Authority Gating for Privileged Lifecycle Events
        if event_type in PRIVILEGED_EVENT_TYPES:
            if authority_permit is None:
                raise AuthorityGateError(
                    f"UNAUTHORIZED_EVENT_APPEND: Privileged event type '{event_type.value}' requires an authenticated authority permit."
                )
            if self._permit_authority is None:
                raise AuthorityGateError(
                    f"NO_PERMIT_AUTHORITY: this ledger has no permit authority, so it cannot accept '{event_type.value}'."
                )
            if not isinstance(authority_permit, AuthorityPermit):
                raise AuthorityGateError("PERMIT_TYPE_INVALID: authority_permit must be an AuthorityPermit")
            problem = self._permit_authority.check(authority_permit)
            if problem:
                raise AuthorityGateError(f"{problem}: permit rejected for '{event_type.value}'")
            if authority_permit.nonce in self._used_permit_nonces:
                raise NonceReplayDetected(f"Permit nonce '{authority_permit.nonce}' has already been used on this ledger")

            permitted_scopes = {
                LedgerEventType.CHAMPION_PROMOTED: {PROMOTION_SCOPE},
                LedgerEventType.CHAMPION_ROLLED_BACK: {PROMOTION_SCOPE},
                LedgerEventType.PROMOTION_EVALUATED: {PROMOTION_SCOPE},
                LedgerEventType.RAW_DATA_VERIFIED: {VERIFICATION_SCOPE},
            }.get(event_type, set())
            if authority_permit.scope not in permitted_scopes:
                raise ScopeViolation(
                    f"Unauthorized authority permit scope '{authority_permit.scope}' for privileged event '{event_type.value}'"
                )

            expected_digest = artifact.get("digest") or artifact.get("raw_id") or scope.artifact_digest
            if not expected_digest or authority_permit.target_digest != expected_digest:
                raise ExecutionBindingMismatch(
                    f"Authority permit digest mismatch: permit target '{authority_permit.target_digest}' != artifact '{expected_digest}'"
                )
            self._used_permit_nonces.add(authority_permit.nonce)

        if event_id is None:
            seq = len(self._events) + 1
            event_id = f"evt-{seq:06d}"
        elif event_id in self._events_by_id:
            raise GovernanceViolation(f"DUPLICATE_EVENT_ID: Event ID '{event_id}' already exists in ledger")
        if evidence_refs is None:
            evidence_refs = []

        # Create draft event to compute canonical digest
        draft = LedgerEvent(
            event_id=event_id,
            event_type=event_type,
            plane=plane,
            recorded_at=recorded_at,
            actor=actor,
            artifact=artifact,
            scope=scope,
            payload=payload,
            evidence_refs=list(evidence_refs),
            previous_record_digest=self._latest_digest,
            record_digest="",
        )
        digest = draft.compute_digest()

        sealed_event = LedgerEvent(
            event_id=event_id,
            event_type=event_type,
            plane=plane,
            recorded_at=recorded_at,
            actor=actor,
            artifact=artifact,
            scope=scope,
            payload=payload,
            evidence_refs=list(evidence_refs),
            previous_record_digest=self._latest_digest,
            record_digest=digest,
        )

        self._events.append(sealed_event)
        self._events_by_id[event_id] = sealed_event
        self._latest_digest = digest
        return sealed_event

    def get_event(self, event_id: str) -> Optional[LedgerEvent]:
        return self._events_by_id.get(event_id)

    def get_events_by_plane(self, plane: EvidencePlane) -> List[LedgerEvent]:
        return [e for e in self._events if e.plane == plane]

    def get_violations(self) -> List[LedgerEvent]:
        return [e for e in self._events if e.event_type == LedgerEventType.INVARIANT_VIOLATION_RECORDED]

    def verify_chain_integrity(self) -> bool:
        """Verifies that every event in the ledger forms an unbroken cryptographic hash chain."""
        expected_prev = GENESIS_DIGEST
        for event in self._events:
            if event.previous_record_digest != expected_prev:
                return False
            computed = event.compute_digest()
            if event.record_digest != computed:
                return False
            expected_prev = event.record_digest
        return True

    def evaluate_claim(
        self,
        claim_type: ClaimType,
        subject: str,
        scope: ScopeBinding,
        cited_evidence_ids: List[str],
        require_independent_adjudication: bool = False,
    ) -> ClaimEvaluationResult:
        """Adjudicates a claim against cited evidence, strictly enforcing non-substitution and scope rules."""
        violations: List[ViolationType] = []
        statuses: List[ClaimStatus] = []
        permitted_planes = PERMITTED_PLANES_BY_CLAIM_TYPE.get(claim_type, set())

        if not cited_evidence_ids:
            violations.append(ViolationType.MISSING_PREREQUISITE)
            statuses.append(ClaimStatus.UNVERIFIED)

        has_independent_adjudication = False
        valid_supporting_evidence_count = 0

        # Check for contradictory observations in the ledger matching this scope
        for event in self._events:
            if event.scope.artifact_digest == scope.artifact_digest:
                if event.event_type == LedgerEventType.RUNTIME_PROBE_OBSERVED:
                    if event.payload.get("status") == "FAIL" or event.payload.get("confinement_breached"):
                        violations.append(ViolationType.CONTRADICTORY_EVIDENCE)
                        statuses.append(ClaimStatus.FALSE)

        # Evaluate each cited evidence item
        for ev_id in cited_evidence_ids:
            ev = self.get_event(ev_id)
            if ev is None:
                violations.append(ViolationType.MISSING_PREREQUISITE)
                statuses.append(ClaimStatus.BLOCKED)
                continue

            # 0. Transitive Claim Laundering Prohibition
            if ev.event_type in (
                LedgerEventType.CLAIM_EVALUATED,
                LedgerEventType.INVARIANT_VIOLATION_RECORDED,
                LedgerEventType.CLAIM_ASSERTED,
            ):
                violations.append(ViolationType.UNSUPPORTED_INFERENCE)
                statuses.append(ClaimStatus.UNVERIFIED)
                continue

            # 1. Plane Support Check (Evidence Non-Substitution Invariant)
            if ev.plane not in permitted_planes:
                violations.append(ViolationType.CROSS_PLANE_SUBSTITUTION)
                statuses.append(ClaimStatus.UNVERIFIED)
                continue

            # 2. Scope Matching Check (Artifact Identity, Context & Policy Ref)
            if ev.scope.artifact_digest != scope.artifact_digest:
                violations.append(ViolationType.SCOPE_MISMATCH)
                statuses.append(ClaimStatus.UNVERIFIED)
                continue

            if ev.scope.environment_digest != scope.environment_digest:
                violations.append(ViolationType.SCOPE_MISMATCH)
                statuses.append(ClaimStatus.UNVERIFIED)
                continue

            if ev.scope.policy_ref != scope.policy_ref:
                violations.append(ViolationType.SCOPE_MISMATCH)
                statuses.append(ClaimStatus.UNVERIFIED)
                continue

            # 3. Time Interval / Staleness Check
            if ev.recorded_at > scope.time_interval_end or ev.recorded_at < scope.time_interval_start:
                violations.append(ViolationType.STALE_EVIDENCE)
                statuses.append(ClaimStatus.UNVERIFIED)
                continue

            # 4. Check for Independent Adjudication if required
            if ev.event_type == LedgerEventType.INDEPENDENT_ADJUDICATION_RECORDED:
                if ev.payload.get("independent") is True:
                    has_independent_adjudication = True
                else:
                    violations.append(ViolationType.INDEPENDENCE_FAILURE)

            # Evidence item passed all criteria
            valid_supporting_evidence_count += 1
            statuses.append(ClaimStatus.TRUE)

        # Check partial-scope coverage for SANDBOX_ATTESTED
        if claim_type == ClaimType.SANDBOX_ATTESTED and valid_supporting_evidence_count > 0:
            observed_probe_names = set()
            for ev_id in cited_evidence_ids:
                e = self.get_event(ev_id)
                if e and e.event_type == LedgerEventType.RUNTIME_PROBE_OBSERVED:
                    observed_probe_names.add(e.payload.get("probe", ""))
            has_network = any("network" in p or "egress" in p or p == "all" for p in observed_probe_names)
            has_filesystem = any("fs" in p or "file" in p or "openat2" in p or p == "all" for p in observed_probe_names)
            if not (has_network and has_filesystem):
                violations.append(ViolationType.MISSING_PREREQUISITE)
                statuses.append(ClaimStatus.UNVERIFIED)

        # Check required independent adjudication
        if require_independent_adjudication and not has_independent_adjudication:
            violations.append(ViolationType.MISSING_PREREQUISITE)
            violations.append(ViolationType.INDEPENDENCE_FAILURE)
            statuses.append(ClaimStatus.UNVERIFIED)

        # Check if no valid supporting evidence was found
        if valid_supporting_evidence_count == 0 and ClaimStatus.FALSE not in statuses:
            statuses.append(ClaimStatus.UNVERIFIED)

        # Resolve status using adverse-first precedence: FALSE > BLOCKED > UNVERIFIED > TRUE
        resolved_status = resolve_status_precedence(statuses)

        # Record violation events if any invariant was breached
        if violations:
            self.record_event(
                event_type=LedgerEventType.INVARIANT_VIOLATION_RECORDED,
                plane=EvidencePlane.GOVERNANCE,
                actor={"type": "system", "id": "osiris.governance.ledger"},
                artifact={"artifact_digest": scope.artifact_digest},
                scope=scope,
                payload={
                    "claim_type": claim_type.value,
                    "subject": subject,
                    "violations": [v.value for v in violations],
                    "resolved_status": resolved_status.value,
                },
                evidence_refs=cited_evidence_ids,
            )

        # Record the claim evaluation event
        eval_event = self.record_event(
            event_type=LedgerEventType.CLAIM_EVALUATED,
            plane=EvidencePlane.GOVERNANCE,
            actor={"type": "system", "id": "osiris.governance.ledger"},
            artifact={"artifact_digest": scope.artifact_digest},
            scope=scope,
            payload={
                "claim_type": claim_type.value,
                "subject": subject,
                "status": resolved_status.value,
                "violations": [v.value for v in violations],
                "valid_evidence_count": valid_supporting_evidence_count,
            },
            evidence_refs=cited_evidence_ids,
        )

        return ClaimEvaluationResult(
            claim_type=claim_type,
            subject=subject,
            status=resolved_status,
            violations=violations,
            cited_evidence_ids=cited_evidence_ids,
            evaluation_event_id=eval_event.event_id,
            details={
                "valid_supporting_evidence_count": valid_supporting_evidence_count,
                "independent_adjudication": has_independent_adjudication,
            },
        )
