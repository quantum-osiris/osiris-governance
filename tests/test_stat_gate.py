"""Tests for Stage 2 Statistical Promotion Gate and A/A Null Testing."""

import random
import pytest
from osiris_governance.errors import StatisticalGateError
from osiris_governance.stat_gate import (
    AASimulationReport,
    PromotionDecision,
    StatisticalPromotionGate,
    batch_digest,
    hierarchical_cluster_bootstrap_ci,
)

SEARCH = [batch_digest([0.5, 0.6])]


def test_winners_curse_blocked_when_heldout_reuses_search_batch():
    gate = StatisticalPromotionGate(alpha=0.05, mde=0.01)
    champ = [[1.0, 1.1], [1.0, 1.2], [1.1, 1.1], [1.0, 1.0], [1.1, 1.2]]
    chall = [[1.5, 1.6], [1.5, 1.7], [1.6, 1.5], [1.5, 1.6], [1.6, 1.6]]
    search = [batch_digest(b) for b in chall[:1]]  # selection saw one of the "held-out" batches
    decision = gate.evaluate_promotion(champ, chall, search_batch_digests=search)
    assert decision.promoted is False
    assert decision.reason_code == "WINNERS_CURSE_BLOCKED:HELDOUT_OVERLAPS_SEARCH"


def test_winners_curse_blocked_without_search_record():
    gate = StatisticalPromotionGate(alpha=0.05, mde=0.01)
    champ = [[1.0, 1.1]] * 5
    chall = [[1.5, 1.6], [1.5, 1.7], [1.6, 1.5], [1.5, 1.6], [1.6, 1.6]]
    decision = gate.evaluate_promotion(champ, chall, search_batch_digests=[])
    assert decision.reason_code == "WINNERS_CURSE_BLOCKED:NO_SEARCH_RECORD"


def test_pseudo_replication_blocked_with_insufficient_batches():
    gate = StatisticalPromotionGate(alpha=0.05, min_batches=5)
    # Only 2 batches provided (Devin Failure 5)
    champ = [[1.0, 1.1, 1.0, 1.2], [1.1, 1.1, 1.0, 1.0]]
    chall = [[1.5, 1.6, 1.5, 1.7], [1.6, 1.5, 1.5, 1.6]]

    decision = gate.evaluate_promotion(champ, chall, search_batch_digests=SEARCH)
    assert decision.promoted is False
    assert decision.reason_code == "PSEUDO_REPLICATION_BLOCKED"


def test_genuine_superiority_promoted():
    gate = StatisticalPromotionGate(alpha=0.05, mde=0.05, min_batches=5, n_resamples=500)
    # Baseline ~ 1.0, Challenger ~ 1.3 (+0.3 delta, well above MDE 0.05)
    champ = [
        [0.98, 1.02, 1.00],
        [1.01, 0.99, 1.00],
        [0.97, 1.03, 1.01],
        [1.00, 1.00, 1.02],
        [0.99, 1.01, 0.98],
    ]
    chall = [
        [1.28, 1.32, 1.30],
        [1.31, 1.29, 1.30],
        [1.27, 1.33, 1.31],
        [1.30, 1.30, 1.32],
        [1.29, 1.31, 1.28],
    ]

    decision = gate.evaluate_promotion(champ, chall, search_batch_digests=SEARCH)
    assert decision.promoted is True
    assert decision.reason_code == "PROMOTION_STATISTICALLY_CONFIRMED"
    assert decision.ci_lower > 0.05
    assert decision.delta_median == pytest.approx(0.3, abs=0.05)


def test_noise_only_difference_rejected():
    gate = StatisticalPromotionGate(alpha=0.05, mde=0.02, min_batches=5, n_resamples=500)
    # Baseline ~ 1.0, Challenger ~ 1.005 (+0.005 delta, below MDE 0.02 and overlapping 0)
    champ = [
        [0.98, 1.02],
        [1.01, 0.99],
        [0.97, 1.03],
        [1.00, 1.00],
        [0.99, 1.01],
    ]
    chall = [
        [0.99, 1.02],
        [1.01, 1.00],
        [0.98, 1.02],
        [1.00, 1.01],
        [0.99, 1.01],
    ]

    decision = gate.evaluate_promotion(champ, chall, search_batch_digests=SEARCH)
    assert decision.promoted is False
    assert decision.reason_code == "INSUFFICIENT_STATISTICAL_SEPARATION"


def test_aa_null_validation_passes():
    # Pre-registered A/A simulation test
    gate = StatisticalPromotionGate(alpha=0.05, mde=0.0, min_batches=5, n_resamples=200)

    def null_generator(seed: int):
        rng = random.Random(seed)
        # 5 batches of 4 samples from standard normal + 10.0
        return [[10.0 + rng.gauss(0, 0.1) for _ in range(4)] for _ in range(5)]

    # Run 100 null pipeline simulations
    report = gate.run_aa_validation(null_generator, n_simulations=100)
    assert report.passed is True
    # In null runs with alpha=0.05, empirical FPR should be close to 0.05 (<= ~0.09)
    assert report.empirical_fpr <= 0.09
    assert report.canonical_hash.startswith("sha256:")
