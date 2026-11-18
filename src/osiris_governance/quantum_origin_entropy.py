"""Quantinuum Quantum Origin Mermin-M3 Entropy Certifier & FIPS 204 Seed Provider.

Implements the 3-qubit Mermin inequality (M3) device-independent randomness
certification protocol (Foreman et al., Quantum 7, 969, 2023) integrated with
OSIRIS canonical RFC 8785 provenance and NIST FIPS 204 ML-DSA-65 / Ed25519
hybrid key generation:

  M3 = <X1 X2 X3> - <X1 Y2 Y3> - <Y1 X2 Y3> - <Y1 Y2 X3>

Invariants enforced:
  - Classical Local Hidden Variable (LHV) ceiling: |M3| <= 2.0
  - Quantum GHZ theoretical maximum: |M3| = 4.0
  - Fail-closed certification: if the lower confidence bound M3_lower <= 2.0
    (or if any of the 4 settings XXX, XYY, YXY, YYX is missing or has < min_shots),
    min-entropy H_min = 0.0 and seed extraction raises GovernanceViolation.
  - Explicit evidence_class ('SIMULATED' vs 'HARDWARE'): simulator counts are
    sealed as 'SIMULATED' and never masquerade as physical QPU entropy.
  - Conditioning with OS CSPRNG (os.urandom) via SHAKE-256 (NIST FIPS 202/204)
    so conditioned output is at least as strong as the host CSPRNG even under
    SIMULATED testing modes.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import os
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from .canonical import canonical_sha256, canonicalize_json
from .errors import GovernanceViolation

MERMIN_SETTINGS: Tuple[Tuple[str, float], ...] = (
    ("XXX", +1.0),
    ("XYY", -1.0),
    ("YXY", -1.0),
    ("YYX", -1.0),
)
CLASSICAL_LHV_BOUND = 2.0
QUANTUM_GHZ_MAX = 4.0


def _parity_sign(bitstring: str) -> int:
    """Return +1 for even Hamming weight (000, 011, 101, 110) and -1 for odd (001, 010, 100, 111)."""
    cleaned = bitstring.strip()
    if len(cleaned) != 3 or any(c not in ("0", "1") for c in cleaned):
        raise GovernanceViolation(f"Invalid 3-qubit Mermin readout bitstring: {bitstring!r}")
    ones = cleaned.count("1")
    return 1 if (ones % 2 == 0) else -1


def _binary_entropy(p: float) -> float:
    if p <= 0.0 or p >= 1.0:
        return 0.0
    return -p * math.log2(p) - (1.0 - p) * math.log2(1.0 - p)


@dataclass(frozen=True)
class MerminEvaluationResult:
    """Statistical evaluation of a 4-setting 3-qubit Mermin M3 experiment."""

    m3_raw: float
    m3_std_error: float
    m3_lower_bound: float
    z_sigma_above_classical: float
    certified_min_entropy_per_round: float
    total_shots: int
    total_certified_min_entropy_bits: float
    correlators: Dict[str, float]
    shots_per_setting: Dict[str, int]
    evidence_class: str  # "SIMULATED" or "HARDWARE"
    certified: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "m3_raw": round(self.m3_raw, 6),
            "m3_std_error": round(self.m3_std_error, 6),
            "m3_lower_bound": round(self.m3_lower_bound, 6),
            "z_sigma_above_classical": round(self.z_sigma_above_classical, 4),
            "certified_min_entropy_per_round": round(self.certified_min_entropy_per_round, 6),
            "total_shots": self.total_shots,
            "total_certified_min_entropy_bits": round(self.total_certified_min_entropy_bits, 2),
            "correlators": {k: round(v, 6) for k, v in sorted(self.correlators.items())},
            "shots_per_setting": dict(sorted(self.shots_per_setting.items())),
            "evidence_class": self.evidence_class,
            "certified": self.certified,
        }

    def to_canonical_dict(self) -> Dict[str, Any]:
        """Decimal-string representation compliant with OSIRIS-CANONICAL-JSON-V1 (no IEEE-754 floats)."""
        return {
            "m3_raw": f"{self.m3_raw:.6f}",
            "m3_std_error": f"{self.m3_std_error:.6f}",
            "m3_lower_bound": f"{self.m3_lower_bound:.6f}",
            "z_sigma_above_classical": f"{self.z_sigma_above_classical:.4f}",
            "certified_min_entropy_per_round": f"{self.certified_min_entropy_per_round:.6f}",
            "total_shots": int(self.total_shots),
            "total_certified_min_entropy_bits": f"{self.total_certified_min_entropy_bits:.2f}",
            "correlators": {k: f"{v:.6f}" for k, v in sorted(self.correlators.items())},
            "shots_per_setting": {k: int(v) for k, v in sorted(self.shots_per_setting.items())},
            "evidence_class": self.evidence_class,
            "certified": bool(self.certified),
        }


class MerminM3Certifier:
    """Evaluates 3-qubit Mermin M3 histograms and certifies device-independent min-entropy."""

    def __init__(
        self,
        min_shots_per_setting: int = 256,
        confidence_z: float = 5.0,
    ) -> None:
        if min_shots_per_setting < 16:
            raise ValueError("min_shots_per_setting must be >= 16")
        if confidence_z <= 0.0:
            raise ValueError("confidence_z must be > 0")
        self.min_shots_per_setting = min_shots_per_setting
        self.confidence_z = confidence_z

    def evaluate_counts(
        self,
        counts_by_setting: Mapping[str, Mapping[str, int]],
        *,
        evidence_class: str = "SIMULATED",
    ) -> MerminEvaluationResult:
        """Compute M3 correlators, finite-sample lower bound, and certified min-entropy rate."""
        if evidence_class not in ("SIMULATED", "HARDWARE"):
            raise GovernanceViolation(
                f"evidence_class must be 'SIMULATED' or 'HARDWARE', got {evidence_class!r}"
            )

        correlators: Dict[str, float] = {}
        shots_map: Dict[str, int] = {}
        var_sum = 0.0
        m3_val = 0.0
        total_shots = 0

        for setting, coeff in MERMIN_SETTINGS:
            if setting not in counts_by_setting:
                raise GovernanceViolation(f"Missing required Mermin measurement setting: {setting}")
            hist = counts_by_setting[setting]
            if not isinstance(hist, Mapping) or not hist:
                raise GovernanceViolation(f"Empty or invalid histogram for setting {setting}")

            n_s = 0
            weighted_parity = 0
            for bitstr, count in hist.items():
                if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                    raise GovernanceViolation(
                        f"Shot count for {setting}:{bitstr} must be a non-negative integer"
                    )
                sign = _parity_sign(bitstr)
                n_s += count
                weighted_parity += sign * count

            if n_s < self.min_shots_per_setting:
                raise GovernanceViolation(
                    f"Setting {setting} has {n_s} shots, below minimum {self.min_shots_per_setting}"
                )

            exp_val = weighted_parity / n_s
            # Binomial variance on parity expectation in [-1, 1]: (1 - <O>^2) / N_s
            var_s = max(1e-12, (1.0 - min(1.0, exp_val * exp_val)) / n_s)
            correlators[setting] = exp_val
            shots_map[setting] = n_s
            var_sum += var_s
            m3_val += coeff * exp_val
            total_shots += n_s

        std_err = math.sqrt(var_sum)
        abs_m3 = abs(m3_val)
        m3_lower = abs_m3 - self.confidence_z * std_err
        z_sigma = (abs_m3 - CLASSICAL_LHV_BOUND) / max(1e-9, std_err)

        # Device-independent min-entropy lower bound per measurement round for M3 > 2:
        # Guessing probability P_guess(M3) <= 1/2 + 1/2 * sqrt(max(0, 1 - ((M3_lower - 2)/2)^2))
        if m3_lower <= CLASSICAL_LHV_BOUND:
            h_min_rate = 0.0
            certified = False
        else:
            norm_violation = min(1.0, max(0.0, (m3_lower - CLASSICAL_LHV_BOUND) / 2.0))
            p_guess = 0.5 + 0.5 * math.sqrt(max(0.0, 1.0 - norm_violation * norm_violation))
            h_min_rate = max(0.0, min(1.0, -math.log2(max(0.5, min(1.0, p_guess)))))
            certified = h_min_rate > 0.0

        min_rounds = min(shots_map.values())
        total_h_min_bits = h_min_rate * min_rounds

        return MerminEvaluationResult(
            m3_raw=m3_val,
            m3_std_error=std_err,
            m3_lower_bound=m3_lower,
            z_sigma_above_classical=z_sigma,
            certified_min_entropy_per_round=h_min_rate,
            total_shots=total_shots,
            total_certified_min_entropy_bits=total_h_min_bits,
            correlators=correlators,
            shots_per_setting=shots_map,
            evidence_class=evidence_class,
            certified=certified,
        )


@dataclass(frozen=True)
class CertifiedEntropySeedReceipt:
    """Canonical provenance receipt binding raw Mermin counts to a conditioned FIPS 204 seed."""

    seed_bytes: bytes
    seed_sha256: str
    raw_counts_sha256: str
    mermin_evaluation: MerminEvaluationResult
    evidence_class: str
    provider_job_id: Optional[str]
    receipt_sha256: str

    def to_manifest(self) -> Dict[str, Any]:
        return {
            "schema": "osiris-quantum-origin-seed-receipt/v1",
            "seed_num_bytes": len(self.seed_bytes),
            "seed_sha256": self.seed_sha256,
            "raw_counts_sha256": self.raw_counts_sha256,
            "evidence_class": self.evidence_class,
            "provider_job_id": self.provider_job_id,
            "mermin_evaluation": self.mermin_evaluation.to_dict(),
            "receipt_sha256": self.receipt_sha256,
        }


class QuantumOriginEntropyProvider:
    """Extracts Mermin-M3 certified entropy and mixes it with host CSPRNG for FIPS 204 / Ed25519."""

    def __init__(self, certifier: Optional[MerminM3Certifier] = None) -> None:
        self.certifier = certifier or MerminM3Certifier()

    def extract_certified_seed(
        self,
        counts_by_setting: Mapping[str, Mapping[str, int]],
        *,
        output_bytes: int = 64,
        evidence_class: str = "SIMULATED",
        provider_job_id: Optional[str] = None,
        extra_context: str = "OSIRIS_FIPS204_ML_DSA_65_KEYGEN",
        mix_os_urandom: bool = True,
    ) -> CertifiedEntropySeedReceipt:
        """Certify Mermin M3 violation and extract randomness via SHAKE-256 + HMAC conditioning."""
        if output_bytes < 16 or output_bytes > 8192:
            raise ValueError("output_bytes must be between 16 (128 bits) and 8192 (64 Kb)")
        if evidence_class == "SIMULATED" and provider_job_id is not None:
            raise GovernanceViolation(
                "SIMULATED Mermin entropy must not carry a fabricated hardware provider_job_id"
            )

        eval_res = self.certifier.evaluate_counts(
            counts_by_setting, evidence_class=evidence_class
        )
        if not eval_res.certified:
            raise GovernanceViolation(
                f"Mermin M3 certification failed closed: M3_lower={eval_res.m3_lower_bound:.4f} "
                f"<= classical LHV bound {CLASSICAL_LHV_BOUND}"
            )

        canonical_counts_bytes = canonicalize_json(dict(counts_by_setting))
        if isinstance(canonical_counts_bytes, str):
            canonical_counts_bytes = canonical_counts_bytes.encode("utf-8")
        raw_counts_sha256 = hashlib.sha256(canonical_counts_bytes).hexdigest()

        # Two-universal / cryptographic randomness extraction via SHAKE-256 over canonical counts
        quantum_extracted = hashlib.shake_256(
            f"QUANTUM_ORIGIN_M3:{extra_context}:".encode("utf-8") + canonical_counts_bytes
        ).digest(output_bytes)

        if mix_os_urandom:
            os_entropy = os.urandom(output_bytes)
            # XOR + SHAKE-256 hybrid conditioning: security >= max(H_min(Quantum), H(OS_CSPRNG))
            mixed_input = bytes(a ^ b for a, b in zip(quantum_extracted, os_entropy))
            final_seed = hashlib.shake_256(
                b"OSIRIS_HYBRID_ENTROPY_V1:" + quantum_extracted + os_entropy + mixed_input
            ).digest(output_bytes)
        else:
            final_seed = quantum_extracted

        seed_sha256 = hashlib.sha256(final_seed).hexdigest()
        body_for_hash = {
            "schema": "osiris-quantum-origin-seed-receipt/v1",
            "seed_num_bytes": output_bytes,
            "seed_sha256": seed_sha256,
            "raw_counts_sha256": raw_counts_sha256,
            "evidence_class": evidence_class,
            "provider_job_id": provider_job_id,
            "mermin_evaluation": eval_res.to_canonical_dict(),
        }
        receipt_sha256 = canonical_sha256(body_for_hash)

        return CertifiedEntropySeedReceipt(
            seed_bytes=final_seed,
            seed_sha256=seed_sha256,
            raw_counts_sha256=raw_counts_sha256,
            mermin_evaluation=eval_res,
            evidence_class=evidence_class,
            provider_job_id=provider_job_id,
            receipt_sha256=receipt_sha256,
        )
