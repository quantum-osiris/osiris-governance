"""Simulator output is sealed as SIMULATED, never as a measurement."""

import pytest

from osiris_governance.errors import EvidenceIntegrityError
from osiris_governance.evidence_verifier import ExternalVerifier, RawDataPackage
from osiris_governance.models.claim import EpistemicStatus
from osiris_governance.models.evidence import EvidenceClass
from osiris_governance.models.ledger import EvidencePlane


def pkg():
    return RawDataPackage(raw_id="SIM-1", source_plane=EvidencePlane.REPRODUCIBILITY, provider_receipt_id=None,
                          raw_payload={"counts": {"00": 500, "11": 500}}, captured_at_utc="2026-11-14T00:00:00Z",
                          metadata={"target_state": "00"})


def test_default_is_unchanged_measured():
    pack = ExternalVerifier().verify_and_seal(pkg(), {"survival_fidelity": 0.5}, claim_id="C")
    assert pack.epistemic_status == EpistemicStatus.MEASURED
    assert pack.evidence_record.evidence_class == EvidenceClass.MEASURED


def test_simulated_match_is_sealed_simulated():
    pack = ExternalVerifier().verify_and_seal(pkg(), {"survival_fidelity": 0.5}, claim_id="C",
                                              evidence_class=EvidenceClass.SIMULATED)
    assert pack.all_matched
    assert pack.epistemic_status == EpistemicStatus.SIMULATED
    assert pack.evidence_record.evidence_class == EvidenceClass.SIMULATED


def test_simulated_mismatch_is_refuted():
    pack = ExternalVerifier().verify_and_seal(pkg(), {"survival_fidelity": 0.9}, claim_id="C",
                                              evidence_class=EvidenceClass.SIMULATED)
    assert pack.epistemic_status == EpistemicStatus.REFUTED


@pytest.mark.parametrize("cls", [EvidenceClass.DERIVED, EvidenceClass.DECLARED, EvidenceClass.HYPOTHESIS])
def test_other_classes_cannot_be_sealed(cls):
    with pytest.raises(EvidenceIntegrityError):
        ExternalVerifier().verify_and_seal(pkg(), {}, claim_id="C", evidence_class=cls)
