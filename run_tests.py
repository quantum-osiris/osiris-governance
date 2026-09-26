"""Standalone, zero-dependency test runner and review-gate verifier for OSIRIS Governance.

Executes all unit tests, verifies all 5 hard boundary invariants, performs AST static
side-effect analysis, and records exact execution environment metadata.
"""

import ast
from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

# Ensure clean isolated import path
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from osiris_governance.canonical import (
    CANONICALIZATION_VERSION,
    canonicalize_json,
    compute_proposal_sha256,
    parse_canonical_json,
)
from osiris_governance.contracts import (
    ActionKind,
    ActionProposal,
    Capability,
    ReplayExecutionPermit,
    ReplayResult,
)
from osiris_governance.errors import (
    CanonicalizationError,
    GovernanceError,
    GovernanceViolation,
    ReplayError,
)
from osiris_governance.replay import DEFAULT_FIXTURE_REGISTRY, execute_replay
from osiris_governance.replay_governor import ReplayGovernor


class RaisesContext:
    """Context manager emulating pytest.raises for zero-dependency execution."""
    def __init__(self, expected_exc):
        self.expected_exc = expected_exc
        self.value = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            raise AssertionError(f"Expected exception {self.expected_exc.__name__} was not raised")
        if issubclass(exc_type, self.expected_exc):
            self.value = exc_val
            return True
        return False


def raises(expected_exc):
    return RaisesContext(expected_exc)


def run_tests():
    passed = 0
    failed = 0
    test_results = []

    def record_test(name, func):
        nonlocal passed, failed
        t0 = time.perf_counter()
        try:
            func()
            elapsed_ms = (time.perf_counter() - t0) * 1000
            passed += 1
            test_results.append({"name": name, "status": "PASSED", "elapsed_ms": round(elapsed_ms, 3)})
            print(f"  [PASS] {name} ({elapsed_ms:.2f}ms)")
        except Exception as e:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            failed += 1
            test_results.append({"name": name, "status": "FAILED", "error": str(e), "elapsed_ms": round(elapsed_ms, 3)})
            print(f"  [FAIL] {name}: {e}")

    print("\n=== Running Canonical Binding Tests ===")

    def test_canonical_json_sorting_and_compactness():
        payload = {"z": 1, "a": 2, "m": {"k2": "val2", "k1": "val1"}}
        raw = canonicalize_json(payload)
        assert raw == b'{"a":2,"m":{"k1":"val1","k2":"val2"},"z":1}'

    def test_duplicate_key_rejection():
        raw_with_dups = b'{"capability":"REPLAY","capability":"WRITE_FILE"}'
        with raises(CanonicalizationError) as ctx:
            parse_canonical_json(raw_with_dups)
        assert ctx.value.code == "DUPLICATE_KEY_DETECTED"
        assert "capability" in str(ctx.value)

    def test_unicode_normalization_nfc():
        decomposed = "cafe\u0301"
        precomposed = "caf\u00e9"
        canon_decomp = canonicalize_json({"name": decomposed})
        canon_precomp = canonicalize_json({"name": precomposed})
        assert canon_decomp == canon_precomp
        assert canon_decomp == b'{"name":"caf\xc3\xa9"}'

    def test_nan_infinity_disallowed():
        with raises(CanonicalizationError) as ctx1:
            canonicalize_json({"val": float("nan")})
        assert ctx1.value.code == "CANONICALIZATION_FAILED"

        with raises(CanonicalizationError) as ctx2:
            canonicalize_json({"val": float("inf")})
        assert ctx2.value.code == "CANONICALIZATION_FAILED"

    def test_top_level_object_required():
        with raises(CanonicalizationError) as ctx:
            parse_canonical_json(b'["REPLAY_FIXTURE"]')
        assert ctx.value.code == "TOP_LEVEL_OBJECT_REQUIRED"

    def test_malformed_json_rejected():
        with raises(CanonicalizationError) as ctx:
            parse_canonical_json(b'{"key": invalid_json}')
        assert ctx.value.code == "MALFORMED_JSON"

    def test_proposal_sha256_tamper_sensitivity():
        proposal_dict = {
            "format_id": "osiris.action-proposal",
            "format_version": "1.0.0",
            "schema_id": "urn:osiris:schema:action-proposal",
            "schema_version": "1.0.0",
            "proposal_id": "prop-001",
            "action_kind": "REPLAY_FIXTURE",
            "capability": "REPLAY",
            "fixture_id": "replay-fixture-v1",
            "parameters": {"mode": "strict"},
            "created_at_utc": "2026-09-26T06:00:00Z",
        }
        bytes_orig = canonicalize_json(proposal_dict)
        hash_orig = compute_proposal_sha256(bytes_orig)

        tampered_dict = dict(proposal_dict)
        tampered_dict["parameters"] = {"mode": "loose"}
        bytes_tampered = canonicalize_json(tampered_dict)
        hash_tampered = compute_proposal_sha256(bytes_tampered)

        assert hash_orig != hash_tampered
        assert len(hash_orig) == 64
        assert len(hash_tampered) == 64

    def test_action_proposal_contract_roundtrip():
        proposal = ActionProposal.from_dict({
            "format_id": "osiris.action-proposal",
            "format_version": "1.0.0",
            "schema_id": "urn:osiris:schema:action-proposal",
            "schema_version": "1.0.0",
            "proposal_id": "prop-002",
            "action_kind": ActionKind.REPLAY_FIXTURE,
            "capability": Capability.REPLAY,
            "fixture_id": "replay-fixture-v1",
            "parameters": {"param1": 123},
            "created_at_utc": "2026-09-26T06:00:00Z",
        })
        canon_bytes = canonicalize_json(proposal.to_dict())
        parsed_dict = parse_canonical_json(canon_bytes)
        restored = ActionProposal.from_dict(parsed_dict)
        assert restored.proposal_id == proposal.proposal_id
        assert restored.action_kind == ActionKind.REPLAY_FIXTURE
        assert restored.capability == Capability.REPLAY
        assert restored.fixture_id == proposal.fixture_id

    record_test("test_canonical_json_sorting_and_compactness", test_canonical_json_sorting_and_compactness)
    record_test("test_duplicate_key_rejection", test_duplicate_key_rejection)
    record_test("test_unicode_normalization_nfc", test_unicode_normalization_nfc)
    record_test("test_nan_infinity_disallowed", test_nan_infinity_disallowed)
    record_test("test_top_level_object_required", test_top_level_object_required)
    record_test("test_malformed_json_rejected", test_malformed_json_rejected)
    record_test("test_proposal_sha256_tamper_sensitivity", test_proposal_sha256_tamper_sensitivity)
    record_test("test_action_proposal_contract_roundtrip", test_action_proposal_contract_roundtrip)

    print("\n=== Running Replay Governor & Boundary Tests ===")

    sample_proposal = ActionProposal.from_dict({
        "format_id": "osiris.action-proposal",
        "format_version": "1.0.0",
        "schema_id": "urn:osiris:schema:action-proposal",
        "schema_version": "1.0.0",
        "proposal_id": "proposal-test-001",
        "action_kind": ActionKind.REPLAY_FIXTURE,
        "capability": Capability.REPLAY,
        "fixture_id": "replay-fixture-v1",
        "parameters": {"run_mode": "deterministic"},
        "created_at_utc": "2026-09-26T06:00:00Z",
    })

    def test_valid_replay_execution_end_to_end():
        governor = ReplayGovernor(policy_version="policy-v1", process_epoch_id="epoch-test-123")
        canon_bytes = canonicalize_json(sample_proposal.to_dict())
        permit = governor.issue_replay_permit(
            proposal=sample_proposal,
            canonical_bytes=canon_bytes,
            nonce="nonce-001",
            now_utc="2026-09-26T06:00:00Z",
            expires_at_utc="2026-09-26T06:01:00Z",
        )
        assert permit.scope == "REPLAY_ONLY_NON_CRYPTOGRAPHIC"
        assert permit.process_epoch_id == "epoch-test-123"
        assert permit.nonce == "nonce-001"

        result = execute_replay(
            proposal_bytes=canon_bytes,
            permit=permit,
            active_process_epoch_id=governor.process_epoch_id,
            now_utc="2026-09-26T06:00:30Z",
        )
        assert result.status == "REPLAYED"
        assert result.fixture_id == "replay-fixture-v1"
        assert len(result.output_sha256) == 64
        out_dict = result.output_as_dict()
        assert out_dict["replay_status"] == "DETERMINISTIC_REPLAY_SUCCESS"
        assert out_dict["fixture_data"]["benchmark_score"] == 1.0

    def test_invariant_1_permit_scope_invalid():
        governor = ReplayGovernor(process_epoch_id="epoch-test-123")
        canon_bytes = canonicalize_json(sample_proposal.to_dict())
        valid_permit = governor.issue_replay_permit(
            proposal=sample_proposal,
            canonical_bytes=canon_bytes,
            nonce="nonce-002",
            now_utc="2026-09-26T06:00:00Z",
            expires_at_utc="2026-09-26T06:01:00Z",
        )
        tampered_permit = ReplayExecutionPermit(
            proposal_sha256=valid_permit.proposal_sha256,
            canonicalization_version=valid_permit.canonicalization_version,
            policy_version=valid_permit.policy_version,
            fixture_id=valid_permit.fixture_id,
            nonce=valid_permit.nonce,
            process_epoch_id=valid_permit.process_epoch_id,
            issued_at_utc=valid_permit.issued_at_utc,
            expires_at_utc=valid_permit.expires_at_utc,
            scope="EXECUTION_GRANT_EXTERNAL",
            issuer=valid_permit.issuer,
        )
        with raises(GovernanceViolation) as ctx:
            execute_replay(
                proposal_bytes=canon_bytes,
                permit=tampered_permit,
                active_process_epoch_id=governor.process_epoch_id,
                now_utc="2026-09-26T06:00:30Z",
            )
        assert ctx.value.code == "PERMIT_SCOPE_INVALID"

    def test_invariant_2_process_epoch_mismatch():
        governor = ReplayGovernor(process_epoch_id="epoch-initial")
        canon_bytes = canonicalize_json(sample_proposal.to_dict())
        permit = governor.issue_replay_permit(
            proposal=sample_proposal,
            canonical_bytes=canon_bytes,
            nonce="nonce-003",
            now_utc="2026-09-26T06:00:00Z",
            expires_at_utc="2026-09-26T06:01:00Z",
        )
        with raises(GovernanceViolation) as ctx:
            execute_replay(
                proposal_bytes=canon_bytes,
                permit=permit,
                active_process_epoch_id="epoch-restarted-new",
                now_utc="2026-09-26T06:00:30Z",
            )
        assert ctx.value.code == "PERMIT_PROCESS_EPOCH_MISMATCH"

    def test_invariant_3_permit_expiry():
        governor = ReplayGovernor(process_epoch_id="epoch-test-123")
        canon_bytes = canonicalize_json(sample_proposal.to_dict())
        permit = governor.issue_replay_permit(
            proposal=sample_proposal,
            canonical_bytes=canon_bytes,
            nonce="nonce-004",
            now_utc="2026-09-26T06:00:00Z",
            expires_at_utc="2026-09-26T06:01:00Z",
        )
        with raises(GovernanceViolation) as ctx:
            execute_replay(
                proposal_bytes=canon_bytes,
                permit=permit,
                active_process_epoch_id=governor.process_epoch_id,
                now_utc="2026-09-26T06:01:01Z",
            )
        assert ctx.value.code == "PERMIT_EXPIRED"

    def test_invariant_4_proposal_binding_mismatch():
        governor = ReplayGovernor(process_epoch_id="epoch-test-123")
        canon_bytes = canonicalize_json(sample_proposal.to_dict())
        permit = governor.issue_replay_permit(
            proposal=sample_proposal,
            canonical_bytes=canon_bytes,
            nonce="nonce-005",
            now_utc="2026-09-26T06:00:00Z",
            expires_at_utc="2026-09-26T06:01:00Z",
        )
        tampered_dict = sample_proposal.to_dict()
        tampered_dict["parameters"] = {"run_mode": "tampered"}
        tampered_bytes = canonicalize_json(tampered_dict)
        with raises(GovernanceViolation) as ctx:
            execute_replay(
                proposal_bytes=tampered_bytes,
                permit=permit,
                active_process_epoch_id=governor.process_epoch_id,
                now_utc="2026-09-26T06:00:30Z",
            )
        assert ctx.value.code == "PROPOSAL_BINDING_MISMATCH"

    def test_invariant_5_canonicalization_version_mismatch():
        governor = ReplayGovernor(process_epoch_id="epoch-test-123")
        canon_bytes = canonicalize_json(sample_proposal.to_dict())
        valid_permit = governor.issue_replay_permit(
            proposal=sample_proposal,
            canonical_bytes=canon_bytes,
            nonce="nonce-006",
            now_utc="2026-09-26T06:00:00Z",
            expires_at_utc="2026-09-26T06:01:00Z",
        )
        tampered_permit = ReplayExecutionPermit(
            proposal_sha256=valid_permit.proposal_sha256,
            canonicalization_version="UNKNOWN-CANONICAL-V2",
            policy_version=valid_permit.policy_version,
            fixture_id=valid_permit.fixture_id,
            nonce=valid_permit.nonce,
            process_epoch_id=valid_permit.process_epoch_id,
            issued_at_utc=valid_permit.issued_at_utc,
            expires_at_utc=valid_permit.expires_at_utc,
            scope=valid_permit.scope,
            issuer=valid_permit.issuer,
        )
        with raises(GovernanceViolation) as ctx:
            execute_replay(
                proposal_bytes=canon_bytes,
                permit=tampered_permit,
                active_process_epoch_id=governor.process_epoch_id,
                now_utc="2026-09-26T06:00:30Z",
            )
        assert ctx.value.code == "CANONICALIZATION_VERSION_MISMATCH"

    def test_nonce_replay_rejected_in_epoch():
        governor = ReplayGovernor(process_epoch_id="epoch-test-123")
        canon_bytes = canonicalize_json(sample_proposal.to_dict())
        governor.issue_replay_permit(
            proposal=sample_proposal,
            canonical_bytes=canon_bytes,
            nonce="unique-nonce-001",
            now_utc="2026-09-26T06:00:00Z",
            expires_at_utc="2026-09-26T06:01:00Z",
        )
        with raises(GovernanceViolation) as ctx:
            governor.issue_replay_permit(
                proposal=sample_proposal,
                canonical_bytes=canon_bytes,
                nonce="unique-nonce-001",
                now_utc="2026-09-26T06:00:10Z",
                expires_at_utc="2026-09-26T06:01:00Z",
            )
        assert ctx.value.code == "NONCE_ALREADY_CONSUMED"

    def test_unknown_fixture_rejected():
        unknown_proposal = ActionProposal.from_dict({
            "format_id": "osiris.action-proposal",
            "format_version": "1.0.0",
            "schema_id": "urn:osiris:schema:action-proposal",
            "schema_version": "1.0.0",
            "proposal_id": "prop-unknown",
            "action_kind": ActionKind.REPLAY_FIXTURE,
            "capability": Capability.REPLAY,
            "fixture_id": "nonexistent-fixture-id",
            "parameters": {},
            "created_at_utc": "2026-09-26T06:00:00Z",
        })
        governor = ReplayGovernor(process_epoch_id="epoch-test-123")
        canon_bytes = canonicalize_json(unknown_proposal.to_dict())
        permit = governor.issue_replay_permit(
            proposal=unknown_proposal,
            canonical_bytes=canon_bytes,
            nonce="nonce-unknown",
            now_utc="2026-09-26T06:00:00Z",
            expires_at_utc="2026-09-26T06:01:00Z",
        )
        with raises(ReplayError) as ctx:
            execute_replay(
                proposal_bytes=canon_bytes,
                permit=permit,
                active_process_epoch_id=governor.process_epoch_id,
                now_utc="2026-09-26T06:00:30Z",
            )
        assert ctx.value.code == "FIXTURE_NOT_FOUND"

    def test_deep_immutability():
        with raises(FrozenInstanceError):
            sample_proposal.fixture_id = "malicious-fixture"
        governor = ReplayGovernor(process_epoch_id="epoch-test-123")
        canon_bytes = canonicalize_json(sample_proposal.to_dict())
        permit = governor.issue_replay_permit(
            proposal=sample_proposal,
            canonical_bytes=canon_bytes,
            nonce="nonce-immut",
            now_utc="2026-09-26T06:00:00Z",
            expires_at_utc="2026-09-26T06:01:00Z",
        )
        with raises(FrozenInstanceError):
            permit.scope = "MUTATED_SCOPE"

    def test_static_side_effect_and_forbidden_import_audit():
        forbidden_modules = {
            "os", "pathlib", "subprocess", "socket", "urllib", "requests", "httpx",
            "google", "boto", "cloud", "secret", "dotenv", "ctypes", "pickle",
            "multiprocessing", "threading", "tempfile", "shutil",
        }
        src_dir = Path(__file__).resolve().parent / "src" / "osiris_governance"
        assert src_dir.is_dir(), f"Source directory {src_dir} not found"
        for py_file in src_dir.glob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root_pkg = alias.name.split(".")[0]
                        assert root_pkg not in forbidden_modules, (
                            f"Forbidden import '{alias.name}' in {py_file.name}:{node.lineno}"
                        )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        root_pkg = node.module.split(".")[0]
                        assert root_pkg not in forbidden_modules, (
                            f"Forbidden from-import '{node.module}' in {py_file.name}:{node.lineno}"
                        )

    def test_quarantine_isolation():
        import osiris_governance
        pkg_path = str(Path(osiris_governance.__file__).resolve())
        assert "/home/enki/fold/osiris" not in pkg_path, (
            f"Quarantine breach: osiris_governance loaded from {pkg_path}"
        )
        for mod_name, mod in list(sys.modules.items()):
            if mod and hasattr(mod, "__file__") and mod.__file__:
                mod_file = str(Path(mod.__file__).resolve())
                if mod_name.startswith("osiris_governance"):
                    assert "/home/enki/fold" not in mod_file, (
                        f"Quarantine breach: {mod_name} resolved from {mod_file}"
                    )

    record_test("test_valid_replay_execution_end_to_end", test_valid_replay_execution_end_to_end)
    record_test("test_invariant_1_permit_scope_invalid", test_invariant_1_permit_scope_invalid)
    record_test("test_invariant_2_process_epoch_mismatch", test_invariant_2_process_epoch_mismatch)
    record_test("test_invariant_3_permit_expiry", test_invariant_3_permit_expiry)
    record_test("test_invariant_4_proposal_binding_mismatch", test_invariant_4_proposal_binding_mismatch)
    record_test("test_invariant_5_canonicalization_version_mismatch", test_invariant_5_canonicalization_version_mismatch)
    record_test("test_nonce_replay_rejected_in_epoch", test_nonce_replay_rejected_in_epoch)
    record_test("test_unknown_fixture_rejected", test_unknown_fixture_rejected)
    record_test("test_deep_immutability", test_deep_immutability)
    record_test("test_static_side_effect_and_forbidden_import_audit", test_static_side_effect_and_forbidden_import_audit)
    record_test("test_quarantine_isolation", test_quarantine_isolation)

    print(f"\nSummary: {passed} passed, {failed} failed.")

    # Environment capture
    env_info = {
        "python_version": sys.version,
        "platform": platform.platform(),
        "executable": sys.executable,
        "cwd": os.getcwd(),
        "total_tests": passed + failed,
        "passed": passed,
        "failed": failed,
        "test_results": test_results,
    }

    env_bytes = json.dumps(env_info, indent=2).encode("utf-8")
    env_hash = hashlib.sha256(env_bytes).hexdigest()
    env_info["report_sha256"] = env_hash

    report_path = Path(__file__).resolve().parent / "test_report.json"
    report_path.write_text(json.dumps(env_info, indent=2), encoding="utf-8")
    print(f"Test report written to {report_path} (SHA-256: {env_hash})")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
