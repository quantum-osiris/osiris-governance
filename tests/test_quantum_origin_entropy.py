"""Tests for Quantinuum Quantum Origin Mermin-M3 Entropy Certifier & Seed Provider."""

from __future__ import annotations

import pytest

from osiris_governance import (
    CLASSICAL_LHV_BOUND,
    QUANTUM_GHZ_MAX,
    GovernanceViolation,
    MerminM3Certifier,
    QuantumOriginEntropyProvider,
)


def _ideal_ghz_mermin_counts(shots: int = 1024):
    # For |GHZ> = (|000> + |111>)/sqrt(2):
    # <XXX> = +1 (even parity bitstrings: 000, 011, 101, 110)
    # <XYY> = -1 (odd parity bitstrings: 001, 010, 100, 111)
    # <YXY> = -1
    # <YYX> = -1
    # M3 = <XXX> - <XYY> - <YXY> - <YYX> = 4.0
    q = shots // 4
    even_hist = {"000": q, "011": q, "101": q, "110": shots - 3 * q}
    odd_hist = {"001": q, "010": q, "100": q, "111": shots - 3 * q}
    return {
        "XXX": dict(even_hist),
        "XYY": dict(odd_hist),
        "YXY": dict(odd_hist),
        "YYX": dict(odd_hist),
    }


def _noisy_ghz_mermin_counts(shots: int = 2048, visibility: float = 0.88):
    # Mixes ideal GHZ parities with (1 - visibility) uniform noise -> M3 ~ 4 * visibility = 3.52
    good = int(round(shots * (0.5 + 0.5 * visibility)))
    bad = shots - good
    return {
        "XXX": {"000": good // 2, "011": good - good // 2, "001": bad // 2, "111": bad - bad // 2},
        "XYY": {"001": good // 2, "010": good - good // 2, "000": bad // 2, "011": bad - bad // 2},
        "YXY": {"100": good // 2, "111": good - good // 2, "101": bad // 2, "110": bad - bad // 2},
        "YYX": {"010": good // 2, "111": good - good // 2, "000": bad // 2, "110": bad - bad // 2},
    }


def _classical_lhv_mermin_counts(shots: int = 1024):
    # Separable / classical local hidden variable assignment: <XXX>=+1, <XYY>=+1, <YXY>=+1, <YYX>=-1 -> M3 = 0 <= 2
    even_hist = {"000": shots // 2, "011": shots - shots // 2}
    odd_hist = {"001": shots // 2, "111": shots - shots // 2}
    return {
        "XXX": dict(even_hist),
        "XYY": dict(even_hist),
        "YXY": dict(even_hist),
        "YYX": dict(odd_hist),
    }


def test_ideal_and_noisy_ghz_violate_mermin_bound_and_certify_min_entropy():
    certifier = MerminM3Certifier(min_shots_per_setting=256, confidence_z=5.0)

    ideal_res = certifier.evaluate_counts(_ideal_ghz_mermin_counts(1024), evidence_class="SIMULATED")
    assert ideal_res.m3_raw == pytest.approx(QUANTUM_GHZ_MAX)
    assert ideal_res.m3_lower_bound > 3.9
    assert ideal_res.certified is True
    assert ideal_res.certified_min_entropy_per_round > 0.9

    noisy_res = certifier.evaluate_counts(_noisy_ghz_mermin_counts(2048, visibility=0.88), evidence_class="SIMULATED")
    assert noisy_res.m3_raw == pytest.approx(4.0 * 0.88, abs=0.02)
    assert noisy_res.m3_lower_bound > CLASSICAL_LHV_BOUND
    assert noisy_res.z_sigma_above_classical > 20.0
    assert noisy_res.certified is True
    assert 0.20 < noisy_res.certified_min_entropy_per_round < 1.0


def test_classical_lhv_or_insufficient_shots_fails_closed():
    certifier = MerminM3Certifier(min_shots_per_setting=256, confidence_z=5.0)
    provider = QuantumOriginEntropyProvider(certifier=certifier)

    lhv_res = certifier.evaluate_counts(_classical_lhv_mermin_counts(1024), evidence_class="SIMULATED")
    assert lhv_res.m3_lower_bound <= CLASSICAL_LHV_BOUND
    assert lhv_res.certified is False
    assert lhv_res.certified_min_entropy_per_round == 0.0

    with pytest.raises(GovernanceViolation, match="failed closed"):
        provider.extract_certified_seed(_classical_lhv_mermin_counts(1024), output_bytes=64)

    # Under-sampled setting (< 256 shots) is rejected
    under_sampled = _ideal_ghz_mermin_counts(128)
    with pytest.raises(GovernanceViolation, match="below minimum"):
        certifier.evaluate_counts(under_sampled)


def test_entropy_provider_extracts_64kb_seed_and_refuses_fake_hardware_job_id():
    provider = QuantumOriginEntropyProvider()
    counts = _noisy_ghz_mermin_counts(2048, visibility=0.90)

    # Refuses fabricated hardware job ID when evidence_class == "SIMULATED"
    with pytest.raises(GovernanceViolation, match="must not carry a fabricated hardware provider_job_id"):
        provider.extract_certified_seed(
            counts,
            output_bytes=64,
            evidence_class="SIMULATED",
            provider_job_id="qntm-helios-fake-job-001",
        )

    # Extracts full 64 Kb (8,192 bytes) certified seed with canonical receipt
    receipt = provider.extract_certified_seed(
        counts,
        output_bytes=8192,
        evidence_class="SIMULATED",
        mix_os_urandom=True,
    )
    assert len(receipt.seed_bytes) == 8192
    assert len(receipt.seed_sha256) == 64
    assert receipt.receipt_sha256.startswith("sha256:") and len(receipt.receipt_sha256) == 71
    manifest = receipt.to_manifest()
    assert manifest["evidence_class"] == "SIMULATED"
    assert manifest["mermin_evaluation"]["certified"] is True
