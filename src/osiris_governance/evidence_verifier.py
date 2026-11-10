"""Evidence Integrity and Recomputation Verifier.

Enforces the Adjudication Engine's primary epistemic invariant:
"No number can enter a claim unless the verifier can recompute it
from raw, externally obtained data."

All derived metrics (fidelity, parity, expectation, median, p99) are
recalculated deterministically from immutable raw counts/samples by this
verifier, which runs logically external to any agent write surface.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .canonical import canonical_sha256, canonicalize_json
from .contracts import PermitAuthority, VERIFICATION_SCOPE
from .errors import AuthorityGateError, EvidenceIntegrityError, GovernanceViolation
from .models.claim import ClaimRecord, EpistemicStatus, ReleaseRelevance
from .models.evidence import EvidenceClass, EvidenceDomain, EvidenceRecord
from .models.ledger import (
    ClaimStatus,
    ClaimType,
    EvidencePlane,
    LedgerEvent,
    LedgerEventType,
    ScopeBinding,
    ViolationType,
)
from .ledger import DynamicEvidenceLedger


DEFAULT_NUMERICAL_TOLERANCE = 1e-6


@dataclass(frozen=True)
class NumericalVerificationResult:
    """The result of recomputing a single numerical metric from raw data."""
    metric_name: str
    declared_value: Optional[float]
    recomputed_value: float
    matched: bool
    absolute_delta: float
    tolerance: float
    details: Dict[str, Any] = field(default_factory=dict)


def _canonicalize_payload_dict(obj: Any) -> Any:
    if isinstance(obj, float):
        return f"{obj:.6f}"
    if isinstance(obj, dict):
        return {str(k): _canonicalize_payload_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_canonicalize_payload_dict(x) for x in obj]
    return obj


@dataclass(frozen=True)
class RawDataPackage:
    """Raw, unaggregated experimental observation package."""
    raw_id: str
    source_plane: EvidencePlane
    provider_receipt_id: Optional[str]
    raw_payload: Mapping[str, Any]  # e.g. {"counts": {"0": 512, "1": 512}} or {"samples_ms": [...]}
    captured_at_utc: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def payload_digest(self) -> str:
        clean = _canonicalize_payload_dict(dict(self.raw_payload))
        return canonical_sha256(canonicalize_json(clean))


@dataclass(frozen=True)
class VerifiedEvidencePack:
    """An adjudicated evidence package with recomputed metrics."""
    raw_id: str
    raw_digest: str
    recomputed_metrics: Dict[str, float]
    verification_results: List[NumericalVerificationResult]
    all_matched: bool
    evidence_record: EvidenceRecord
    epistemic_status: EpistemicStatus


class ExternalVerifier:
    """Deterministic Evaluator running outside the agent's write surface."""

    def __init__(self, tolerance: float = DEFAULT_NUMERICAL_TOLERANCE,
                 permit_authority: Optional[PermitAuthority] = None):
        self.tolerance = tolerance
        self._permit_authority = permit_authority

    def batch_values(self, raw_pkg: RawDataPackage) -> List[float]:
        """The observations one raw package contributes to a promotion batch,
        recomputed here rather than taken from the caller."""
        payload = raw_pkg.raw_payload
        if "counts" in payload:
            counts = payload["counts"]
            metric = raw_pkg.metadata.get("metric", "survival_fidelity")
            if metric == "mean_qubit_zero_probability":
                return [self.recompute_mean_qubit_zero_probability(counts)]
            if metric != "survival_fidelity":
                raise EvidenceIntegrityError(f"raw package {raw_pkg.raw_id}: unknown counts metric '{metric}'")
            n_qubits = max((len(k) for k in counts), default=0)
            target = raw_pkg.metadata.get("target_state", "0" * n_qubits)
            return [self.recompute_survival_fidelity(counts, target)]
        if "samples" in payload:
            values = [float(x) for x in payload["samples"]]
            if not values:
                raise EvidenceIntegrityError(f"raw package {raw_pkg.raw_id} has no samples")
            return values
        raise EvidenceIntegrityError(
            f"raw package {raw_pkg.raw_id} has neither 'counts' nor 'samples'; cannot form a promotion batch"
        )

    # -------------------------------------------------------------------------
    # Deterministic Metric Recomputation
    # -------------------------------------------------------------------------
    @staticmethod
    def recompute_bitstring_counts(counts: Mapping[str, int]) -> Dict[str, Any]:
        """Calculates total shots, probabilities, and marginals from bitstring counts."""
        total_shots = sum(counts.values())
        if total_shots <= 0:
            raise EvidenceIntegrityError("Raw counts total must be > 0")

        probs = {k: v / total_shots for k, v in counts.items()}
        # Compute bitstring lengths
        bit_lens = {len(k) for k in counts.keys()}
        n_qubits = max(bit_lens) if bit_lens else 0

        # Marginal single-qubit Z expectations: <Z_i> = P(bit_i == '0') - P(bit_i == '1')
        z_expectations: Dict[int, float] = {}
        for q in range(n_qubits):
            p0 = sum(v for k, v in counts.items() if len(k) > q and k[-(q + 1)] == "0") / total_shots
            p1 = 1.0 - p0
            z_expectations[q] = p0 - p1

        # Parity expectation <P> = sum_{k} (-1)^{popcount(k)} P(k)
        parity = sum(((-1) ** (k.count("1"))) * v for k, v in counts.items()) / total_shots

        return {
            "total_shots": total_shots,
            "probabilities": probs,
            "n_qubits": n_qubits,
            "z_expectations": z_expectations,
            "parity": parity,
        }

    @classmethod
    def recompute_mean_qubit_zero_probability(cls, counts: Mapping[str, int]) -> float:
        """Mean over qubits of P(qubit reads 0); with a final H on every qubit this is
        mean |+> survival (dnalang.metrics.survival_plus)."""
        z = cls.recompute_bitstring_counts(counts)["z_expectations"]
        if not z:
            raise EvidenceIntegrityError("Raw counts have no qubits")
        return float(sum((1.0 + v) / 2.0 for v in z.values()) / len(z))

    @staticmethod
    def recompute_survival_fidelity(counts: Mapping[str, int], target_state: str) -> float:
        """Deterministically computes survival fidelity to a target bitstring state."""
        total_shots = sum(counts.values())
        if total_shots <= 0:
            raise EvidenceIntegrityError("Raw counts total must be > 0")
        target_counts = counts.get(target_state, 0)
        return float(target_counts / total_shots)

    @staticmethod
    def recompute_continuous_samples(samples: Sequence[float]) -> Dict[str, float]:
        """Recomputes summary statistics for benchmark latency or memory samples."""
        if not samples:
            raise EvidenceIntegrityError("Samples sequence cannot be empty")
        s = sorted(float(x) for x in samples)
        n = len(s)
        mean_val = sum(s) / n
        median_val = s[n // 2] if n % 2 != 0 else (s[n // 2 - 1] + s[n // 2]) / 2.0
        p95_idx = min(int(0.95 * n), n - 1)
        p99_idx = min(int(0.99 * n), n - 1)
        variance = sum((x - mean_val) ** 2 for x in s) / (n - 1) if n > 1 else 0.0

        return {
            "n": float(n),
            "mean": float(mean_val),
            "median": float(median_val),
            "min": float(s[0]),
            "max": float(s[-1]),
            "p95": float(s[p95_idx]),
            "p99": float(s[p99_idx]),
            "std": float(math.sqrt(variance)),
        }

    # -------------------------------------------------------------------------
    # Verification and Evidence Sealing
    # -------------------------------------------------------------------------
    def verify_and_seal(
        self,
        raw_pkg: RawDataPackage,
        claimed_metrics: Mapping[str, float],
        claim_id: str,
        subject: str = "Empirical Measurement",
    ) -> VerifiedEvidencePack:
        """Recomputes all metrics from raw data and validates against claimed values.
        
        If any number in claimed_metrics deviates by more than tolerance from
        the recomputed value, all_matched will be False and epistemic status
        will be demoted to REFUTED.
        """
        raw_digest = raw_pkg.payload_digest()
        recomputed: Dict[str, float] = {}

        # 1. Recompute metrics based on payload type
        if "counts" in raw_pkg.raw_payload:
            counts = raw_pkg.raw_payload["counts"]
            res = self.recompute_bitstring_counts(counts)
            recomputed["total_shots"] = float(res["total_shots"])
            recomputed["parity"] = float(res["parity"])
            for q, val in res["z_expectations"].items():
                recomputed[f"z_exp_q{q}"] = float(val)

            target = raw_pkg.metadata.get("target_state", "0" * res["n_qubits"])
            recomputed["survival_fidelity"] = self.recompute_survival_fidelity(counts, target)
            recomputed["mean_qubit_zero_probability"] = self.recompute_mean_qubit_zero_probability(counts)

        if "samples_ms" in raw_pkg.raw_payload:
            stats = self.recompute_continuous_samples(raw_pkg.raw_payload["samples_ms"])
            for k, v in stats.items():
                recomputed[f"latency_{k}"] = v

        if "memory_mb" in raw_pkg.raw_payload:
            stats = self.recompute_continuous_samples(raw_pkg.raw_payload["memory_mb"])
            for k, v in stats.items():
                recomputed[f"memory_{k}"] = v

        # 2. Compare declared/claimed metrics against recomputed values
        verif_results: List[NumericalVerificationResult] = []
        all_matched = True

        for m_name, declared in claimed_metrics.items():
            if m_name not in recomputed:
                # Agent claimed a metric that cannot be derived from raw data
                verif_results.append(
                    NumericalVerificationResult(
                        metric_name=m_name,
                        declared_value=declared,
                        recomputed_value=float("nan"),
                        matched=False,
                        absolute_delta=float("inf"),
                        tolerance=self.tolerance,
                        details={"error": "Metric not derivable from raw data"},
                    )
                )
                all_matched = False
                continue

            recomp_val = recomputed[m_name]
            delta = abs(declared - recomp_val)
            matched = delta <= self.tolerance
            if not matched:
                all_matched = False

            verif_results.append(
                NumericalVerificationResult(
                    metric_name=m_name,
                    declared_value=declared,
                    recomputed_value=recomp_val,
                    matched=matched,
                    absolute_delta=delta,
                    tolerance=self.tolerance,
                    details={},
                )
            )

        # 3. Formulate EvidenceRecord
        now_utc = datetime.now(timezone.utc).isoformat()
        evd_id = f"EVD-{raw_pkg.raw_id}"
        epistemic = EpistemicStatus.MEASURED if all_matched else EpistemicStatus.REFUTED

        manifest_metrics = {
            k: (f"{v:.6f}" if isinstance(v, float) else str(v))
            for k, v in recomputed.items()
        }

        evidence_rec = EvidenceRecord(
            evidence_id=evd_id,
            evidence_class=EvidenceClass.MEASURED,
            domain=EvidenceDomain.E_EXTERNAL,
            claim_ids=[claim_id],
            artifact_digest=raw_digest,
            environment_digest=raw_digest,
            raw_payload_digest=raw_digest,
            captured_at_utc=now_utc,
            evidence_plane=raw_pkg.source_plane,
            immutable=True,
            manifest={
                "raw_id": raw_pkg.raw_id,
                "provider_receipt_id": raw_pkg.provider_receipt_id,
                "recomputed_metrics": manifest_metrics,
                "verification_status": "MATCH" if all_matched else "MISMATCH",
            },
        )

        return VerifiedEvidencePack(
            raw_id=raw_pkg.raw_id,
            raw_digest=raw_digest,
            recomputed_metrics=recomputed,
            verification_results=verif_results,
            all_matched=all_matched,
            evidence_record=evidence_rec,
            epistemic_status=epistemic,
        )

    def record_to_ledger(
        self,
        ledger: DynamicEvidenceLedger,
        verified_pack: VerifiedEvidencePack,
        claim_id: str,
        subject: str,
        statement: str,
    ) -> LedgerEvent:
        """Appends the verified evidence and claim evaluation event into the ledger."""
        actor = {"agent": "osiris.verifier.external", "role": "DETERMINISTIC_EVALUATOR"}
        artifact = {"raw_id": verified_pack.raw_id, "digest": verified_pack.raw_digest}
        scope = ScopeBinding(
            artifact_digest=verified_pack.raw_digest,
            environment_digest=verified_pack.raw_digest,
            time_interval_start=verified_pack.evidence_record.captured_at_utc,
            time_interval_end=verified_pack.evidence_record.captured_at_utc,
            policy_ref="OSIRIS-SPEC-VERIF-015",
            authority_id="osiris.verifier.external",
        )

        canonical_metrics = {
            k: (f"{v:.6f}" if isinstance(v, float) else str(v))
            for k, v in verified_pack.recomputed_metrics.items()
        }

        # 1. Record raw data verification event with authenticated verifier permit
        if self._permit_authority is None:
            raise AuthorityGateError("NO_PERMIT_AUTHORITY: ExternalVerifier needs a PermitAuthority to record verified evidence")
        verifier_permit = self._permit_authority.issue(
            issuer="osiris.verifier.external",
            scope=VERIFICATION_SCOPE,
            target_digest=verified_pack.raw_digest,
        )
        ledger.record_event(
            event_type=LedgerEventType.RAW_DATA_VERIFIED,
            plane=EvidencePlane.SCIENTIFIC_EXPERIMENTAL,
            actor=actor,
            artifact=artifact,
            scope=scope,
            payload={
                "raw_id": verified_pack.raw_id,
                "recomputed_metrics": canonical_metrics,
                "all_matched": verified_pack.all_matched,
            },
            authority_permit=verifier_permit,
        )

        # 2. Record sealed evidence
        ev_event = ledger.record_event(
            event_type=LedgerEventType.EVIDENCE_RECORD_SEALED,
            plane=EvidencePlane.SCIENTIFIC_EXPERIMENTAL,
            actor=actor,
            artifact=artifact,
            scope=scope,
            payload={
                "evidence_id": verified_pack.evidence_record.evidence_id,
                "evidence_record": verified_pack.evidence_record.canonical_bytes().decode("utf-8"),
            },
            evidence_refs=[verified_pack.evidence_record.evidence_id],
        )

        # 3. Assert and evaluate claim
        status = ClaimStatus.TRUE if verified_pack.all_matched else ClaimStatus.FALSE
        violations = [] if verified_pack.all_matched else [ViolationType.UNVERIFIED_NUMERICAL_CLAIM]

        ledger.record_event(
            event_type=LedgerEventType.CLAIM_ASSERTED,
            plane=EvidencePlane.SCIENTIFIC_EXPERIMENTAL,
            actor=actor,
            artifact=artifact,
            scope=scope,
            payload={
                "claim_id": claim_id,
                "subject": subject,
                "statement": statement,
                "claimed_epistemic_status": verified_pack.epistemic_status.value,
            },
            evidence_refs=[verified_pack.evidence_record.evidence_id],
        )

        eval_event = ledger.record_event(
            event_type=LedgerEventType.CLAIM_EVALUATED,
            plane=EvidencePlane.SCIENTIFIC_EXPERIMENTAL,
            actor=actor,
            artifact=artifact,
            scope=scope,
            payload={
                "claim_type": ClaimType.EVIDENCE_INTEGRITY_VERIFIED.value,
                "claim_id": claim_id,
                "subject": subject,
                "status": status.value,
                "violations": [v.value for v in violations],
            },
            evidence_refs=[verified_pack.evidence_record.evidence_id],
        )

        return eval_event


# -----------------------------------------------------------------------------
# Document Claim Scanner (Anti-Hallucination Gate)
# -----------------------------------------------------------------------------

NUMBER_PATTERN = re.compile(r"\b\d+\.\d+(?:e[+-]?\d+)?\b|\b\d+%\b")
EVIDENCE_CITATION_PATTERN = re.compile(r"\[(?:EVD-[A-Za-z0-9_-]+|sha256:[a-f0-9]{64})\]")


@dataclass(frozen=True)
class DocumentAuditFinding:
    line_number: int
    raw_text: str
    detected_number: str
    has_evidence_citation: bool
    citation: Optional[str]
    verified: bool
    reason: str


@dataclass(frozen=True)
class DocumentAuditReport:
    is_valid: bool
    total_findings: int
    unanchored_findings: int
    findings: List[DocumentAuditFinding]


def audit_document_numerical_claims(
    doc_text: str,
    ledger: Optional[DynamicEvidenceLedger] = None,
    allowlist_numbers: Optional[Set[str]] = None,
) -> DocumentAuditReport:
    """Scans text/markdown for numerical claims and ensures they are cited and verifiable.
    
    Prevents Devin Failures 1, 3, 6, 7, 8 (numbers entering text without data provenance).
    """
    allowlist = allowlist_numbers or {"0.0", "1.0", "0%", "100%", "2.0"}  # common syntax constants
    findings: List[DocumentAuditFinding] = []
    lines = doc_text.splitlines()

    for idx, line in enumerate(lines, start=1):
        # Ignore comments or code blocks defining variables
        if line.strip().startswith(("#", "//", "/*", "*", "```", "def ", "class ")):
            continue

        num_matches = NUMBER_PATTERN.findall(line)
        if not num_matches:
            continue

        citations = EVIDENCE_CITATION_PATTERN.findall(line)
        has_citation = len(citations) > 0
        citation = citations[0] if citations else None

        for num in num_matches:
            if num in allowlist:
                continue

            if not has_citation:
                findings.append(
                    DocumentAuditFinding(
                        line_number=idx,
                        raw_text=line.strip(),
                        detected_number=num,
                        has_evidence_citation=False,
                        citation=None,
                        verified=False,
                        reason="Unanchored numerical assertion without [EVD-...] citation",
                    )
                )
            else:
                # If ledger provided, check that citation exists in ledger
                verified = True
                reason = "Anchored to cited evidence"
                if ledger is not None:
                    # Look up evidence in ledger events
                    ev_id = citation.strip("[]")
                    found = False
                    for evt in ledger.events:
                        if ev_id in evt.evidence_refs or evt.artifact.get("digest") == ev_id:
                            found = True
                            break
                    if not found:
                        verified = False
                        reason = f"Citation {citation} not found in ledger"

                findings.append(
                    DocumentAuditFinding(
                        line_number=idx,
                        raw_text=line.strip(),
                        detected_number=num,
                        has_evidence_citation=True,
                        citation=citation,
                        verified=verified,
                        reason=reason,
                    )
                )

    unanchored = sum(1 for f in findings if not f.verified)
    return DocumentAuditReport(
        is_valid=(unanchored == 0),
        total_findings=len(findings),
        unanchored_findings=unanchored,
        findings=findings,
    )
