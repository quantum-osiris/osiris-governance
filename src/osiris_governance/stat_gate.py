"""Statistical Promotion Gate and Pre-Registered A/A Simulation Harness.

Enforces:
1. Anti-Winner's-Curse Protocol: Promotion decisions require two-stage split evaluation.
   No candidate can be promoted on the data it was selected on.
2. Anti-Pseudo-Replication Protocol: Multi-batch hierarchical uncertainty quantification.
   Bootstrapping must operate on cluster/batch units, not raw pooled shots.
3. Pre-Registered A/A Acceptance Gate: The gate must empirically satisfy FPR <= alpha
   under null simulation across the pipeline.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Collection, Dict, List, Mapping, Optional, Sequence, Tuple

from .canonical import canonical_sha256, canonicalize_json
from .errors import StatisticalGateError
from .models.ledger import ClaimStatus, ViolationType


@dataclass(frozen=True)
class PromotionDecision:
    """The adjudicated output of the statistical promotion gate."""
    promoted: bool
    challenger_median: float
    champion_median: float
    delta_median: float
    ci_lower: float
    ci_upper: float
    confidence_level: float
    replicates_evaluated: int
    batches_evaluated: int
    reason_code: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AASimulationReport:
    """Outcome of pre-registered A/A null testing across pipeline simulations."""
    n_simulations: int
    false_positives: int
    empirical_fpr: float
    alpha: float
    passed: bool
    message: str
    canonical_hash: str = ""

    def compute_hash(self) -> str:
        data = {
            "n_simulations": self.n_simulations,
            "false_positives": self.false_positives,
            "empirical_fpr": f"{self.empirical_fpr:.6f}",
            "alpha": f"{self.alpha:.6f}",
            "passed": self.passed,
        }
        return canonical_sha256(canonicalize_json(data))


def batch_digest(batch: Sequence[float]) -> str:
    """Content digest of one batch of observations (exact float repr)."""
    return canonical_sha256(canonicalize_json([repr(float(x)) for x in batch]))


def hierarchical_cluster_bootstrap_ci(
    champion_batches: Sequence[Sequence[float]],
    challenger_batches: Sequence[Sequence[float]],
    min_batches: int = 5,
    n_resamples: int = 2000,
    confidence_level: float = 0.95,
    seed: int = 20261001,
) -> Tuple[float, float, float]:
    """Computes cluster-bootstrap confidence interval over calibration batches.
    
    Prevents Devin Failure 5 (pseudo-replication from pooled shots or 2 replicates).
    Returns (delta_point_estimate, ci_lower, ci_upper).
    """
    n_champ = len(champion_batches)
    n_chall = len(challenger_batches)

    if n_champ < min_batches or n_chall < min_batches:
        raise StatisticalGateError(
            f"PSEUDO_REPLICATION_DETECTED: Require at least {min_batches} independent batches. "
            f"Observed: Champion={n_champ}, Challenger={n_chall}."
        )

    # Flatten point medians
    all_champ = [x for b in champion_batches for x in b]
    all_chall = [x for b in challenger_batches for x in b]
    if not all_champ or not all_chall:
        raise StatisticalGateError("Empty observation batches provided to bootstrap.")

    s_champ = sorted(all_champ)
    s_chall = sorted(all_chall)
    champ_point = s_champ[len(s_champ) // 2]
    chall_point = s_chall[len(s_chall) // 2]
    point_delta = chall_point - champ_point

    rng = random.Random(seed)
    deltas: List[float] = []

    for _ in range(n_resamples):
        # Resample batches with replacement
        sampled_champ_batches = [rng.choice(champion_batches) for _ in range(n_champ)]
        sampled_chall_batches = [rng.choice(challenger_batches) for _ in range(n_chall)]

        flat_champ = [x for b in sampled_champ_batches for x in b]
        flat_chall = [x for b in sampled_chall_batches for x in b]

        sc = sorted(flat_champ)
        sl = sorted(flat_chall)
        med_c = sc[len(sc) // 2]
        med_l = sl[len(sl) // 2]
        deltas.append(med_l - med_c)

    deltas.sort()
    alpha = 1.0 - confidence_level
    low_idx = int(math.floor(alpha / 2.0 * len(deltas)))
    high_idx = int(math.ceil((1.0 - alpha / 2.0) * len(deltas))) - 1
    high_idx = min(high_idx, len(deltas) - 1)

    return point_delta, deltas[low_idx], deltas[high_idx]


class StatisticalPromotionGate:
    """Evaluates algorithm/candidate promotion under strict null simulation and out-of-sample rules."""

    def __init__(
        self,
        alpha: float = 0.05,
        mde: float = 0.0,
        min_batches: int = 5,
        n_resamples: int = 2000,
        random_seed: int = 20261001,
    ):
        self.alpha = alpha
        self.mde = mde
        self.min_batches = min_batches
        self.n_resamples = n_resamples
        self.random_seed = random_seed
        self.confidence_level = 1.0 - alpha

    def evaluate_promotion(
        self,
        champion_batches: Sequence[Sequence[float]],
        challenger_batches: Sequence[Sequence[float]],
        search_batch_digests: Collection[str],
        heldout_batch_digests: Optional[Sequence[str]] = None,
    ) -> PromotionDecision:
        """Adjudicates whether challenger beats champion on held-out batches.

        Held-out status is established from data, not asserted: the caller must
        supply the digests of every batch the search saw, and no held-out batch
        may share a digest with them.
        heldout_batch_digests defaults to the content digests of the batches;
        pass raw-package digests when the batches were derived from them.
        """
        heldout = list(heldout_batch_digests) if heldout_batch_digests is not None else [
            batch_digest(b) for b in list(champion_batches) + list(challenger_batches)
        ]
        search = set(search_batch_digests)
        problem = None
        if not search:
            problem = ("NO_SEARCH_RECORD", "Promotion blocked: no search-batch digests supplied, so held-out status cannot be checked.")
        elif len(heldout) != len(champion_batches) + len(challenger_batches):
            problem = ("HELDOUT_DIGESTS_INCOMPLETE", "Promotion blocked: one digest is required per held-out batch.")
        elif search.intersection(heldout):
            problem = ("HELDOUT_OVERLAPS_SEARCH", f"Promotion blocked: {len(search.intersection(heldout))} held-out batch(es) were also used in search.")
        if problem:
            return PromotionDecision(
                promoted=False,
                challenger_median=0.0,
                champion_median=0.0,
                delta_median=0.0,
                ci_lower=0.0,
                ci_upper=0.0,
                confidence_level=self.confidence_level,
                replicates_evaluated=0,
                batches_evaluated=0,
                reason_code=f"WINNERS_CURSE_BLOCKED:{problem[0]}",
                message=problem[1],
                details={"violation": ViolationType.WINNERS_CURSE_DETECTED.value},
            )

        # 2. Check batch counts and compute bootstrap
        try:
            pt_delta, ci_low, ci_high = hierarchical_cluster_bootstrap_ci(
                champion_batches=champion_batches,
                challenger_batches=challenger_batches,
                min_batches=self.min_batches,
                n_resamples=self.n_resamples,
                confidence_level=self.confidence_level,
                seed=self.random_seed,
            )
        except StatisticalGateError as e:
            return PromotionDecision(
                promoted=False,
                challenger_median=0.0,
                champion_median=0.0,
                delta_median=0.0,
                ci_lower=0.0,
                ci_upper=0.0,
                confidence_level=self.confidence_level,
                replicates_evaluated=0,
                batches_evaluated=min(len(champion_batches), len(challenger_batches)),
                reason_code="PSEUDO_REPLICATION_BLOCKED",
                message=str(e),
                details={"violation": ViolationType.PSEUDO_REPLICATION_DETECTED.value},
            )

        all_champ = [x for b in champion_batches for x in b]
        all_chall = [x for b in challenger_batches for x in b]
        sc = sorted(all_champ)
        sl = sorted(all_chall)
        med_c = sc[len(sc) // 2]
        med_l = sl[len(sl) // 2]
        n_reps = len(all_chall)
        n_batches = len(challenger_batches)

        # 3. Decision rule: ci_lower > mde
        is_significant = ci_low > self.mde
        if is_significant:
            return PromotionDecision(
                promoted=True,
                challenger_median=med_l,
                champion_median=med_c,
                delta_median=pt_delta,
                ci_lower=ci_low,
                ci_upper=ci_high,
                confidence_level=self.confidence_level,
                replicates_evaluated=n_reps,
                batches_evaluated=n_batches,
                reason_code="PROMOTION_STATISTICALLY_CONFIRMED",
                message=(
                    f"Challenger verified superior: Delta {pt_delta:.4f} "
                    f"({int(self.confidence_level * 100)}% CI: [{ci_low:.4f}, {ci_high:.4f}] > MDE {self.mde})."
                ),
                details={"statistically_significant": True},
            )
        else:
            return PromotionDecision(
                promoted=False,
                challenger_median=med_l,
                champion_median=med_c,
                delta_median=pt_delta,
                ci_lower=ci_low,
                ci_upper=ci_high,
                confidence_level=self.confidence_level,
                replicates_evaluated=n_reps,
                batches_evaluated=n_batches,
                reason_code="INSUFFICIENT_STATISTICAL_SEPARATION",
                message=(
                    f"Promotion rejected: Delta {pt_delta:.4f} "
                    f"({int(self.confidence_level * 100)}% CI: [{ci_low:.4f}, {ci_high:.4f}] does not strictly exceed MDE {self.mde})."
                ),
                details={"statistically_significant": False},
            )

    def run_aa_validation(
        self,
        null_generator: Callable[[int], Sequence[Sequence[float]]],
        n_simulations: int = 1000,
    ) -> AASimulationReport:
        """Simulates full pipeline under null hypothesis (H0: Arm A and Arm B identical).
        
        The gate passes acceptance if and only if empirical FPR <= alpha (accounting
        for binomial sampling margin).
        """
        false_positives = 0
        for i in range(n_simulations):
            # Generate two independent arms from the identical null distribution
            arm_a = null_generator(seed=i * 3)
            arm_b = null_generator(seed=i * 3 + 1)
            search = null_generator(seed=i * 3 + 2)

            # Evaluate promotion under the gate
            decision = self.evaluate_promotion(
                champion_batches=arm_a,
                challenger_batches=arm_b,
                search_batch_digests=[batch_digest(b) for b in search],
            )
            if decision.promoted:
                false_positives += 1

        empirical_fpr = false_positives / n_simulations
        # Upper bound on binomial variation at 95% confidence
        binomial_margin = 1.96 * math.sqrt(self.alpha * (1.0 - self.alpha) / n_simulations)
        max_acceptable_fpr = self.alpha + binomial_margin
        passed = empirical_fpr <= max_acceptable_fpr

        msg = (
            f"A/A Null Simulation: {false_positives}/{n_simulations} false positives "
            f"(FPR={empirical_fpr:.4f}, nominal alpha={self.alpha:.4f}, max allowed={max_acceptable_fpr:.4f}). "
            f"Verdict: {'PASS' if passed else 'FAIL'}."
        )

        report = AASimulationReport(
            n_simulations=n_simulations,
            false_positives=false_positives,
            empirical_fpr=empirical_fpr,
            alpha=self.alpha,
            passed=passed,
            message=msg,
        )
        report = AASimulationReport(
            n_simulations=report.n_simulations,
            false_positives=report.false_positives,
            empirical_fpr=report.empirical_fpr,
            alpha=report.alpha,
            passed=report.passed,
            message=report.message,
            canonical_hash=report.compute_hash(),
        )
        if not passed:
            raise StatisticalGateError(
                f"A/A Gate Validation Failed: Empirical FPR {empirical_fpr:.4f} > {max_acceptable_fpr:.4f}. "
                "The promotion gate permits excess false discoveries."
            )
        return report
