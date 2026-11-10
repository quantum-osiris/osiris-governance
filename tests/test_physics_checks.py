"""Tests for Stage 3 Physics & Domain Detectability Checks."""

import math
import pytest
from osiris_governance.physics_checks import (
    DetectabilityAuditResult,
    InvarianceAuditResult,
    NoiselessBaselineAuditResult,
    PhysicsDetectabilityVerifier,
)


def test_anti_seked_blocks_flat_parameter():
    verifier = PhysicsDetectabilityVerifier(gradient_tol=1e-4)

    # Simulated flat observable: Bell fidelity invariant under symmetric rotation
    # e.g. O(theta) = 1.0 (constant for all theta)
    def flat_observable(theta: float) -> float:
        return 1.0

    result = verifier.audit_parameter_invariance(flat_observable, parameter_name="theta_lock")
    assert result.is_invariant is True
    assert result.status == "ANTI_SEKED_BLOCKED"
    assert "ANTI_SEKED_VIOLATION" in result.message


def test_anti_seked_passes_active_parameter():
    verifier = PhysicsDetectabilityVerifier(gradient_tol=1e-4)

    # Parameterized observable with real variation: O(theta) = cos^2(theta / 2)
    def active_observable(theta: float) -> float:
        return math.cos(theta / 2.0) ** 2

    result = verifier.audit_parameter_invariance(active_observable, parameter_name="rx_angle")
    assert result.is_invariant is False
    assert result.status == "PASSED"
    assert result.max_gradient > 0.1


def test_noiseless_baseline_catches_unitary_artifact():
    verifier = PhysicsDetectabilityVerifier(unitary_artifact_tol=0.01)

    # TVD dip at depth 3 is 0.18 on hardware, but 0.182 on noiseless statevector
    cand_metric = 0.180
    noiseless_metric = 0.182
    result = verifier.audit_noiseless_baseline(
        candidate_metric=cand_metric,
        noiseless_metric=noiseless_metric,
        phenomenon_name="fast_scrambling_tvd_dip",
    )
    assert result.is_unitary_artifact is True
    assert result.status == "UNITARY_ARTIFACT_DETECTED"
    assert "environmental discovery claim prohibited" in result.message


def test_noiseless_baseline_validates_genuine_noise_gap():
    verifier = PhysicsDetectabilityVerifier(unitary_artifact_tol=0.01)

    # Hardware fidelity is 0.73 due to dephasing, noiseless is 1.00 (gap 0.27)
    cand_metric = 0.730
    noiseless_metric = 1.000
    result = verifier.audit_noiseless_baseline(
        candidate_metric=cand_metric,
        noiseless_metric=noiseless_metric,
        phenomenon_name="teleportation_phase_damping",
    )
    assert result.is_unitary_artifact is False
    assert result.status == "PASSED"


def test_detectability_envelope():
    verifier = PhysicsDetectabilityVerifier()

    # Effect size 0.05, drift sigma 0.01 -> SNR 5.0 >= 3.0 (Pass)
    res_pass = verifier.audit_detectability(effect_size=0.05, drift_sigma=0.01, min_snr=3.0)
    assert res_pass.detectable is True
    assert res_pass.snr == pytest.approx(5.0)

    # Effect size 0.01, drift sigma 0.01 -> SNR 1.0 < 3.0 (Fail)
    res_fail = verifier.audit_detectability(effect_size=0.01, drift_sigma=0.01, min_snr=3.0)
    assert res_fail.detectable is False
    assert "EFFECT_BELOW_NOISE_FLOOR" in res_fail.message
