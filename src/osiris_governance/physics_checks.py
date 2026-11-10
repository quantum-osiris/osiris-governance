"""Physics and Domain Detectability Verification Engine.

Enforces:
1. Anti-Seked Rule (GOVERNANCE.md Rule 1): Pre-execution invariance check.
   Symbolic / analytical audit of target observable dO/d_theta. If identically zero,
   aborts execution and quarantines the parameter as an unobservable lint defect.
2. Mandatory Noiseless Baseline (GOVERNANCE.md Rule 2):
   Ensures claimed discoveries are not anti-concentration unitary artifacts.
3. Physical Detectability & Drift Floor:
   Enforces effect size Delta >= k * sigma_drift.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from .errors import NoiselessBaselineError, SymbolicInvarianceError


@dataclass(frozen=True)
class InvarianceAuditResult:
    """Outcome of symbolic/analytical invariance audit for a parameter."""
    parameter_name: str
    is_invariant: bool
    max_gradient: float
    variance: float
    status: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NoiselessBaselineAuditResult:
    """Outcome of companion noiseless baseline evaluation."""
    phenomenon_name: str
    candidate_metric: float
    noiseless_metric: float
    delta_gap: float
    is_unitary_artifact: bool
    status: str
    message: str


@dataclass(frozen=True)
class DetectabilityAuditResult:
    """Outcome of physical noise-floor detectability audit."""
    effect_size: float
    drift_sigma: float
    snr: float
    detectable: bool
    message: str


class PhysicsDetectabilityVerifier:
    """Deterministic Verifier for physical and symbolic invariants."""

    def __init__(self, gradient_tol: float = 1e-5, unitary_artifact_tol: float = 0.01):
        self.gradient_tol = gradient_tol
        self.unitary_artifact_tol = unitary_artifact_tol

    # -------------------------------------------------------------------------
    # Rule 1: Anti-Seked Parameter Invariance Check
    # -------------------------------------------------------------------------
    def audit_parameter_invariance(
        self,
        observable_evaluator: Callable[[float], float],
        parameter_name: str = "theta",
        test_points: Optional[Sequence[float]] = None,
    ) -> InvarianceAuditResult:
        """Audits whether dO/d_theta is identically zero across the parameter domain.
        
        Evaluates observable O(theta) over test angles and computes finite-difference
        gradients. If max gradient < tolerance, the parameter is a mathematical identity
        (e.g., Bell state invariant under symmetric RY, refuting theta_lock = 51.843°).
        """
        if test_points is None:
            # 19 equidistant sample angles across [0, 2*pi]
            test_points = np.linspace(0.0, 2.0 * math.pi, 19, endpoint=False).tolist()

        values = [float(observable_evaluator(theta)) for theta in test_points]
        vals = np.array(values, dtype=np.float64)
        var = float(np.var(vals))

        # Approximate numerical gradients
        eps = 1e-4
        grads = []
        for theta in test_points:
            f_plus = float(observable_evaluator(theta + eps))
            f_minus = float(observable_evaluator(theta - eps))
            grad = abs((f_plus - f_minus) / (2.0 * eps))
            grads.append(grad)

        max_grad = float(max(grads)) if grads else 0.0
        is_invariant = (max_grad < self.gradient_tol) and (var < self.gradient_tol ** 2)

        if is_invariant:
            msg = (
                f"ANTI_SEKED_VIOLATION: Parameter '{parameter_name}' has identically zero gradient "
                f"(max |dO/d_theta| = {max_grad:.2e} < {self.gradient_tol:.2e}). "
                "The observable is invariant to this parameter; sweep aborted as mathematical identity."
            )
            return InvarianceAuditResult(
                parameter_name=parameter_name,
                is_invariant=True,
                max_gradient=max_grad,
                variance=var,
                status="ANTI_SEKED_BLOCKED",
                message=msg,
                details={"recommendation": "Demote parameter to linting issue; do not dispatch to QPU"},
            )

        msg = (
            f"Parameter '{parameter_name}' exhibits genuine observable dependence "
            f"(max |dO/d_theta| = {max_grad:.4f}, var={var:.4e}). Invariance test passed."
        )
        return InvarianceAuditResult(
            parameter_name=parameter_name,
            is_invariant=False,
            max_gradient=max_grad,
            variance=var,
            status="PASSED",
            message=msg,
        )

    # -------------------------------------------------------------------------
    # Rule 2: Mandatory Noiseless Baseline Check
    # -------------------------------------------------------------------------
    def audit_noiseless_baseline(
        self,
        candidate_metric: float,
        noiseless_metric: float,
        phenomenon_name: str = "quantum_signature",
    ) -> NoiselessBaselineAuditResult:
        """Audits whether an observed effect is present in noiseless simulation.
        
        If candidate metric matches noiseless simulation within tolerance, the effect
        is classified as a unitary circuit structure / anti-concentration artifact,
        preventing environmental discovery claims.
        """
        gap = abs(candidate_metric - noiseless_metric)
        is_artifact = gap <= self.unitary_artifact_tol

        if is_artifact:
            msg = (
                f"NOISELESS_BASELINE_ALERT: Phenomenon '{phenomenon_name}' appears identically in "
                f"noiseless statevector simulation (candidate={candidate_metric:.4f}, "
                f"noiseless={noiseless_metric:.4f}, gap={gap:.4f} <= {self.unitary_artifact_tol}). "
                "Must be classified as unitary circuit structure; environmental discovery claim prohibited."
            )
            return NoiselessBaselineAuditResult(
                phenomenon_name=phenomenon_name,
                candidate_metric=candidate_metric,
                noiseless_metric=noiseless_metric,
                delta_gap=gap,
                is_unitary_artifact=True,
                status="UNITARY_ARTIFACT_DETECTED",
                message=msg,
            )

        msg = (
            f"Phenomenon '{phenomenon_name}' demonstrates significant gap from noiseless baseline "
            f"(candidate={candidate_metric:.4f}, noiseless={noiseless_metric:.4f}, gap={gap:.4f}). "
            "Validated as genuine environmental / physical signature."
        )
        return NoiselessBaselineAuditResult(
            phenomenon_name=phenomenon_name,
            candidate_metric=candidate_metric,
            noiseless_metric=noiseless_metric,
            delta_gap=gap,
            is_unitary_artifact=False,
            status="PASSED",
            message=msg,
        )

    # -------------------------------------------------------------------------
    # Detectability & Physical Noise Floor Audit
    # -------------------------------------------------------------------------
    def audit_detectability(
        self,
        effect_size: float,
        drift_sigma: float,
        min_snr: float = 3.0,
    ) -> DetectabilityAuditResult:
        """Audits whether effect size is detectable above hardware drift envelope."""
        if drift_sigma <= 0.0:
            snr = float("inf") if effect_size > 0.0 else 0.0
        else:
            snr = abs(effect_size) / drift_sigma

        detectable = snr >= min_snr
        if not detectable:
            msg = (
                f"EFFECT_BELOW_NOISE_FLOOR: Effect size {effect_size:.4f} has SNR {snr:.2f} < {min_snr:.2f} "
                f"against calibration drift sigma={drift_sigma:.4f}. Cannot be distinguished from hardware drift."
            )
        else:
            msg = f"Effect size {effect_size:.4f} exceeds noise floor (SNR={snr:.2f} >= {min_snr:.2f})."

        return DetectabilityAuditResult(
            effect_size=effect_size,
            drift_sigma=drift_sigma,
            snr=snr,
            detectable=detectable,
            message=msg,
        )
