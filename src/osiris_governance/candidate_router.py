"""Constrained Candidate Router and Evaluator Confinement Guard.

Enforces:
1. Evaluator Confinement (Anti-Reward Hacking / METR & DGM findings):
   Candidates have ZERO write authority over evaluator harnesses, test suites,
   scoring scripts, and ledgers. Any patch attempting to touch forbidden paths
   or AST nodes is immediately rejected with EVALUATOR_INTEGRITY_COMPROMISED.
2. Pre-Evaluation Semantic Screening:
   Filters out malformed candidates before consuming simulation or hardware budget.
3. Strict Budget Accounting:
   Monitors unique evaluations across search algorithms (GA, XCS organism, BO).
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .canonical import canonical_sha256, canonicalize_json
from .errors import GovernanceViolation


PROTECTED_PATH_PATTERNS = (
    "tests/",
    "test_",
    "verifier",
    "evaluator",
    "ledger",
    "governance",
    "confinement",
    "baseline_artifact.json",
    "scoring",
    "stat_gate",
)

FORBIDDEN_AST_CALLS = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "system",
    "popen",
    "spawn",
}


@dataclass(frozen=True)
class ScreeningResult:
    """Outcome of pre-evaluation candidate screening."""
    candidate_id: str
    is_admissible: bool
    reason_code: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


class EvaluatorConfinementGuard:
    """Protects evaluation harnesses from agent tampering."""

    def __init__(
        self,
        protected_prefixes: Sequence[str] = PROTECTED_PATH_PATTERNS,
        forbidden_calls: Set[str] = FORBIDDEN_AST_CALLS,
    ):
        self.protected_prefixes = tuple(protected_prefixes)
        self.forbidden_calls = forbidden_calls

    def audit_patch_paths(self, patch_diff: str, candidate_id: str = "PATCH-PROPOSAL") -> ScreeningResult:
        """Inspects diff headers to verify candidate does not modify protected evaluator files."""
        touched_files: List[str] = []
        for line in patch_diff.splitlines():
            if line.startswith("--- ") or line.startswith("+++ "):
                # Extract filename
                parts = line.split(maxsplit=1)
                if len(parts) == 2:
                    clean_path = parts[1].strip().lstrip("ab/").split("\t")[0]
                    if clean_path != "/dev/null":
                        touched_files.append(clean_path)

        for filepath in touched_files:
            for pattern in self.protected_prefixes:
                if pattern in filepath:
                    return ScreeningResult(
                        candidate_id=candidate_id,
                        is_admissible=False,
                        reason_code="EVALUATOR_INTEGRITY_COMPROMISED",
                        message=(
                            f"Evaluator confinement breach: Candidate patch attempts to modify "
                            f"protected evaluation path '{filepath}' matching pattern '{pattern}'."
                        ),
                        details={"touched_file": filepath, "matched_pattern": pattern},
                    )

        return ScreeningResult(
            candidate_id=candidate_id,
            is_admissible=True,
            reason_code="CONFINEMENT_PASSED",
            message="Patch adheres to evaluator confinement boundaries.",
            details={"touched_files": touched_files},
        )

    def audit_ast_safety(self, python_source: str, candidate_id: str = "CODE-CANDIDATE") -> ScreeningResult:
        """Inspects candidate Python AST to prevent runtime sandbox breakout calls."""
        try:
            tree = ast.parse(python_source)
        except SyntaxError as e:
            return ScreeningResult(
                candidate_id=candidate_id,
                is_admissible=False,
                reason_code="SYNTAX_ERROR",
                message=f"Candidate code contains invalid syntax: {e}",
            )

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                func_name = None
                if isinstance(func, ast.Name):
                    func_name = func.id
                elif isinstance(func, ast.Attribute):
                    func_name = func.attr

                if func_name and func_name in self.forbidden_calls:
                    return ScreeningResult(
                        candidate_id=candidate_id,
                        is_admissible=False,
                        reason_code="FORBIDDEN_AST_PRIMITIVE",
                        message=f"Forbidden breakout call '{func_name}' detected in candidate AST.",
                        details={"forbidden_node": func_name},
                    )

        return ScreeningResult(
            candidate_id=candidate_id,
            is_admissible=True,
            reason_code="AST_SAFETY_PASSED",
            message="AST conforms to safe generation subset.",
        )


class ConstrainedCandidateRouter:
    """Manages candidate screening and unique evaluation budget allocation."""

    def __init__(
        self,
        budget_limit: int,
        confinement_guard: Optional[EvaluatorConfinementGuard] = None,
        domain_screener: Optional[Callable[[Any], Optional[str]]] = None,
    ):
        self.budget_limit = budget_limit
        self.confinement_guard = confinement_guard or EvaluatorConfinementGuard()
        self.domain_screener = domain_screener
        self._evaluated_keys: Set[str] = set()
        self._rejections_count: int = 0

    @property
    def evaluations_spent(self) -> int:
        return len(self._evaluated_keys)

    @property
    def budget_exhausted(self) -> bool:
        return len(self._evaluated_keys) >= self.budget_limit

    @property
    def rejections_count(self) -> int:
        return self._rejections_count

    def screen_and_route(
        self,
        candidate_proposal: Any,
        candidate_key: str,
        patch_diff: Optional[str] = None,
        source_code: Optional[str] = None,
    ) -> ScreeningResult:
        """Runs multi-layer screening: patch confinement -> AST safety -> domain screener -> budget."""
        # 1. Confinement check on patch diff
        if patch_diff is not None:
            patch_audit = self.confinement_guard.audit_patch_paths(patch_diff)
            if not patch_audit.is_admissible:
                self._rejections_count += 1
                return patch_audit

        # 2. AST safety check on source code
        if source_code is not None:
            ast_audit = self.confinement_guard.audit_ast_safety(source_code, candidate_id=candidate_key)
            if not ast_audit.is_admissible:
                self._rejections_count += 1
                return ast_audit

        # 3. Domain screening (e.g. DD parity / structural screen)
        if self.domain_screener is not None:
            domain_err = self.domain_screener(candidate_proposal)
            if domain_err is not None:
                self._rejections_count += 1
                return ScreeningResult(
                    candidate_id=candidate_key,
                    is_admissible=False,
                    reason_code="DOMAIN_SCREEN_REJECTED",
                    message=f"Candidate failed domain screening: {domain_err}",
                )

        # 4. Check evaluation budget (cached items cost 0 unique budget)
        if candidate_key in self._evaluated_keys:
            return ScreeningResult(
                candidate_id=candidate_key,
                is_admissible=True,
                reason_code="CACHED_CANDIDATE",
                message="Candidate already evaluated; free cache lookup.",
                details={"unique_budget_consumed": False},
            )

        if self.budget_exhausted:
            return ScreeningResult(
                candidate_id=candidate_key,
                is_admissible=False,
                reason_code="BUDGET_EXHAUSTED",
                message=f"Evaluation budget limit ({self.budget_limit}) reached. Further proposals blocked.",
                details={"budget_limit": self.budget_limit},
            )

        # Mark candidate as admitted for evaluation
        self._evaluated_keys.add(candidate_key)
        return ScreeningResult(
            candidate_id=candidate_key,
            is_admissible=True,
            reason_code="ADMITTED_FOR_EVALUATION",
            message="Candidate passed all pre-flight gates and is admitted for execution.",
            details={"evals_spent": len(self._evaluated_keys), "budget_limit": self.budget_limit},
        )
