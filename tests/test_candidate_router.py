"""Tests for Stage 4 Constrained Candidate Router and Evaluator Confinement Guard."""

import pytest
from osiris_governance.candidate_router import (
    ConstrainedCandidateRouter,
    EvaluatorConfinementGuard,
    ScreeningResult,
)


def test_confinement_guard_blocks_patch_touching_tests():
    guard = EvaluatorConfinementGuard()
    malicious_patch = (
        "--- tests/reference/test_sparse_matvec.py\n"
        "+++ tests/reference/test_sparse_matvec.py\n"
        "@@ -10,3 +10,4 @@\n"
        "-    assert result == expected\n"
        "+    assert True\n"
    )
    result = guard.audit_patch_paths(malicious_patch)
    assert result.is_admissible is False
    assert result.reason_code == "EVALUATOR_INTEGRITY_COMPROMISED"
    assert "tests/reference/test_sparse_matvec.py" in result.message


def test_confinement_guard_blocks_patch_touching_governance():
    guard = EvaluatorConfinementGuard()
    tampered_patch = (
        "--- src/osiris_governance/stat_gate.py\n"
        "+++ src/osiris_governance/stat_gate.py\n"
        "@@ -50,3 +50,4 @@\n"
        "-    return ci_lower > mde\n"
        "+    return True\n"
    )
    result = guard.audit_patch_paths(tampered_patch)
    assert result.is_admissible is False
    assert result.reason_code == "EVALUATOR_INTEGRITY_COMPROMISED"


def test_confinement_guard_allows_safe_code_patch():
    guard = EvaluatorConfinementGuard()
    safe_patch = (
        "--- src/kernel/sparse_matvec.py\n"
        "+++ src/kernel/sparse_matvec.py\n"
        "@@ -15,3 +15,3 @@\n"
        "-    for i in range(n):\n"
        "+    for i in range(0, n, 2):\n"
    )
    result = guard.audit_patch_paths(safe_patch)
    assert result.is_admissible is True
    assert result.reason_code == "CONFINEMENT_PASSED"


def test_ast_guard_blocks_eval_exec():
    guard = EvaluatorConfinementGuard()
    code_with_eval = "def run():\n    eval('import os; os.system(\"rm -rf /\")')\n"
    result = guard.audit_ast_safety(code_with_eval)
    assert result.is_admissible is False
    assert result.reason_code == "FORBIDDEN_AST_PRIMITIVE"


def test_candidate_router_budget_and_domain_screening():
    def dummy_domain_screener(candidate: dict) -> str | None:
        if candidate.get("parity") != "even":
            return "Odd parity rejected"
        return None

    router = ConstrainedCandidateRouter(budget_limit=2, domain_screener=dummy_domain_screener)

    # 1. Candidate failing domain screener
    res1 = router.screen_and_route({"parity": "odd"}, "cand_1")
    assert res1.is_admissible is False
    assert res1.reason_code == "DOMAIN_SCREEN_REJECTED"
    assert router.evaluations_spent == 0

    # 2. Valid candidate 1
    res2 = router.screen_and_route({"parity": "even"}, "cand_2")
    assert res2.is_admissible is True
    assert res2.reason_code == "ADMITTED_FOR_EVALUATION"
    assert router.evaluations_spent == 1

    # 3. Repeated candidate 1 (cached, free)
    res2_cached = router.screen_and_route({"parity": "even"}, "cand_2")
    assert res2_cached.is_admissible is True
    assert res2_cached.reason_code == "CACHED_CANDIDATE"
    assert router.evaluations_spent == 1

    # 4. Valid candidate 2
    res3 = router.screen_and_route({"parity": "even"}, "cand_3")
    assert res3.is_admissible is True
    assert router.evaluations_spent == 2
    assert router.budget_exhausted is True

    # 5. Candidate 3 attempts evaluation after budget exhausted
    res4 = router.screen_and_route({"parity": "even"}, "cand_4")
    assert res4.is_admissible is False
    assert res4.reason_code == "BUDGET_EXHAUSTED"
