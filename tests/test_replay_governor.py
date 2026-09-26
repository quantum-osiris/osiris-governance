"""Test suite for ReplayGovernor, ReplayExecutionPermit, and deterministic replay runtime."""

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path
import sys
import pytest

from osiris_governance.canonical import (
    CANONICALIZATION_VERSION,
    canonicalize_json,
    compute_proposal_sha256,
)
from osiris_governance.contracts import (
    ActionKind,
    ActionProposal,
    Capability,
    ReplayExecutionPermit,
)
from osiris_governance.errors import GovernanceViolation, ReplayError
from osiris_governance.replay import execute_replay
from osiris_governance.replay_governor import ReplayGovernor


@pytest.fixture
def sample_proposal() -> ActionProposal:
    """Fixture returning a valid ActionProposal."""
    return ActionProposal.from_dict({
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


def test_valid_replay_execution_end_to_end(sample_proposal):
    """Verify end-to-end replay workflow produces deterministic output and hash."""
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


def test_invariant_1_permit_scope_invalid(sample_proposal):
    """Verify that any permit with scope != REPLAY_ONLY_NON_CRYPTOGRAPHIC is denied."""
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
        scope="EXECUTION_GRANT_EXTERNAL",  # INVALID SCOPE
        issuer=valid_permit.issuer,
    )

    with pytest.raises(GovernanceViolation) as exc_info:
        execute_replay(
            proposal_bytes=canon_bytes,
            permit=tampered_permit,
            active_process_epoch_id=governor.process_epoch_id,
            now_utc="2026-09-26T06:00:30Z",
        )
    assert exc_info.value.code == "PERMIT_SCOPE_INVALID"


def test_invariant_2_process_epoch_mismatch(sample_proposal):
    """Verify mechanical restart invalidation when process epoch differs."""
    governor = ReplayGovernor(process_epoch_id="epoch-initial")
    canon_bytes = canonicalize_json(sample_proposal.to_dict())
    permit = governor.issue_replay_permit(
        proposal=sample_proposal,
        canonical_bytes=canon_bytes,
        nonce="nonce-003",
        now_utc="2026-09-26T06:00:00Z",
        expires_at_utc="2026-09-26T06:01:00Z",
    )

    # Simulated process restart creates new epoch
    restarted_epoch_id = "epoch-restarted-new"

    with pytest.raises(GovernanceViolation) as exc_info:
        execute_replay(
            proposal_bytes=canon_bytes,
            permit=permit,
            active_process_epoch_id=restarted_epoch_id,
            now_utc="2026-09-26T06:00:30Z",
        )
    assert exc_info.value.code == "PERMIT_PROCESS_EPOCH_MISMATCH"


def test_invariant_3_permit_expiry(sample_proposal):
    """Verify that execution after permit expiry timestamp is rejected."""
    governor = ReplayGovernor(process_epoch_id="epoch-test-123")
    canon_bytes = canonicalize_json(sample_proposal.to_dict())
    permit = governor.issue_replay_permit(
        proposal=sample_proposal,
        canonical_bytes=canon_bytes,
        nonce="nonce-004",
        now_utc="2026-09-26T06:00:00Z",
        expires_at_utc="2026-09-26T06:01:00Z",
    )

    # Attempt replay after expiry
    with pytest.raises(GovernanceViolation) as exc_info:
        execute_replay(
            proposal_bytes=canon_bytes,
            permit=permit,
            active_process_epoch_id=governor.process_epoch_id,
            now_utc="2026-09-26T06:01:01Z",
        )
    assert exc_info.value.code == "PERMIT_EXPIRED"


def test_invariant_4_proposal_binding_mismatch(sample_proposal):
    """Verify that tampering with proposal bytes after permit issuance is denied."""
    governor = ReplayGovernor(process_epoch_id="epoch-test-123")
    canon_bytes = canonicalize_json(sample_proposal.to_dict())
    permit = governor.issue_replay_permit(
        proposal=sample_proposal,
        canonical_bytes=canon_bytes,
        nonce="nonce-005",
        now_utc="2026-09-26T06:00:00Z",
        expires_at_utc="2026-09-26T06:01:00Z",
    )

    # Alter proposal bytes
    tampered_dict = sample_proposal.to_dict()
    tampered_dict["parameters"] = {"run_mode": "tampered"}
    tampered_bytes = canonicalize_json(tampered_dict)

    with pytest.raises(GovernanceViolation) as exc_info:
        execute_replay(
            proposal_bytes=tampered_bytes,
            permit=permit,
            active_process_epoch_id=governor.process_epoch_id,
            now_utc="2026-09-26T06:00:30Z",
        )
    assert exc_info.value.code == "PROPOSAL_BINDING_MISMATCH"


def test_invariant_5_canonicalization_version_mismatch(sample_proposal):
    """Verify rejection if permit specifies incompatible canonicalization version."""
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

    with pytest.raises(GovernanceViolation) as exc_info:
        execute_replay(
            proposal_bytes=canon_bytes,
            permit=tampered_permit,
            active_process_epoch_id=governor.process_epoch_id,
            now_utc="2026-09-26T06:00:30Z",
        )
    assert exc_info.value.code == "CANONICALIZATION_VERSION_MISMATCH"


def test_nonce_replay_rejected_in_epoch(sample_proposal):
    """Verify that presenting the same nonce twice within one epoch is denied."""
    governor = ReplayGovernor(process_epoch_id="epoch-test-123")
    canon_bytes = canonicalize_json(sample_proposal.to_dict())

    # First issuance with nonce succeeds
    governor.issue_replay_permit(
        proposal=sample_proposal,
        canonical_bytes=canon_bytes,
        nonce="unique-nonce-001",
        now_utc="2026-09-26T06:00:00Z",
        expires_at_utc="2026-09-26T06:01:00Z",
    )

    # Second issuance with same nonce fails closed
    with pytest.raises(GovernanceViolation) as exc_info:
        governor.issue_replay_permit(
            proposal=sample_proposal,
            canonical_bytes=canon_bytes,
            nonce="unique-nonce-001",
            now_utc="2026-09-26T06:00:10Z",
            expires_at_utc="2026-09-26T06:01:00Z",
        )
    assert exc_info.value.code == "NONCE_ALREADY_CONSUMED"


def test_unknown_fixture_rejected(sample_proposal):
    """Verify that requesting an unmapped fixture ID fails closed."""
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

    with pytest.raises(ReplayError) as exc_info:
        execute_replay(
            proposal_bytes=canon_bytes,
            permit=permit,
            active_process_epoch_id=governor.process_epoch_id,
            now_utc="2026-09-26T06:00:30Z",
        )
    assert exc_info.value.code == "FIXTURE_NOT_FOUND"


def test_deep_immutability(sample_proposal):
    """Verify that contracts cannot be mutated after creation."""
    with pytest.raises(FrozenInstanceError):
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

    with pytest.raises(FrozenInstanceError):
        permit.scope = "MUTATED_SCOPE"


def test_static_side_effect_and_forbidden_import_audit():
    """Verify via AST parsing that production modules import ZERO forbidden side-effect modules."""
    forbidden_modules = {
        "os", "pathlib", "subprocess", "socket", "urllib", "requests", "httpx",
        "google", "boto", "cloud", "secret", "dotenv", "ctypes", "pickle",
        "multiprocessing", "threading", "tempfile", "shutil",
    }

    src_dir = Path(__file__).resolve().parent.parent / "src" / "osiris_governance"
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
    """Verify that no module in osiris_governance imports or references the quarantined prototype."""
    import osiris_governance

    # Verify package location is NOT inside /home/enki/fold
    pkg_path = Path(osiris_governance.__file__).resolve()
    assert "/home/enki/fold/osiris" not in str(pkg_path), (
        f"Quarantine breach: osiris_governance loaded from {pkg_path}"
    )

    # Check loaded modules in sys.modules
    for mod_name, mod in list(sys.modules.items()):
        if mod and hasattr(mod, "__file__") and mod.__file__:
            mod_file = str(Path(mod.__file__).resolve())
            if mod_name.startswith("osiris_governance"):
                assert "/home/enki/fold" not in mod_file, (
                    f"Quarantine violation: {mod_name} resolved from {mod_file}"
                )


if __name__ == "__main__":
    p = ActionProposal.from_dict({
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
    test_valid_replay_execution_end_to_end(p)
    test_invariant_1_permit_scope_invalid(p)
    test_invariant_2_process_epoch_mismatch(p)
    test_invariant_3_permit_expiry(p)
    test_invariant_4_proposal_binding_mismatch(p)
    test_invariant_5_canonicalization_version_mismatch(p)
    test_nonce_replay_rejected_in_epoch(p)
    test_unknown_fixture_rejected(p)
    test_deep_immutability(p)
    test_static_side_effect_and_forbidden_import_audit()
    test_quarantine_isolation()
    print("All replay governor tests passed.")

