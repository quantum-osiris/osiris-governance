"""Champion/Challenger Promotion Framework with Automated Rollback.

Enforces:
1. Multi-Gate Promotion Pipeline:
   - Confinement & AST Safety (Stage 4)
   - Evidence Integrity Recomputation (Stage 1)
   - Out-of-Sample Statistical Gate (Stage 2)
   - Physics & Domain Invariants (Stage 3)
   - Mutation Testing Non-Regression Gate (GOVERNANCE.md Rule 7 / Just et al. 2014)
2. Post-Promotion Shadow Monitoring & Automated Rollback:
   Monitors post-promotion execution drift. If performance degrades beyond
   rollback threshold, automatically reverts to previous champion and records
   CHAMPION_ROLLED_BACK event to immutable ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .canonical import canonical_sha256, canonicalize_json
from .candidate_router import EvaluatorConfinementGuard
from .contracts import PermitAuthority, PROMOTION_SCOPE
from .errors import EvidenceIntegrityError
from .evidence_verifier import ExternalVerifier, RawDataPackage, VerifiedEvidencePack
from .ledger import DynamicEvidenceLedger
from .models.ledger import (
    ClaimStatus,
    ClaimType,
    EvidencePlane,
    LedgerEvent,
    LedgerEventType,
    ScopeBinding,
    ViolationType,
)
from .physics_checks import PhysicsDetectabilityVerifier
from .stat_gate import PromotionDecision, StatisticalPromotionGate


@dataclass(frozen=True)
class ChampionState:
    """Active Champion record."""
    champion_id: str
    artifact_digest: str
    baseline_median: float
    mutation_score: float
    promoted_at_utc: str
    active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PromotionPipelineResult:
    """Complete multi-gate evaluation outcome."""
    challenger_id: str
    promoted: bool
    stage_confinement_passed: bool
    stage_correctness_passed: bool
    stage_integrity_passed: bool
    stage_stats_passed: bool
    stage_physics_passed: bool
    stage_mutation_non_regression_passed: bool
    reason_code: str
    message: str
    decision_details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RollbackEventResult:
    """Outcome of automated post-promotion rollback."""
    rolled_back: bool
    quarantined_champion_id: str
    restored_champion_id: str
    trigger_reason: str
    observed_metric: float
    rollback_threshold: float
    message: str


class ChampionChallengerManager:
    """Orchestrates end-to-end verified research promotion and rollback."""

    def __init__(
        self,
        initial_champion: ChampionState,
        ledger: DynamicEvidenceLedger,
        permit_authority: PermitAuthority,
        stat_gate: Optional[StatisticalPromotionGate] = None,
        verifier: Optional[ExternalVerifier] = None,
        confinement_guard: Optional[EvaluatorConfinementGuard] = None,
        physics_verifier: Optional[PhysicsDetectabilityVerifier] = None,
        rollback_degradation_tolerance: float = 0.05,
    ):
        self.active_champion = initial_champion
        self.champion_history: List[ChampionState] = [initial_champion]
        self.ledger = ledger
        self.permit_authority = permit_authority
        self.stat_gate = stat_gate or StatisticalPromotionGate(alpha=0.05)
        self.verifier = verifier or ExternalVerifier(permit_authority=permit_authority)
        self.confinement_guard = confinement_guard or EvaluatorConfinementGuard()
        self.physics_verifier = physics_verifier or PhysicsDetectabilityVerifier()
        self.rollback_tolerance = rollback_degradation_tolerance

    def evaluate_and_promote(
        self,
        challenger_id: str,
        patch_diff: Optional[str],
        source_code: Optional[str],
        raw_pkg: RawDataPackage,
        claimed_metrics: Mapping[str, float],
        champion_heldout_packages: Sequence[RawDataPackage],
        challenger_heldout_packages: Sequence[RawDataPackage],
        search_packages: Sequence[RawDataPackage],
        challenger_mutation_score: float,
        correctness_passes: bool = True,
        observable_evaluator: Optional[Any] = None,
    ) -> PromotionPipelineResult:
        """Executes the full 5-stage verified promotion sequence."""
        # Stage 4: Confinement & Safety
        if patch_diff is not None:
            c_res = self.confinement_guard.audit_patch_paths(patch_diff)
            if not c_res.is_admissible:
                return PromotionPipelineResult(
                    challenger_id=challenger_id,
                    promoted=False,
                    stage_confinement_passed=False,
                    stage_correctness_passed=False,
                    stage_integrity_passed=False,
                    stage_stats_passed=False,
                    stage_physics_passed=False,
                    stage_mutation_non_regression_passed=False,
                    reason_code=c_res.reason_code,
                    message=c_res.message,
                )

        if source_code is not None:
            a_res = self.confinement_guard.audit_ast_safety(source_code, candidate_id=challenger_id)
            if not a_res.is_admissible:
                return PromotionPipelineResult(
                    challenger_id=challenger_id,
                    promoted=False,
                    stage_confinement_passed=False,
                    stage_correctness_passed=False,
                    stage_integrity_passed=False,
                    stage_stats_passed=False,
                    stage_physics_passed=False,
                    stage_mutation_non_regression_passed=False,
                    reason_code=a_res.reason_code,
                    message=a_res.message,
                )

        # Stage Correctness Test Suite
        if not correctness_passes:
            return PromotionPipelineResult(
                challenger_id=challenger_id,
                promoted=False,
                stage_confinement_passed=True,
                stage_correctness_passed=False,
                stage_integrity_passed=False,
                stage_stats_passed=False,
                stage_physics_passed=False,
                stage_mutation_non_regression_passed=False,
                reason_code="CORRECTNESS_TESTS_FAILED",
                message="Candidate failed deterministic reference correctness tests.",
            )

        # Stage 1: Evidence Integrity Recomputation
        verified_pack = self.verifier.verify_and_seal(
            raw_pkg=raw_pkg,
            claimed_metrics=claimed_metrics,
            claim_id=f"CLM-{challenger_id}",
            subject=f"Candidate {challenger_id} Verification",
        )
        if not verified_pack.all_matched:
            return PromotionPipelineResult(
                challenger_id=challenger_id,
                promoted=False,
                stage_confinement_passed=True,
                stage_correctness_passed=True,
                stage_integrity_passed=False,
                stage_stats_passed=False,
                stage_physics_passed=False,
                stage_mutation_non_regression_passed=False,
                reason_code="EVIDENCE_INTEGRITY_MISMATCH",
                message="Candidate failed raw data metric recomputation check.",
                decision_details={"recomputed": verified_pack.recomputed_metrics},
            )

        # Stage 3: Physics Invariance & Detectability (Anti-Seked)
        if observable_evaluator is not None:
            inv_res = self.physics_verifier.audit_parameter_invariance(observable_evaluator)
            if inv_res.is_invariant:
                return PromotionPipelineResult(
                    challenger_id=challenger_id,
                    promoted=False,
                    stage_confinement_passed=True,
                    stage_correctness_passed=True,
                    stage_integrity_passed=True,
                    stage_stats_passed=False,
                    stage_physics_passed=False,
                    stage_mutation_non_regression_passed=False,
                    reason_code=inv_res.status,
                    message=inv_res.message,
                )

        # Stage 2: Statistical Promotion Gate (Out-of-sample)
        # Batches are recomputed from raw packages here; held-out status is checked by package digest.
        try:
            champion_batches = [self.verifier.batch_values(p) for p in champion_heldout_packages]
            challenger_batches = [self.verifier.batch_values(p) for p in challenger_heldout_packages]
        except EvidenceIntegrityError as e:
            return PromotionPipelineResult(
                challenger_id=challenger_id,
                promoted=False,
                stage_confinement_passed=True,
                stage_correctness_passed=True,
                stage_integrity_passed=False,
                stage_stats_passed=False,
                stage_physics_passed=True,
                stage_mutation_non_regression_passed=False,
                reason_code="HELDOUT_RAW_DATA_INVALID",
                message=str(e),
            )
        stat_decision = self.stat_gate.evaluate_promotion(
            champion_batches=champion_batches,
            challenger_batches=challenger_batches,
            search_batch_digests=[p.payload_digest() for p in search_packages],
            heldout_batch_digests=[p.payload_digest() for p in list(champion_heldout_packages) + list(challenger_heldout_packages)],
        )
        if not stat_decision.promoted:
            return PromotionPipelineResult(
                challenger_id=challenger_id,
                promoted=False,
                stage_confinement_passed=True,
                stage_correctness_passed=True,
                stage_integrity_passed=True,
                stage_stats_passed=False,
                stage_physics_passed=True,
                stage_mutation_non_regression_passed=False,
                reason_code=stat_decision.reason_code,
                message=stat_decision.message,
                decision_details={"ci_lower": stat_decision.ci_lower, "ci_upper": stat_decision.ci_upper},
            )

        # Stage Non-Regression Mutation Testing Gate (Rule 7)
        if challenger_mutation_score < self.active_champion.mutation_score:
            msg = (
                f"MUTATION_SCORE_REGRESSED: Challenger kill rate {challenger_mutation_score:.3f} < "
                f"Champion kill rate {self.active_champion.mutation_score:.3f}. Non-regression gate tripped."
            )
            return PromotionPipelineResult(
                challenger_id=challenger_id,
                promoted=False,
                stage_confinement_passed=True,
                stage_correctness_passed=True,
                stage_integrity_passed=True,
                stage_stats_passed=True,
                stage_physics_passed=True,
                stage_mutation_non_regression_passed=False,
                reason_code="MUTATION_SCORE_REGRESSION",
                message=msg,
                decision_details={
                    "challenger_score": challenger_mutation_score,
                    "champion_score": self.active_champion.mutation_score,
                },
            )

        # ALL GATES PASSED -> Promote Challenger to Champion
        now_utc = datetime.now(timezone.utc).isoformat()
        new_champion = ChampionState(
            champion_id=challenger_id,
            artifact_digest=verified_pack.raw_digest,
            baseline_median=stat_decision.challenger_median,
            mutation_score=challenger_mutation_score,
            promoted_at_utc=now_utc,
            active=True,
        )
        self.champion_history.append(new_champion)
        old_champion = self.active_champion
        self.active_champion = new_champion

        # Append promotion event to immutable ledger
        actor = {"agent": "osiris.promotion.manager", "role": "PROMOTION_AUTHORITY"}
        artifact = {"champion_id": challenger_id, "digest": new_champion.artifact_digest}
        scope = ScopeBinding(
            artifact_digest=new_champion.artifact_digest,
            environment_digest=new_champion.artifact_digest,
            time_interval_start=now_utc,
            time_interval_end=now_utc,
            policy_ref="OSIRIS-SPEC-VERIF-015",
            authority_id="osiris.promotion.manager",
        )
        promotion_permit = self.permit_authority.issue(
            issuer="osiris.promotion.manager",
            scope=PROMOTION_SCOPE,
            target_digest=new_champion.artifact_digest,
        )
        self.ledger.record_event(
            event_type=LedgerEventType.CHAMPION_PROMOTED,
            plane=EvidencePlane.GOVERNANCE,
            actor=actor,
            artifact=artifact,
            scope=scope,
            payload={
                "previous_champion_id": old_champion.champion_id,
                "promoted_champion_id": challenger_id,
                "delta_median": f"{stat_decision.delta_median:.6f}",
                "mutation_score": f"{challenger_mutation_score:.6f}",
            },
            authority_permit=promotion_permit,
            evidence_refs=[verified_pack.evidence_record.evidence_id],
        )

        return PromotionPipelineResult(
            challenger_id=challenger_id,
            promoted=True,
            stage_confinement_passed=True,
            stage_correctness_passed=True,
            stage_integrity_passed=True,
            stage_stats_passed=True,
            stage_physics_passed=True,
            stage_mutation_non_regression_passed=True,
            reason_code="CHAMPION_PROMOTED",
            message=f"Challenger '{challenger_id}' passed all verification stages and is now active Champion.",
            decision_details={
                "delta_median": stat_decision.delta_median,
                "ci_lower": stat_decision.ci_lower,
                "ci_upper": stat_decision.ci_upper,
                "mutation_score": challenger_mutation_score,
            },
        )

    def monitor_and_rollback_if_degraded(
        self,
        post_promotion_median: float,
    ) -> RollbackEventResult:
        """Monitors post-promotion execution. Triggers automated rollback upon degradation."""
        # Expected baseline performance
        expected_median = self.active_champion.baseline_median
        # Allowed degradation floor
        threshold = expected_median * (1.0 - self.rollback_tolerance)

        if post_promotion_median < threshold:
            # Performance degradation detected -> Roll back!
            if len(self.champion_history) < 2:
                # No previous champion to restore
                return RollbackEventResult(
                    rolled_back=False,
                    quarantined_champion_id=self.active_champion.champion_id,
                    restored_champion_id=self.active_champion.champion_id,
                    trigger_reason="NO_FALLBACK_CHAMPION_AVAILABLE",
                    observed_metric=post_promotion_median,
                    rollback_threshold=threshold,
                    message="Degradation detected, but no prior champion exists in history to restore.",
                )

            quarantined = self.active_champion
            # Restore previous champion
            restored = self.champion_history[-2]
            self.active_champion = restored

            now_utc = datetime.now(timezone.utc).isoformat()
            actor = {"agent": "osiris.rollback.watchdog", "role": "AUTOMATED_ROLLBACK"}
            artifact = {"quarantined_id": quarantined.champion_id, "restored_id": restored.champion_id}
            scope = ScopeBinding(
                artifact_digest=restored.artifact_digest,
                environment_digest=restored.artifact_digest,
                time_interval_start=now_utc,
                time_interval_end=now_utc,
                policy_ref="OSIRIS-SPEC-VERIF-015",
                authority_id="osiris.rollback.watchdog",
            )
            rollback_permit = self.permit_authority.issue(
                issuer="osiris.rollback.watchdog",
                scope=PROMOTION_SCOPE,
                target_digest=restored.artifact_digest,
            )
            self.ledger.record_event(
                event_type=LedgerEventType.CHAMPION_ROLLED_BACK,
                plane=EvidencePlane.GOVERNANCE,
                actor=actor,
                artifact=artifact,
                scope=scope,
                payload={
                    "quarantined_champion_id": quarantined.champion_id,
                    "restored_champion_id": restored.champion_id,
                    "observed_metric": f"{post_promotion_median:.6f}",
                    "rollback_threshold": f"{threshold:.6f}",
                    "reason": "POST_PROMOTION_DEGRADATION",
                },
                authority_permit=rollback_permit,
            )

            msg = (
                f"AUTOMATED_ROLLBACK: Champion '{quarantined.champion_id}' degraded to {post_promotion_median:.4f} "
                f"(below threshold {threshold:.4f}). Rollback executed; Champion '{restored.champion_id}' restored."
            )
            return RollbackEventResult(
                rolled_back=True,
                quarantined_champion_id=quarantined.champion_id,
                restored_champion_id=restored.champion_id,
                trigger_reason="POST_PROMOTION_DEGRADATION",
                observed_metric=post_promotion_median,
                rollback_threshold=threshold,
                message=msg,
            )

        return RollbackEventResult(
            rolled_back=False,
            quarantined_champion_id="",
            restored_champion_id=self.active_champion.champion_id,
            trigger_reason="PERFORMANCE_STABLE",
            observed_metric=post_promotion_median,
            rollback_threshold=threshold,
            message=f"Post-promotion monitoring stable ({post_promotion_median:.4f} >= threshold {threshold:.4f}).",
        )
