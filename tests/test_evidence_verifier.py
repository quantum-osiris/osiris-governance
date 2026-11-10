"""Tests for Stage 1 Evidence Verifier and Document Claim Scanner."""

import pytest
from osiris_governance.contracts import PermitAuthority
from osiris_governance.errors import AuthorityGateError, EvidenceIntegrityError
from osiris_governance.evidence_verifier import (
    DEFAULT_NUMERICAL_TOLERANCE,
    ExternalVerifier,
    RawDataPackage,
    audit_document_numerical_claims,
)
from osiris_governance.ledger import DynamicEvidenceLedger
from osiris_governance.models.claim import EpistemicStatus
from osiris_governance.models.ledger import ClaimStatus, EvidencePlane, LedgerEventType, ViolationType

AUTHORITY = PermitAuthority(b"k" * 32)


def test_recompute_bitstring_counts_deterministic():
    counts = {"00": 500, "11": 500}
    res = ExternalVerifier.recompute_bitstring_counts(counts)
    assert res["total_shots"] == 1000
    assert res["probabilities"]["00"] == 0.5
    assert res["probabilities"]["11"] == 0.5
    assert res["n_qubits"] == 2
    # Marginal Z expectations on qubit 0 (least significant bit) and qubit 1:
    # 00 has bit0='0' and bit1='0'; 11 has bit0='1' and bit1='1'
    assert res["z_expectations"][0] == 0.0
    assert res["z_expectations"][1] == 0.0
    # Parity: '00' popcount 0 -> +1; '11' popcount 2 -> +1. Parity should be 1.0
    assert res["parity"] == 1.0


def test_recompute_survival_fidelity():
    counts = {"000": 800, "001": 100, "111": 100}
    fid = ExternalVerifier.recompute_survival_fidelity(counts, "000")
    assert fid == 0.8


def test_recompute_continuous_samples():
    samples = [10.0, 12.0, 9.0, 11.0, 13.0]
    stats = ExternalVerifier.recompute_continuous_samples(samples)
    assert stats["n"] == 5.0
    assert stats["mean"] == 11.0
    assert stats["median"] == 11.0
    assert stats["min"] == 9.0
    assert stats["max"] == 13.0


def test_verify_and_seal_exact_match():
    verifier = ExternalVerifier(tolerance=1e-5, permit_authority=AUTHORITY)
    ledger = DynamicEvidenceLedger(ledger_id="test-ledger-001", permit_authority=AUTHORITY)
    raw_pkg = RawDataPackage(
        raw_id="RAW-RUN-001",
        source_plane=EvidencePlane.SCIENTIFIC_EXPERIMENTAL,
        provider_receipt_id="job_qpu_12345",
        raw_payload={"counts": {"00": 845, "11": 155}},
        captured_at_utc="2026-10-07T07:00:00Z",
        metadata={"target_state": "00"},
    )
    # Target state 00 survival fidelity is 845 / 1000 = 0.845
    claimed = {"survival_fidelity": 0.845, "total_shots": 1000.0}
    pack = verifier.verify_and_seal(
        raw_pkg=raw_pkg,
        claimed_metrics=claimed,
        claim_id="CLM-FIDELITY-001",
    )
    assert pack.all_matched is True
    assert pack.epistemic_status == EpistemicStatus.MEASURED
    assert len(pack.verification_results) == 2
    assert pack.verification_results[0].matched is True

    # Record to ledger
    eval_event = verifier.record_to_ledger(
        ledger=ledger,
        verified_pack=pack,
        claim_id="CLM-FIDELITY-001",
        subject="Teleportation Fidelity",
        statement="Ground truth target state achieved 0.845 fidelity",
    )
    assert eval_event.payload["status"] == ClaimStatus.TRUE.value
    assert len(eval_event.payload["violations"]) == 0
    assert ledger.event_count == 4


def test_verify_and_seal_mismatch_demotes_to_refuted():
    verifier = ExternalVerifier(tolerance=1e-5, permit_authority=AUTHORITY)
    ledger = DynamicEvidenceLedger(ledger_id="test-ledger-002", permit_authority=AUTHORITY)
    raw_pkg = RawDataPackage(
        raw_id="RAW-RUN-002",
        source_plane=EvidencePlane.SCIENTIFIC_EXPERIMENTAL,
        provider_receipt_id="job_qpu_99999",
        raw_payload={"counts": {"00": 700, "11": 300}},
        captured_at_utc="2026-10-07T07:00:00Z",
        metadata={"target_state": "00"},
    )
    # Real is 0.700, but agent hallucinates / claims 0.845
    claimed = {"survival_fidelity": 0.845}
    pack = verifier.verify_and_seal(
        raw_pkg=raw_pkg,
        claimed_metrics=claimed,
        claim_id="CLM-FIDELITY-002",
    )
    assert pack.all_matched is False
    assert pack.epistemic_status == EpistemicStatus.REFUTED
    assert pack.verification_results[0].matched is False
    assert pytest.approx(pack.verification_results[0].recomputed_value, 1e-5) == 0.700

    # Record to ledger and check adverse adjudication
    eval_event = verifier.record_to_ledger(
        ledger=ledger,
        verified_pack=pack,
        claim_id="CLM-FIDELITY-002",
        subject="Teleportation Fidelity",
        statement="Hallucinated claim that fidelity is 0.845",
    )
    assert eval_event.payload["status"] == ClaimStatus.FALSE.value
    assert ViolationType.UNVERIFIED_NUMERICAL_CLAIM.value in eval_event.payload["violations"]


def test_verify_and_seal_metric_not_in_raw():
    verifier = ExternalVerifier(permit_authority=AUTHORITY)
    raw_pkg = RawDataPackage(
        raw_id="RAW-RUN-003",
        source_plane=EvidencePlane.SCIENTIFIC_EXPERIMENTAL,
        provider_receipt_id="job_qpu_888",
        raw_payload={"counts": {"0": 50, "1": 50}},
        captured_at_utc="2026-10-07T07:00:00Z",
    )
    # Agent claims a metric that cannot be derived
    claimed = {"quantum_scrambling_velocity": 42.0}
    pack = verifier.verify_and_seal(
        raw_pkg=raw_pkg,
        claimed_metrics=claimed,
        claim_id="CLM-GHOST-001",
    )
    assert pack.all_matched is False
    assert pack.epistemic_status == EpistemicStatus.REFUTED
    assert pack.verification_results[0].matched is False


def test_document_claim_scanner_detects_unanchored_numbers():
    doc_unanchored = """
    Our dynamic decoupling optimization achieved a parity fidelity of 0.845,
    representing a 15.2% acceleration over baseline.
    """
    report = audit_document_numerical_claims(doc_unanchored)
    assert report.is_valid is False
    assert report.unanchored_findings >= 2
    assert any("0.845" in f.detected_number for f in report.findings)


def test_document_claim_scanner_accepts_cited_evidence():
    ledger = DynamicEvidenceLedger(permit_authority=AUTHORITY)
    verifier = ExternalVerifier(permit_authority=AUTHORITY)
    raw_pkg = RawDataPackage(
        raw_id="RUN-101",
        source_plane=EvidencePlane.SCIENTIFIC_EXPERIMENTAL,
        provider_receipt_id="job_001",
        raw_payload={"counts": {"00": 845, "11": 155}},
        captured_at_utc="2026-10-07T07:00:00Z",
        metadata={"target_state": "00"},
    )
    pack = verifier.verify_and_seal(raw_pkg, {"survival_fidelity": 0.845}, "CLM-101")
    verifier.record_to_ledger(ledger, pack, "CLM-101", "Subj", "Stmt")

    doc_anchored = "The verified target fidelity was 0.845 [EVD-RUN-101]."
    report = audit_document_numerical_claims(doc_anchored, ledger=ledger)
    assert report.is_valid is True
    assert report.unanchored_findings == 0


def test_record_to_ledger_requires_permit_authority():
    pkg = RawDataPackage(raw_id="RAW-X", source_plane=EvidencePlane.SCIENTIFIC_EXPERIMENTAL,
                         provider_receipt_id=None, raw_payload={"counts": {"0": 10}}, captured_at_utc="2026-10-07T00:00:00Z")
    unsigned = ExternalVerifier()
    pack = unsigned.verify_and_seal(pkg, {"survival_fidelity": 1.0}, "CLM-X")
    with pytest.raises(AuthorityGateError, match="NO_PERMIT_AUTHORITY"):
        unsigned.record_to_ledger(DynamicEvidenceLedger(permit_authority=AUTHORITY), pack, "CLM-X", "s", "t")


def test_batch_values_recomputed_from_raw():
    v = ExternalVerifier()
    counts = RawDataPackage(raw_id="A", source_plane=EvidencePlane.SCIENTIFIC_EXPERIMENTAL, provider_receipt_id=None,
                            raw_payload={"counts": {"00": 750, "11": 250}}, captured_at_utc="t", metadata={"target_state": "00"})
    samples = RawDataPackage(raw_id="B", source_plane=EvidencePlane.SCIENTIFIC_EXPERIMENTAL, provider_receipt_id=None,
                             raw_payload={"samples": [1, 2.5]}, captured_at_utc="t")
    neither = RawDataPackage(raw_id="C", source_plane=EvidencePlane.SCIENTIFIC_EXPERIMENTAL, provider_receipt_id=None,
                             raw_payload={"summary": 0.99}, captured_at_utc="t")
    assert v.batch_values(counts) == [0.75]
    assert v.batch_values(samples) == [1.0, 2.5]
    with pytest.raises(EvidenceIntegrityError):
        v.batch_values(neither)


def test_mean_qubit_zero_probability_matches_dnalang_survival_plus():
    counts = {"00": 500, "01": 200, "10": 100, "11": 200}
    # qubit 0 (rightmost) reads 0 in 00,10: 600/1000; qubit 1 in 00,01: 700/1000
    assert ExternalVerifier.recompute_mean_qubit_zero_probability(counts) == pytest.approx(0.65)
    pkg = RawDataPackage(raw_id="M", source_plane=EvidencePlane.SCIENTIFIC_EXPERIMENTAL, provider_receipt_id=None,
                         raw_payload={"counts": counts}, captured_at_utc="t", metadata={"metric": "mean_qubit_zero_probability"})
    assert ExternalVerifier().batch_values(pkg) == [pytest.approx(0.65)]
