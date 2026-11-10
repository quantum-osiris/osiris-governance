"""Tests for Stage 5 Champion/Challenger Promotion and Automated Rollback."""

import pytest
from osiris_governance.champion_challenger import (
    ChampionChallengerManager,
    ChampionState,
    PromotionPipelineResult,
    RollbackEventResult,
)
from osiris_governance.contracts import PermitAuthority
from osiris_governance.evidence_verifier import ExternalVerifier, RawDataPackage
from osiris_governance.ledger import DynamicEvidenceLedger
from osiris_governance.models.ledger import EvidencePlane, LedgerEventType
from osiris_governance.stat_gate import StatisticalPromotionGate


AUTHORITY = PermitAuthority(b"k" * 32)


def pkgs(prefix, batches):
    return [RawDataPackage(raw_id=f"{prefix}-{i}", source_plane=EvidencePlane.SCIENTIFIC_EXPERIMENTAL,
                           provider_receipt_id=None, raw_payload={"samples": list(b)},
                           captured_at_utc="2026-10-07T07:00:00Z") for i, b in enumerate(batches)]


SEARCH = pkgs("SEARCH", [[0.5, 0.6, 0.7]])


@pytest.fixture
def test_setup():
    ledger = DynamicEvidenceLedger(ledger_id="test-promotion-ledger", permit_authority=AUTHORITY)
    initial_champ = ChampionState(
        champion_id="CHAMP-001",
        artifact_digest="sha256:0000000000000000000000000000000000000000000000000000000000000001",
        baseline_median=1.00,
        mutation_score=0.80,
        promoted_at_utc="2026-10-07T00:00:00Z",
    )
    stat_gate = StatisticalPromotionGate(alpha=0.05, mde=0.05, min_batches=5, n_resamples=200)
    manager = ChampionChallengerManager(
        initial_champion=initial_champ,
        ledger=ledger,
        permit_authority=AUTHORITY,
        stat_gate=stat_gate,
        rollback_degradation_tolerance=0.10,  # 10% tolerance floor
    )
    return manager, ledger, initial_champ


def test_full_pipeline_successful_promotion(test_setup):
    manager, ledger, initial_champ = test_setup

    # Valid challenger raw data
    raw_pkg = RawDataPackage(
        raw_id="RAW-CHALL-002",
        source_plane=EvidencePlane.SCIENTIFIC_EXPERIMENTAL,
        provider_receipt_id="job_qpu_200",
        raw_payload={"counts": {"00": 900, "11": 100}},
        captured_at_utc="2026-10-07T07:10:00Z",
        metadata={"target_state": "00"},
    )
    claimed = {"survival_fidelity": 0.90}

    champ_batches = [
        [0.98, 1.02, 1.00],
        [1.01, 0.99, 1.00],
        [0.97, 1.03, 1.01],
        [1.00, 1.00, 1.02],
        [0.99, 1.01, 0.98],
    ]
    chall_batches = [
        [1.28, 1.32, 1.30],
        [1.31, 1.29, 1.30],
        [1.27, 1.33, 1.31],
        [1.30, 1.30, 1.32],
        [1.29, 1.31, 1.28],
    ]

    result = manager.evaluate_and_promote(
        challenger_id="CHALL-002",
        patch_diff="--- src/opt.py\n+++ src/opt.py\n@@ -1 +1 @@\n-pass\n+optimize()\n",
        source_code="def optimize(): return 42\n",
        raw_pkg=raw_pkg,
        claimed_metrics=claimed,
        champion_heldout_packages=pkgs("CHAMP", champ_batches),
        challenger_heldout_packages=pkgs("CHALL", chall_batches),
        search_packages=SEARCH,
        challenger_mutation_score=0.85,  # Higher than champion's 0.80
        correctness_passes=True,
    )

    assert result.promoted is True
    assert result.reason_code == "CHAMPION_PROMOTED"
    assert manager.active_champion.champion_id == "CHALL-002"
    assert manager.active_champion.mutation_score == 0.85

    # Check ledger recorded event
    events = [e for e in ledger.events if e.event_type == LedgerEventType.CHAMPION_PROMOTED]
    assert len(events) == 1
    assert events[0].payload["promoted_champion_id"] == "CHALL-002"


def test_promotion_rejected_on_mutation_score_regression(test_setup):
    manager, ledger, initial_champ = test_setup

    raw_pkg = RawDataPackage(
        raw_id="RAW-CHALL-003",
        source_plane=EvidencePlane.SCIENTIFIC_EXPERIMENTAL,
        provider_receipt_id="job_qpu_300",
        raw_payload={"counts": {"00": 900, "11": 100}},
        captured_at_utc="2026-10-07T07:10:00Z",
        metadata={"target_state": "00"},
    )
    claimed = {"survival_fidelity": 0.90}

    champ_batches = [[1.0] * 3 for _ in range(5)]
    chall_batches = [[1.5] * 3 for _ in range(5)]

    # Challenger mutant kill rate is 0.70 < champion's 0.80 (Rule 7 non-regression violation)
    result = manager.evaluate_and_promote(
        challenger_id="CHALL-003",
        patch_diff=None,
        source_code=None,
        raw_pkg=raw_pkg,
        claimed_metrics=claimed,
        champion_heldout_packages=pkgs("CHAMP", champ_batches),
        challenger_heldout_packages=pkgs("CHALL", chall_batches),
        search_packages=SEARCH,
        challenger_mutation_score=0.70,
        correctness_passes=True,
    )

    assert result.promoted is False
    assert result.reason_code == "MUTATION_SCORE_REGRESSION"
    assert "MUTATION_SCORE_REGRESSED" in result.message
    assert manager.active_champion.champion_id == "CHAMP-001"


def test_promotion_rejected_on_evidence_integrity_mismatch(test_setup):
    manager, ledger, initial_champ = test_setup

    # Raw bitstrings say 0.60, but claimed says 0.95
    raw_pkg = RawDataPackage(
        raw_id="RAW-CHALL-004",
        source_plane=EvidencePlane.SCIENTIFIC_EXPERIMENTAL,
        provider_receipt_id="job_qpu_400",
        raw_payload={"counts": {"00": 600, "11": 400}},
        captured_at_utc="2026-10-07T07:10:00Z",
        metadata={"target_state": "00"},
    )
    claimed = {"survival_fidelity": 0.95}

    champ_batches = [[1.0] * 3 for _ in range(5)]
    chall_batches = [[1.5] * 3 for _ in range(5)]

    result = manager.evaluate_and_promote(
        challenger_id="CHALL-004",
        patch_diff=None,
        source_code=None,
        raw_pkg=raw_pkg,
        claimed_metrics=claimed,
        champion_heldout_packages=pkgs("CHAMP", champ_batches),
        challenger_heldout_packages=pkgs("CHALL", chall_batches),
        search_packages=SEARCH,
        challenger_mutation_score=0.90,
        correctness_passes=True,
    )

    assert result.promoted is False
    assert result.reason_code == "EVIDENCE_INTEGRITY_MISMATCH"


def test_post_promotion_automated_rollback(test_setup):
    manager, ledger, initial_champ = test_setup

    # 1. Promote Challenger CHALL-005
    raw_pkg = RawDataPackage(
        raw_id="RAW-CHALL-005",
        source_plane=EvidencePlane.SCIENTIFIC_EXPERIMENTAL,
        provider_receipt_id="job_qpu_500",
        raw_payload={"counts": {"00": 900, "11": 100}},
        captured_at_utc="2026-10-07T07:10:00Z",
        metadata={"target_state": "00"},
    )
    champ_batches = [[1.00] * 3 for _ in range(5)]
    chall_batches = [[1.30] * 3 for _ in range(5)]

    res = manager.evaluate_and_promote(
        challenger_id="CHALL-005",
        patch_diff=None,
        source_code=None,
        raw_pkg=raw_pkg,
        claimed_metrics={"survival_fidelity": 0.90},
        champion_heldout_packages=pkgs("CHAMP", champ_batches),
        challenger_heldout_packages=pkgs("CHALL", chall_batches),
        search_packages=SEARCH,
        challenger_mutation_score=0.85,
    )
    assert res.promoted is True
    assert manager.active_champion.champion_id == "CHALL-005"
    assert manager.active_champion.baseline_median == 1.30

    # 2. Monitoring: performance is stable at 1.28 >= 1.30 * 0.90 (1.17 floor)
    stable_res = manager.monitor_and_rollback_if_degraded(post_promotion_median=1.28)
    assert stable_res.rolled_back is False
    assert manager.active_champion.champion_id == "CHALL-005"

    # 3. Sudden degradation: post-promotion median drops to 0.95 (< 1.17 floor)
    rollback_res = manager.monitor_and_rollback_if_degraded(post_promotion_median=0.95)
    assert rollback_res.rolled_back is True
    assert rollback_res.quarantined_champion_id == "CHALL-005"
    assert rollback_res.restored_champion_id == "CHAMP-001"
    assert manager.active_champion.champion_id == "CHAMP-001"
    assert manager.active_champion.artifact_digest == initial_champ.artifact_digest
    assert manager.active_champion is initial_champ

    # Check ledger event
    rb_events = [e for e in ledger.events if e.event_type == LedgerEventType.CHAMPION_ROLLED_BACK]
    assert len(rb_events) == 1
    assert rb_events[0].payload["quarantined_champion_id"] == "CHALL-005"
    assert rb_events[0].payload["restored_champion_id"] == "CHAMP-001"


def test_promotion_blocked_when_heldout_package_was_used_in_search(test_setup):
    manager, ledger, _ = test_setup
    raw_pkg = RawDataPackage(raw_id="RAW-6", source_plane=EvidencePlane.SCIENTIFIC_EXPERIMENTAL, provider_receipt_id=None,
                             raw_payload={"counts": {"00": 900, "11": 100}}, captured_at_utc="2026-10-07T07:10:00Z",
                             metadata={"target_state": "00"})
    chall = pkgs("CHALL", [[1.3 + i / 100] * 3 for i in range(5)])
    result = manager.evaluate_and_promote(
        challenger_id="CHALL-006", patch_diff=None, source_code=None, raw_pkg=raw_pkg,
        claimed_metrics={"survival_fidelity": 0.90},
        champion_heldout_packages=pkgs("CHAMP", [[1.0 + i / 100] * 3 for i in range(5)]),
        challenger_heldout_packages=chall,
        search_packages=[chall[0]],
        challenger_mutation_score=0.85,
    )
    assert result.promoted is False
    assert result.reason_code == "WINNERS_CURSE_BLOCKED:HELDOUT_OVERLAPS_SEARCH"
    assert not [e for e in ledger.events if e.event_type == LedgerEventType.CHAMPION_PROMOTED]


def test_promotion_blocked_when_heldout_has_no_raw_data(test_setup):
    manager, _, _ = test_setup
    raw_pkg = RawDataPackage(raw_id="RAW-7", source_plane=EvidencePlane.SCIENTIFIC_EXPERIMENTAL, provider_receipt_id=None,
                             raw_payload={"counts": {"00": 900, "11": 100}}, captured_at_utc="2026-10-07T07:10:00Z",
                             metadata={"target_state": "00"})
    summary_only = [RawDataPackage(raw_id=f"S-{i}", source_plane=EvidencePlane.SCIENTIFIC_EXPERIMENTAL, provider_receipt_id=None,
                                   raw_payload={"median": 1.5}, captured_at_utc="t") for i in range(5)]
    result = manager.evaluate_and_promote(
        challenger_id="CHALL-007", patch_diff=None, source_code=None, raw_pkg=raw_pkg,
        claimed_metrics={"survival_fidelity": 0.90},
        champion_heldout_packages=pkgs("CHAMP", [[1.0] * 3] * 5),
        challenger_heldout_packages=summary_only,
        search_packages=SEARCH,
        challenger_mutation_score=0.85,
    )
    assert result.promoted is False
    assert result.reason_code == "HELDOUT_RAW_DATA_INVALID"
