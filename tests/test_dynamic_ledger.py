"""Tests for Dynamic Evidence Ledger and Evidence Non-Substitution Invariant enforcement."""

import pytest

import dataclasses
from datetime import datetime, timezone

from osiris_governance.contracts import AuthorityPermit, PermitAuthority, PROMOTION_SCOPE, VERIFICATION_SCOPE
from osiris_governance.errors import (
    AuthorityGateError,
    ExecutionBindingMismatch,
    GovernanceViolation,
    MutableReferenceError,
    NonceReplayDetected,
    ScopeViolation,
)
from osiris_governance.ledger import DynamicEvidenceLedger
from osiris_governance.models.ledger import (
    ClaimStatus,
    ClaimType,
    EvidencePlane,
    LedgerEventType,
    ScopeBinding,
    ViolationType,
    resolve_status_precedence,
)


@pytest.fixture
def base_scope():
    return ScopeBinding(
        artifact_digest="sha256:111122223333444455556666777788889999aaaabbbbccccddddeeeeffff0000",
        environment_digest="sha256:host-linux-kernel-6.8-ns-isolated",
        time_interval_start="2026-09-26T12:00:00Z",
        time_interval_end="2026-09-26T12:05:00Z",
        policy_ref="sandbox-attestation-policy@1.0",
        authority_id="sec-ops-01",
    )


def test_ledger_append_and_hash_chain_integrity(base_scope):
    ledger = DynamicEvidenceLedger(ledger_id="test-ledger-01")

    ev1 = ledger.record_event(
        event_type=LedgerEventType.REQUEST_VALIDATED,
        plane=EvidencePlane.GOVERNANCE,
        actor={"type": "service", "id": "osiris-control-plane"},
        artifact={"digest": base_scope.artifact_digest},
        scope=base_scope,
        payload={"request_id": "req-001", "valid": True},
    )

    ev2 = ledger.record_event(
        event_type=LedgerEventType.RUNTIME_PROBE_OBSERVED,
        plane=EvidencePlane.RUNTIME_SECURITY,
        actor={"type": "probe", "id": "network-monitor"},
        artifact={"digest": base_scope.artifact_digest},
        scope=base_scope,
        payload={"probe": "network_egress", "status": "PASS", "frames": 0},
        evidence_refs=[ev1.event_id],
    )

    assert ledger.event_count == 2
    assert ledger.verify_chain_integrity() is True
    assert ev2.previous_record_digest == ev1.record_digest


def test_cross_plane_substitution_detected(base_scope):
    """Invariant: Replay evidence (REPRODUCIBILITY) cannot support HARDWARE_EXECUTION_CONFIRMED."""
    ledger = DynamicEvidenceLedger()

    # Analyst records a local replay event
    replay_ev = ledger.record_event(
        event_type=LedgerEventType.FIXTURE_REPLAY_COMPLETED,
        plane=EvidencePlane.REPRODUCIBILITY,
        actor={"type": "service", "id": "local-fixture-runner"},
        artifact={"digest": base_scope.artifact_digest},
        scope=base_scope,
        payload={"fixture_id": "quantum-echo-v1", "deterministic": True},
        recorded_at="2026-09-26T12:01:00Z",
    )

    # Analyst attempts to cite this replay to prove HARDWARE_EXECUTION_CONFIRMED
    result = ledger.evaluate_claim(
        claim_type=ClaimType.HARDWARE_EXECUTION_CONFIRMED,
        subject="quantum-execution:job-42",
        scope=base_scope,
        cited_evidence_ids=[replay_ev.event_id],
    )

    assert result.status == ClaimStatus.UNVERIFIED
    assert ViolationType.CROSS_PLANE_SUBSTITUTION in result.violations

    # Ledger appended an invariant violation event
    violations = ledger.get_violations()
    assert len(violations) == 1
    assert violations[0].payload["claim_type"] == "HARDWARE_EXECUTION_CONFIRMED"


def test_scope_mismatch_artifact_expansion(base_scope):
    """Invariant: Evidence for artifact A cannot validate artifact B."""
    ledger = DynamicEvidenceLedger()

    # Evidence collected for container A
    probe_ev = ledger.record_event(
        event_type=LedgerEventType.RUNTIME_PROBE_OBSERVED,
        plane=EvidencePlane.RUNTIME_SECURITY,
        actor={"type": "probe", "id": "fs-sandbox-monitor"},
        artifact={"digest": base_scope.artifact_digest},
        scope=base_scope,
        payload={"probe": "openat2_beneath", "status": "PASS"},
        recorded_at="2026-09-26T12:02:00Z",
    )

    # Claim asserted for container B (different artifact digest)
    scope_b = ScopeBinding(
        artifact_digest="sha256:different_artifact_digest_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        environment_digest=base_scope.environment_digest,
        time_interval_start=base_scope.time_interval_start,
        time_interval_end=base_scope.time_interval_end,
        policy_ref=base_scope.policy_ref,
        authority_id=base_scope.authority_id,
    )

    result = ledger.evaluate_claim(
        claim_type=ClaimType.SANDBOX_ATTESTED,
        subject="container:prod-candidate-b",
        scope=scope_b,
        cited_evidence_ids=[probe_ev.event_id],
    )

    assert result.status == ClaimStatus.UNVERIFIED
    assert ViolationType.SCOPE_MISMATCH in result.violations


def test_stale_evidence_detection(base_scope):
    """Invariant: Evidence collected outside the declared execution interval cannot support the claim."""
    ledger = DynamicEvidenceLedger()

    # Evidence recorded earlier (outside the interval)
    stale_ev = ledger.record_event(
        event_type=LedgerEventType.RUNTIME_PROBE_OBSERVED,
        plane=EvidencePlane.RUNTIME_SECURITY,
        actor={"type": "probe", "id": "egress-monitor"},
        artifact={"digest": base_scope.artifact_digest},
        scope=base_scope,
        payload={"probe": "egress", "status": "PASS"},
        recorded_at="2026-09-26T11:00:00Z",  # 1 hour prior to interval_start
    )

    result = ledger.evaluate_claim(
        claim_type=ClaimType.RUNTIME_EGRESS_BLOCKED,
        subject="workload:run-123",
        scope=base_scope,
        cited_evidence_ids=[stale_ev.event_id],
    )

    assert result.status == ClaimStatus.UNVERIFIED
    assert ViolationType.STALE_EVIDENCE in result.violations


def test_contradictory_evidence_forces_false_precedence(base_scope):
    """Invariant: Adverse observation forces status to FALSE, dominating any positive evidence."""
    ledger = DynamicEvidenceLedger()

    # 1. A successful file probe
    ev_pass = ledger.record_event(
        event_type=LedgerEventType.RUNTIME_PROBE_OBSERVED,
        plane=EvidencePlane.RUNTIME_SECURITY,
        actor={"type": "probe", "id": "fs-probe"},
        artifact={"digest": base_scope.artifact_digest},
        scope=base_scope,
        payload={"probe": "filesystem", "status": "PASS"},
        recorded_at="2026-09-26T12:01:00Z",
    )

    # 2. A failing network egress probe on the same artifact
    ledger.record_event(
        event_type=LedgerEventType.RUNTIME_PROBE_OBSERVED,
        plane=EvidencePlane.RUNTIME_SECURITY,
        actor={"type": "probe", "id": "network-probe"},
        artifact={"digest": base_scope.artifact_digest},
        scope=base_scope,
        payload={"probe": "network_egress", "status": "FAIL", "confinement_breached": True},
        recorded_at="2026-09-26T12:02:00Z",
    )

    # 3. Independent adjudication record
    ev_adj = ledger.record_event(
        event_type=LedgerEventType.INDEPENDENT_ADJUDICATION_RECORDED,
        plane=EvidencePlane.RUNTIME_SECURITY,
        actor={"type": "auditor", "id": "external-firm"},
        artifact={"digest": base_scope.artifact_digest},
        scope=base_scope,
        payload={"independent": True, "verdict": "FAIL"},
        recorded_at="2026-09-26T12:03:00Z",
    )

    # Claim asserted citing passing probe + adjudication
    result = ledger.evaluate_claim(
        claim_type=ClaimType.SANDBOX_ATTESTED,
        subject="execution:run-431",
        scope=base_scope,
        cited_evidence_ids=[ev_pass.event_id, ev_adj.event_id],
        require_independent_adjudication=True,
    )

    # Due to adverse-first precedence (FALSE > BLOCKED > UNVERIFIED > TRUE)
    assert result.status == ClaimStatus.FALSE
    assert ViolationType.CONTRADICTORY_EVIDENCE in result.violations


def test_independence_requirement_enforcement(base_scope):
    """Invariant: SANDBOX_ATTESTED requires independent review; self-attestation is rejected."""
    ledger = DynamicEvidenceLedger()

    probe_ev = ledger.record_event(
        event_type=LedgerEventType.RUNTIME_PROBE_OBSERVED,
        plane=EvidencePlane.RUNTIME_SECURITY,
        actor={"type": "probe", "id": "confinement-probe"},
        artifact={"digest": base_scope.artifact_digest},
        scope=base_scope,
        payload={"probe": "all", "status": "PASS"},
        recorded_at="2026-09-26T12:02:00Z",
    )

    # Asserting claim with require_independent_adjudication=True but missing independent record
    result = ledger.evaluate_claim(
        claim_type=ClaimType.SANDBOX_ATTESTED,
        subject="execution:run-431",
        scope=base_scope,
        cited_evidence_ids=[probe_ev.event_id],
        require_independent_adjudication=True,
    )

    assert result.status == ClaimStatus.UNVERIFIED
    assert ViolationType.INDEPENDENCE_FAILURE in result.violations
    assert ViolationType.MISSING_PREREQUISITE in result.violations


def test_valid_supporting_claim(base_scope):
    """When all bindings, planes, and independent reviews match, claim evaluates to TRUE."""
    ledger = DynamicEvidenceLedger()

    probe_ev = ledger.record_event(
        event_type=LedgerEventType.RUNTIME_PROBE_OBSERVED,
        plane=EvidencePlane.RUNTIME_SECURITY,
        actor={"type": "probe", "id": "confinement-probe"},
        artifact={"digest": base_scope.artifact_digest},
        scope=base_scope,
        payload={"probe": "all", "status": "PASS"},
        recorded_at="2026-09-26T12:02:00Z",
    )

    adj_ev = ledger.record_event(
        event_type=LedgerEventType.INDEPENDENT_ADJUDICATION_RECORDED,
        plane=EvidencePlane.RUNTIME_SECURITY,
        actor={"type": "auditor", "id": "third-party-audit"},
        artifact={"digest": base_scope.artifact_digest},
        scope=base_scope,
        payload={"independent": True, "verdict": "PASS"},
        recorded_at="2026-09-26T12:03:00Z",
    )

    result = ledger.evaluate_claim(
        claim_type=ClaimType.SANDBOX_ATTESTED,
        subject="execution:run-431",
        scope=base_scope,
        cited_evidence_ids=[probe_ev.event_id, adj_ev.event_id],
        require_independent_adjudication=True,
    )

    assert result.status == ClaimStatus.TRUE
    assert len(result.violations) == 0
    assert ledger.verify_chain_integrity() is True


def test_reject_mutable_references():
    """Invariant: Artifact digest must be an immutable cryptographic content digest, not a mutable tag or branch."""
    with pytest.raises(MutableReferenceError, match="contains mutable token 'latest'"):
        ScopeBinding(
            artifact_digest="docker.io/library/worker:latest",
            environment_digest="sha256:1111",
            time_interval_start="2026-09-26T12:00:00Z",
            time_interval_end="2026-09-26T12:05:00Z",
            policy_ref="policy@1.0",
            authority_id="sec-01",
        )

    with pytest.raises(MutableReferenceError, match="contains mutable token 'main'"):
        ScopeBinding(
            artifact_digest="git:refs/heads/main",
            environment_digest="sha256:1111",
            time_interval_start="2026-09-26T12:00:00Z",
            time_interval_end="2026-09-26T12:05:00Z",
            policy_ref="policy@1.0",
            authority_id="sec-01",
        )

    with pytest.raises(MutableReferenceError, match="must be an immutable cryptographic content digest"):
        ScopeBinding(
            artifact_digest="unpinned-release-v1",
            environment_digest="sha256:1111",
            time_interval_start="2026-09-26T12:00:00Z",
            time_interval_end="2026-09-26T12:05:00Z",
            policy_ref="policy@1.0",
            authority_id="sec-01",
        )


def test_reject_duplicate_event_ids(base_scope):
    """Invariant: Replayed or duplicate event IDs must be rejected immediately."""
    ledger = DynamicEvidenceLedger()
    ledger.record_event(
        event_type=LedgerEventType.REQUEST_VALIDATED,
        plane=EvidencePlane.GOVERNANCE,
        actor={"type": "sec", "id": "auth"},
        artifact={"digest": base_scope.artifact_digest},
        scope=base_scope,
        payload={"ok": True},
        event_id="evt-fixed-001",
    )

    with pytest.raises(GovernanceViolation, match="DUPLICATE_EVENT_ID"):
        ledger.record_event(
            event_type=LedgerEventType.REQUEST_VALIDATED,
            plane=EvidencePlane.GOVERNANCE,
            actor={"type": "sec", "id": "auth"},
            artifact={"digest": base_scope.artifact_digest},
            scope=base_scope,
            payload={"ok": True},
            event_id="evt-fixed-001",
        )


def test_policy_version_substitution_rejected(base_scope):
    """Invariant: Evidence collected under policy revision A cannot support a claim under policy revision B."""
    ledger = DynamicEvidenceLedger()
    probe_ev = ledger.record_event(
        event_type=LedgerEventType.RUNTIME_PROBE_OBSERVED,
        plane=EvidencePlane.RUNTIME_SECURITY,
        actor={"type": "probe", "id": "confinement-probe"},
        artifact={"digest": base_scope.artifact_digest},
        scope=base_scope,  # policy_ref="sandbox-attestation-policy@1.0"
        payload={"probe": "all", "status": "PASS"},
        recorded_at="2026-09-26T12:02:00Z",
    )

    # Claim asserted under a different policy revision
    scope_policy_v2 = ScopeBinding(
        artifact_digest=base_scope.artifact_digest,
        environment_digest=base_scope.environment_digest,
        time_interval_start=base_scope.time_interval_start,
        time_interval_end=base_scope.time_interval_end,
        policy_ref="sandbox-attestation-policy@2.0",  # Different policy revision
        authority_id=base_scope.authority_id,
    )

    result = ledger.evaluate_claim(
        claim_type=ClaimType.RUNTIME_EGRESS_BLOCKED,
        subject="workload:run-123",
        scope=scope_policy_v2,
        cited_evidence_ids=[probe_ev.event_id],
    )

    assert result.status == ClaimStatus.UNVERIFIED
    assert ViolationType.SCOPE_MISMATCH in result.violations


def test_transitive_claim_laundering_prohibited(base_scope):
    """Invariant: A derived claim evaluation event cannot substitute as primary observation evidence."""
    ledger = DynamicEvidenceLedger()

    probe_ev = ledger.record_event(
        event_type=LedgerEventType.RUNTIME_PROBE_OBSERVED,
        plane=EvidencePlane.RUNTIME_SECURITY,
        actor={"type": "probe", "id": "network-monitor"},
        artifact={"digest": base_scope.artifact_digest},
        scope=base_scope,
        payload={"probe": "network_egress", "status": "PASS"},
        recorded_at="2026-09-26T12:02:00Z",
    )

    # First legitimate evaluation creates a CLAIM_EVALUATED event
    first_eval = ledger.evaluate_claim(
        claim_type=ClaimType.RUNTIME_EGRESS_BLOCKED,
        subject="network:run-1",
        scope=base_scope,
        cited_evidence_ids=[probe_ev.event_id],
    )
    assert first_eval.status == ClaimStatus.TRUE

    # Attacker tries to cite the derived CLAIM_EVALUATED event as primary evidence
    transitive_eval = ledger.evaluate_claim(
        claim_type=ClaimType.SANDBOX_ATTESTED,
        subject="execution:run-431",
        scope=base_scope,
        cited_evidence_ids=[first_eval.evaluation_event_id],
    )

    assert transitive_eval.status == ClaimStatus.UNVERIFIED
    assert ViolationType.UNSUPPORTED_INFERENCE in transitive_eval.violations


def test_partial_scope_sandbox_attestation_rejected(base_scope):
    """Invariant: Asserting SANDBOX_ATTESTED when only network egress is observed without filesystem isolation is rejected."""
    ledger = DynamicEvidenceLedger()

    # Network egress probe only
    net_probe = ledger.record_event(
        event_type=LedgerEventType.RUNTIME_PROBE_OBSERVED,
        plane=EvidencePlane.RUNTIME_SECURITY,
        actor={"type": "probe", "id": "network-probe"},
        artifact={"digest": base_scope.artifact_digest},
        scope=base_scope,
        payload={"probe": "network_egress", "status": "PASS"},
        recorded_at="2026-09-26T12:02:00Z",
    )

    adj_ev = ledger.record_event(
        event_type=LedgerEventType.INDEPENDENT_ADJUDICATION_RECORDED,
        plane=EvidencePlane.RUNTIME_SECURITY,
        actor={"type": "auditor", "id": "auditor-01"},
        artifact={"digest": base_scope.artifact_digest},
        scope=base_scope,
        payload={"independent": True, "verdict": "PASS"},
        recorded_at="2026-09-26T12:03:00Z",
    )

    # Filesystem probe is missing
    partial_result = ledger.evaluate_claim(
        claim_type=ClaimType.SANDBOX_ATTESTED,
        subject="execution:run-431",
        scope=base_scope,
        cited_evidence_ids=[net_probe.event_id, adj_ev.event_id],
        require_independent_adjudication=True,
    )

    assert partial_result.status == ClaimStatus.UNVERIFIED
    assert ViolationType.MISSING_PREREQUISITE in partial_result.violations

    # Add the missing filesystem probe
    fs_probe = ledger.record_event(
        event_type=LedgerEventType.RUNTIME_PROBE_OBSERVED,
        plane=EvidencePlane.RUNTIME_SECURITY,
        actor={"type": "probe", "id": "fs-probe"},
        artifact={"digest": base_scope.artifact_digest},
        scope=base_scope,
        payload={"probe": "filesystem_openat2", "status": "PASS"},
        recorded_at="2026-09-26T12:02:30Z",
    )

    complete_result = ledger.evaluate_claim(
        claim_type=ClaimType.SANDBOX_ATTESTED,
        subject="execution:run-431",
        scope=base_scope,
        cited_evidence_ids=[net_probe.event_id, fs_probe.event_id, adj_ev.event_id],
        require_independent_adjudication=True,
    )

    assert complete_result.status == ClaimStatus.TRUE
    assert len(complete_result.violations) == 0


TEST_KEY = b"k" * 32


def _promote(ledger, scope, permit, digest=None):
    return ledger.record_event(
        event_type=LedgerEventType.CHAMPION_PROMOTED,
        plane=EvidencePlane.GOVERNANCE,
        actor={"agent": "osiris.promotion.manager", "role": "PROMOTION_AUTHORITY"},
        artifact={"digest": digest or scope.artifact_digest},
        scope=scope,
        payload={"metric": "0.999"},
        authority_permit=permit,
    )


def test_privileged_event_without_permit_raises_authority_gate_error(base_scope):
    ledger = DynamicEvidenceLedger(permit_authority=PermitAuthority(TEST_KEY))
    with pytest.raises(AuthorityGateError, match="requires an authenticated authority permit"):
        _promote(ledger, base_scope, None)


def test_ledger_without_permit_authority_rejects_privileged_events(base_scope):
    signed = PermitAuthority(TEST_KEY).issue("osiris.promotion.manager", PROMOTION_SCOPE, base_scope.artifact_digest)
    with pytest.raises(AuthorityGateError, match="NO_PERMIT_AUTHORITY"):
        _promote(DynamicEvidenceLedger(), base_scope, signed)


def test_self_minted_unsigned_permit_rejected(base_scope):
    ledger = DynamicEvidenceLedger(permit_authority=PermitAuthority(TEST_KEY))
    forged = AuthorityPermit(
        issuer="unauthorized_agent", scope=PROMOTION_SCOPE, target_digest=base_scope.artifact_digest,
        nonce="n", issued_at_utc="2000-01-01T00:00:00Z", expires_at_utc="2099-01-01T00:00:00Z",
    )
    with pytest.raises(AuthorityGateError, match="PERMIT_SIGNATURE_INVALID"):
        _promote(ledger, base_scope, forged)


def test_permit_signed_with_other_key_rejected(base_scope):
    ledger = DynamicEvidenceLedger(permit_authority=PermitAuthority(TEST_KEY))
    other = PermitAuthority(b"x" * 32).issue("agent", PROMOTION_SCOPE, base_scope.artifact_digest)
    with pytest.raises(AuthorityGateError, match="PERMIT_SIGNATURE_INVALID"):
        _promote(ledger, base_scope, other)


def test_tampered_permit_target_rejected(base_scope):
    authority = PermitAuthority(TEST_KEY)
    ledger = DynamicEvidenceLedger(permit_authority=authority)
    signed = authority.issue("osiris.promotion.manager", PROMOTION_SCOPE, "sha256:" + "ab" * 32)
    tampered = dataclasses.replace(signed, target_digest=base_scope.artifact_digest)
    with pytest.raises(AuthorityGateError, match="PERMIT_SIGNATURE_INVALID"):
        _promote(ledger, base_scope, tampered)


def test_expired_permit_rejected(base_scope):
    authority = PermitAuthority(TEST_KEY)
    ledger = DynamicEvidenceLedger(permit_authority=authority)
    old = authority.issue("osiris.promotion.manager", PROMOTION_SCOPE, base_scope.artifact_digest,
                          ttl_seconds=60, now=datetime(2000, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(AuthorityGateError, match="PERMIT_EXPIRED"):
        _promote(ledger, base_scope, old)


def test_empty_target_permit_cannot_be_issued():
    with pytest.raises(ValueError, match="must not be empty"):
        PermitAuthority(TEST_KEY).issue("agent", PROMOTION_SCOPE, "")


def test_permit_nonce_replay_rejected(base_scope):
    authority = PermitAuthority(TEST_KEY)
    ledger = DynamicEvidenceLedger(permit_authority=authority)
    permit = authority.issue("osiris.promotion.manager", PROMOTION_SCOPE, base_scope.artifact_digest)
    _promote(ledger, base_scope, permit)
    with pytest.raises(NonceReplayDetected):
        _promote(ledger, base_scope, permit)


def test_privileged_event_with_mismatched_permit_digest_raises_binding_mismatch(base_scope):
    authority = PermitAuthority(TEST_KEY)
    ledger = DynamicEvidenceLedger(permit_authority=authority)
    permit = authority.issue("osiris.promotion.manager", PROMOTION_SCOPE, "sha256:" + "cd" * 32)
    with pytest.raises(ExecutionBindingMismatch, match="Authority permit digest mismatch"):
        _promote(ledger, base_scope, permit)


def test_privileged_event_with_unauthorized_scope_raises_scope_violation(base_scope):
    authority = PermitAuthority(TEST_KEY)
    ledger = DynamicEvidenceLedger(permit_authority=authority)
    permit = authority.issue("osiris.promotion.manager", "UNAUTHORIZED_ARBITRARY_SCOPE", base_scope.artifact_digest)
    with pytest.raises(ScopeViolation, match="Unauthorized authority permit scope"):
        _promote(ledger, base_scope, permit)


def test_privileged_event_with_valid_permit_succeeds(base_scope):
    authority = PermitAuthority(TEST_KEY)
    ledger = DynamicEvidenceLedger(permit_authority=authority)
    event = _promote(ledger, base_scope, authority.issue("osiris.promotion.manager", PROMOTION_SCOPE, base_scope.artifact_digest))
    assert event.event_type == LedgerEventType.CHAMPION_PROMOTED
    assert event.record_digest.startswith("sha256:")
    assert ledger.verify_chain_integrity() is True
