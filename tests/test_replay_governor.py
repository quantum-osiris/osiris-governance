"""Test suite for ReplayGovernor, ReplayExecutionPermit, and deterministic replay runtime.

Uses Python standard library unittest only (no pytest dependencies or shims).
"""

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path
import sys
import unittest

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


class TestReplayGovernor(unittest.TestCase):
    """Test suite for capability governor, replay invariants, and isolation."""

    def setUp(self):
        self.sample_proposal = ActionProposal.from_dict({
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

    def test_valid_replay_execution_end_to_end(self):
        """Verify end-to-end replay workflow produces deterministic output and hash."""
        governor = ReplayGovernor(policy_version="policy-v1", process_epoch_id="epoch-test-123")
        canon_bytes = canonicalize_json(self.sample_proposal.to_dict())

        permit = governor.issue_replay_permit(
            proposal=self.sample_proposal,
            canonical_bytes=canon_bytes,
            nonce="nonce-001",
            now_utc="2026-09-26T06:00:00Z",
            expires_at_utc="2026-09-26T06:01:00Z",
        )

        self.assertEqual(permit.scope, "REPLAY_ONLY_NON_CRYPTOGRAPHIC")
        self.assertEqual(permit.process_epoch_id, "epoch-test-123")
        self.assertEqual(permit.nonce, "nonce-001")

        result = execute_replay(
            proposal_bytes=canon_bytes,
            permit=permit,
            active_process_epoch_id=governor.process_epoch_id,
            now_utc="2026-09-26T06:00:30Z",
        )

        self.assertEqual(result.status, "REPLAYED")
        self.assertEqual(result.fixture_id, "replay-fixture-v1")
        self.assertEqual(len(result.output_sha256), 64)
        out_dict = result.output_as_dict()
        self.assertEqual(out_dict["replay_status"], "DETERMINISTIC_REPLAY_SUCCESS")
        self.assertEqual(out_dict["fixture_data"]["benchmark_score"], 1.0)

    def test_invariant_1_permit_scope_invalid(self):
        """Verify that any permit with scope != REPLAY_ONLY_NON_CRYPTOGRAPHIC is denied."""
        governor = ReplayGovernor(process_epoch_id="epoch-test-123")
        canon_bytes = canonicalize_json(self.sample_proposal.to_dict())
        valid_permit = governor.issue_replay_permit(
            proposal=self.sample_proposal,
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

        with self.assertRaises(GovernanceViolation) as ctx:
            execute_replay(
                proposal_bytes=canon_bytes,
                permit=tampered_permit,
                active_process_epoch_id=governor.process_epoch_id,
                now_utc="2026-09-26T06:00:30Z",
            )
        self.assertEqual(ctx.exception.code, "PERMIT_SCOPE_INVALID")

    def test_invariant_2_process_epoch_mismatch(self):
        """Verify mechanical restart invalidation when process epoch differs."""
        governor = ReplayGovernor(process_epoch_id="epoch-initial")
        canon_bytes = canonicalize_json(self.sample_proposal.to_dict())
        permit = governor.issue_replay_permit(
            proposal=self.sample_proposal,
            canonical_bytes=canon_bytes,
            nonce="nonce-003",
            now_utc="2026-09-26T06:00:00Z",
            expires_at_utc="2026-09-26T06:01:00Z",
        )

        # Simulated process restart creates new epoch
        restarted_epoch_id = "epoch-restarted-new"

        with self.assertRaises(GovernanceViolation) as ctx:
            execute_replay(
                proposal_bytes=canon_bytes,
                permit=permit,
                active_process_epoch_id=restarted_epoch_id,
                now_utc="2026-09-26T06:00:30Z",
            )
        self.assertEqual(ctx.exception.code, "PERMIT_PROCESS_EPOCH_MISMATCH")

    def test_invariant_3_permit_expiry(self):
        """Verify that execution after permit expiry timestamp is rejected."""
        governor = ReplayGovernor(process_epoch_id="epoch-test-123")
        canon_bytes = canonicalize_json(self.sample_proposal.to_dict())
        permit = governor.issue_replay_permit(
            proposal=self.sample_proposal,
            canonical_bytes=canon_bytes,
            nonce="nonce-004",
            now_utc="2026-09-26T06:00:00Z",
            expires_at_utc="2026-09-26T06:01:00Z",
        )

        # Attempt replay after expiry
        with self.assertRaises(GovernanceViolation) as ctx:
            execute_replay(
                proposal_bytes=canon_bytes,
                permit=permit,
                active_process_epoch_id=governor.process_epoch_id,
                now_utc="2026-09-26T06:01:01Z",
            )
        self.assertEqual(ctx.exception.code, "PERMIT_EXPIRED")

    def test_invariant_4_proposal_binding_mismatch(self):
        """Verify that tampering with proposal bytes after permit issuance is denied."""
        governor = ReplayGovernor(process_epoch_id="epoch-test-123")
        canon_bytes = canonicalize_json(self.sample_proposal.to_dict())
        permit = governor.issue_replay_permit(
            proposal=self.sample_proposal,
            canonical_bytes=canon_bytes,
            nonce="nonce-005",
            now_utc="2026-09-26T06:00:00Z",
            expires_at_utc="2026-09-26T06:01:00Z",
        )

        # Alter proposal bytes
        tampered_dict = self.sample_proposal.to_dict()
        tampered_dict["parameters"] = {"run_mode": "tampered"}
        tampered_bytes = canonicalize_json(tampered_dict)

        with self.assertRaises(GovernanceViolation) as ctx:
            execute_replay(
                proposal_bytes=tampered_bytes,
                permit=permit,
                active_process_epoch_id=governor.process_epoch_id,
                now_utc="2026-09-26T06:00:30Z",
            )
        self.assertEqual(ctx.exception.code, "PROPOSAL_BINDING_MISMATCH")

    def test_invariant_5_canonicalization_version_mismatch(self):
        """Verify rejection if permit specifies incompatible canonicalization version."""
        governor = ReplayGovernor(process_epoch_id="epoch-test-123")
        canon_bytes = canonicalize_json(self.sample_proposal.to_dict())
        valid_permit = governor.issue_replay_permit(
            proposal=self.sample_proposal,
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

        with self.assertRaises(GovernanceViolation) as ctx:
            execute_replay(
                proposal_bytes=canon_bytes,
                permit=tampered_permit,
                active_process_epoch_id=governor.process_epoch_id,
                now_utc="2026-09-26T06:00:30Z",
            )
        self.assertEqual(ctx.exception.code, "CANONICALIZATION_VERSION_MISMATCH")

    def test_nonce_replay_rejected_in_epoch(self):
        """Verify that presenting the same nonce twice within one epoch is denied."""
        governor = ReplayGovernor(process_epoch_id="epoch-test-123")
        canon_bytes = canonicalize_json(self.sample_proposal.to_dict())

        # First issuance with nonce succeeds
        governor.issue_replay_permit(
            proposal=self.sample_proposal,
            canonical_bytes=canon_bytes,
            nonce="unique-nonce-001",
            now_utc="2026-09-26T06:00:00Z",
            expires_at_utc="2026-09-26T06:01:00Z",
        )

        # Second issuance with same nonce fails closed
        with self.assertRaises(GovernanceViolation) as ctx:
            governor.issue_replay_permit(
                proposal=self.sample_proposal,
                canonical_bytes=canon_bytes,
                nonce="unique-nonce-001",
                now_utc="2026-09-26T06:00:10Z",
                expires_at_utc="2026-09-26T06:01:00Z",
            )
        self.assertEqual(ctx.exception.code, "NONCE_ALREADY_CONSUMED")

    def test_unknown_fixture_rejected(self):
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

        with self.assertRaises(ReplayError) as ctx:
            execute_replay(
                proposal_bytes=canon_bytes,
                permit=permit,
                active_process_epoch_id=governor.process_epoch_id,
                now_utc="2026-09-26T06:00:30Z",
            )
        self.assertEqual(ctx.exception.code, "FIXTURE_NOT_FOUND")

    def test_deep_immutability(self):
        """Verify that contracts cannot be mutated after creation."""
        with self.assertRaises(FrozenInstanceError):
            self.sample_proposal.fixture_id = "malicious-fixture"

        governor = ReplayGovernor(process_epoch_id="epoch-test-123")
        canon_bytes = canonicalize_json(self.sample_proposal.to_dict())
        permit = governor.issue_replay_permit(
            proposal=self.sample_proposal,
            canonical_bytes=canon_bytes,
            nonce="nonce-immut",
            now_utc="2026-09-26T06:00:00Z",
            expires_at_utc="2026-09-26T06:01:00Z",
        )

        with self.assertRaises(FrozenInstanceError):
            permit.scope = "MUTATED_SCOPE"

    def test_static_side_effect_and_forbidden_import_audit(self):
        """Verify via AST parsing that production modules import ZERO forbidden side-effect modules."""
        forbidden_modules = {
            "os", "pathlib", "subprocess", "socket", "urllib", "requests", "httpx",
            "google", "boto", "cloud", "secret", "dotenv", "ctypes", "pickle",
            "multiprocessing", "threading", "tempfile", "shutil",
        }

        src_dir = Path(__file__).resolve().parent.parent / "src" / "osiris_governance"
        self.assertTrue(src_dir.is_dir(), f"Source directory {src_dir} not found")

        for py_file in src_dir.glob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root_pkg = alias.name.split(".")[0]
                        self.assertNotIn(
                            root_pkg, forbidden_modules,
                            f"Forbidden import '{alias.name}' in {py_file.name}:{node.lineno}"
                        )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        root_pkg = node.module.split(".")[0]
                        self.assertNotIn(
                            root_pkg, forbidden_modules,
                            f"Forbidden from-import '{node.module}' in {py_file.name}:{node.lineno}"
                        )

    def test_quarantine_isolation(self):
        """Verify that no module in osiris_governance imports or references the quarantined prototype."""
        import osiris_governance

        # Verify package location is NOT inside /home/enki/fold
        pkg_path = Path(osiris_governance.__file__).resolve()
        self.assertNotIn(
            "/home/enki/fold/osiris", str(pkg_path),
            f"Quarantine breach: osiris_governance loaded from {pkg_path}"
        )

        # Check loaded modules in sys.modules
        for mod_name, mod in list(sys.modules.items()):
            if mod and hasattr(mod, "__file__") and mod.__file__:
                mod_file = str(Path(mod.__file__).resolve())
                if mod_name.startswith("osiris_governance"):
                    self.assertNotIn(
                        "/home/enki/fold", mod_file,
                        f"Quarantine violation: {mod_name} resolved from {mod_file}"
                    )


if __name__ == "__main__":
    unittest.main()
