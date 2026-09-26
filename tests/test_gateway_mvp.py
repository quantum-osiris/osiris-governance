"""
Unit and Mutation Tests for OSIRIS Replay Gateway MVP
=====================================================

Covers:
1. Positive tests (Canonicalization, Decision, Replay, Result Verification, Evidence Chain)
2. Negative tests (Schema, Float rejection, Path/URL rejection, Secret key rejection, Tampering)
3. Mutation tests (Detecting 8 intentional control weakenings)
"""

import json
import os
import unittest
from pathlib import Path

from osiris_governance.gateway import (
    DEFAULT_ADAPTER_ID,
    DEFAULT_POLICY_REVISION,
    PolicyConfig,
    ReplayGateway,
    ReplayPermit,
    ReplayRequest,
    _validate_types_and_reject_floats,
)
from osiris_governance.errors import GovernanceViolation


class TestGatewayPositive(unittest.TestCase):
    def setUp(self):
        self.gw = ReplayGateway()
        self.valid_req_dict = {
            "schema_version": "1.0",
            "request_id": "req-example-001",
            "workload_type": "replay_fixture_v1",
            "fixture_id": "echo-normalized-input-v1",
            "input": {
                "message": "hello"
            },
            "provenance_required": True,
            "idempotency_key": "example-unique-key-1"
        }

    def test_canonical_reproducibility(self):
        req1 = ReplayRequest.from_dict(self.valid_req_dict)
        req2 = ReplayRequest.from_dict(self.valid_req_dict)
        self.assertEqual(req1.compute_digest(), req2.compute_digest())
        self.assertEqual(req1.to_canonical_bytes(), req2.to_canonical_bytes())

    def test_allow_replay_decision(self):
        req = ReplayRequest.from_dict(self.valid_req_dict)
        decision, permit, reason = self.gw.decide(req)
        self.assertEqual(decision, "ALLOW_REPLAY")
        self.assertIsNotNone(permit)
        self.assertEqual(permit.fixture_id, "echo-normalized-input-v1")
        self.assertEqual(permit.execution_mode, "REPLAY_ONLY")
        self.assertFalse(permit.side_effects_allowed)

    def test_fixture_execution_and_result_verification(self):
        req = ReplayRequest.from_dict(self.valid_req_dict)
        decision, permit, _ = self.gw.decide(req)
        exec_res = self.gw.execute_adapter(permit, req)
        self.assertFalse(exec_res["side_effects_observed"])
        self.assertEqual(exec_res["output"]["status"], "ECHOED")
        self.assertEqual(exec_res["output"]["echo"], "hello")

        verified = self.gw.verify_result(req, permit, exec_res)
        self.assertTrue(verified)

    def test_evidence_record_and_replay_match(self):
        req = ReplayRequest.from_dict(self.valid_req_dict)
        decision, permit, reason = self.gw.decide(req)
        exec_res = self.gw.execute_adapter(permit, req)
        record = self.gw.seal_evidence_record(req, decision, reason, permit, exec_res)

        self.assertIn("record_digest", record["integrity"])
        self.assertTrue(record["integrity"]["record_digest"].startswith("sha256:"))

        # Replay should match
        matched, msg = self.gw.replay_record(record, req)
        self.assertTrue(matched)
        self.assertEqual(msg, "REPLAY_MATCH")

    def test_hash_chain_linking(self):
        req1 = ReplayRequest.from_dict(self.valid_req_dict)
        d1, p1, r1 = self.gw.decide(req1)
        res1 = self.gw.execute_adapter(p1, req1)
        rec1 = self.gw.seal_evidence_record(req1, d1, r1, p1, res1)

        req2_dict = dict(self.valid_req_dict)
        req2_dict["request_id"] = "req-example-002"
        req2_dict["idempotency_key"] = "example-unique-key-2"
        req2 = ReplayRequest.from_dict(req2_dict)
        d2, p2, r2 = self.gw.decide(req2)
        res2 = self.gw.execute_adapter(p2, req2)
        rec2 = self.gw.seal_evidence_record(
            req2, d2, r2, p2, res2,
            previous_record_digest=rec1["integrity"]["record_digest"]
        )

        self.assertEqual(rec2["integrity"]["previous_record_digest"], rec1["integrity"]["record_digest"])


class TestGatewayNegative(unittest.TestCase):
    def setUp(self):
        self.gw = ReplayGateway()
        self.base_dict = {
            "schema_version": "1.0",
            "request_id": "req-test-neg",
            "workload_type": "replay_fixture_v1",
            "fixture_id": "echo-normalized-input-v1",
            "input": {"message": "hello"},
            "provenance_required": True,
            "idempotency_key": "key-neg-1"
        }

    def test_reject_floating_point(self):
        bad = dict(self.base_dict)
        bad["input"] = {"message": "test", "num": 3.14159}
        with self.assertRaises(ValueError) as ctx:
            ReplayRequest.from_dict(bad)
        self.assertIn("Floating-point values are rejected", str(ctx.exception))

    def test_reject_unknown_field(self):
        bad = dict(self.base_dict)
        bad["unknown_field"] = "malicious"
        with self.assertRaises(ValueError) as ctx:
            ReplayRequest.from_dict(bad)
        self.assertIn("Unknown fields in request", str(ctx.exception))

    def test_reject_missing_field(self):
        bad = dict(self.base_dict)
        del bad["provenance_required"]
        with self.assertRaises(ValueError) as ctx:
            ReplayRequest.from_dict(bad)
        self.assertIn("Missing required fields", str(ctx.exception))

    def test_reject_url(self):
        bad = dict(self.base_dict)
        bad["input"] = {"target": "https://attacker.com/leak"}
        with self.assertRaises(ValueError) as ctx:
            ReplayRequest.from_dict(bad)
        self.assertIn("URLs are strictly forbidden", str(ctx.exception))

    def test_reject_filepath(self):
        bad = dict(self.base_dict)
        bad["input"] = {"target": "/etc/passwd"}
        with self.assertRaises(ValueError) as ctx:
            ReplayRequest.from_dict(bad)
        self.assertIn("Filesystem paths are strictly forbidden", str(ctx.exception))

    def test_reject_secret_key_names(self):
        bad = dict(self.base_dict)
        bad["input"] = {"api_key": "secret123"}
        with self.assertRaises(ValueError) as ctx:
            ReplayRequest.from_dict(bad)
        self.assertIn("Forbidden key name", str(ctx.exception))

    def test_deny_unsupported_workload(self):
        bad = dict(self.base_dict)
        bad["workload_type"] = "arbitrary_execution"
        req = ReplayRequest.from_dict(bad)
        decision, permit, reason = self.gw.decide(req)
        self.assertEqual(decision, "DENY_UNSUPPORTED_WORKLOAD")
        self.assertIsNone(permit)

    def test_deny_unknown_fixture(self):
        bad = dict(self.base_dict)
        bad["fixture_id"] = "unknown_quantum_job"
        req = ReplayRequest.from_dict(bad)
        decision, permit, reason = self.gw.decide(req)
        self.assertEqual(decision, "DENY_UNKNOWN_FIXTURE")
        self.assertIsNone(permit)

    def test_deny_policy_mismatch(self):
        req = ReplayRequest.from_dict(self.base_dict)
        decision, permit, reason = self.gw.decide(req, requested_policy_rev="policy-9.9.9")
        self.assertEqual(decision, "DENY_POLICY_MISMATCH")
        self.assertIsNone(permit)

    def test_post_approval_tampering_fails_replay(self):
        req = ReplayRequest.from_dict(self.base_dict)
        decision, permit, reason = self.gw.decide(req)
        exec_res = self.gw.execute_adapter(permit, req)
        record = self.gw.seal_evidence_record(req, decision, reason, permit, exec_res)

        # Mutate request slightly
        tampered_dict = dict(self.base_dict)
        tampered_dict["input"] = {"message": "tampered"}
        tampered_req = ReplayRequest.from_dict(tampered_dict)

        matched, msg = self.gw.replay_record(record, tampered_req)
        self.assertFalse(matched)
        self.assertIn("Request digest mismatch", msg)


class TestGatewayMutationDetection(unittest.TestCase):
    """Verifies that intentional control weakenings are caught by the test harness."""

    def setUp(self):
        self.gw = ReplayGateway()
        self.base_dict = {
            "schema_version": "1.0",
            "request_id": "req-mutation-001",
            "workload_type": "replay_fixture_v1",
            "fixture_id": "echo-normalized-input-v1",
            "input": {"message": "hello"},
            "provenance_required": True,
            "idempotency_key": "mut-key"
        }

    def test_mutation_01_unknown_workload_caught(self):
        """M-01: Weakening default deny to allow unknown workloads must be detected."""
        d = dict(self.base_dict)
        d["workload_type"] = "unauthorized_workload"
        req = ReplayRequest.from_dict(d)
        decision, _, _ = self.gw.decide(req)
        self.assertEqual(decision, "DENY_UNSUPPORTED_WORKLOAD")

    def test_mutation_02_unknown_fixture_caught(self):
        """M-02: Skipping fixture allowlist check must be detected."""
        d = dict(self.base_dict)
        d["fixture_id"] = "unregistered_fixture"
        req = ReplayRequest.from_dict(d)
        decision, _, _ = self.gw.decide(req)
        self.assertEqual(decision, "DENY_UNKNOWN_FIXTURE")

    def test_mutation_03_tampered_request_digest_caught(self):
        """M-03: Ignoring request digest binding in adapter must be detected."""
        req = ReplayRequest.from_dict(self.base_dict)
        _, permit, _ = self.gw.decide(req)
        # Create a mutated permit with wrong digest
        bad_permit = ReplayPermit(
            permit_version=permit.permit_version,
            permit_id=permit.permit_id,
            request_digest="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            fixture_id=permit.fixture_id,
            policy_revision=permit.policy_revision,
            execution_mode=permit.execution_mode,
            adapter_id=permit.adapter_id,
            not_before_epoch=permit.not_before_epoch,
            not_after_epoch=permit.not_after_epoch,
            side_effects_allowed=permit.side_effects_allowed,
        )
        with self.assertRaises(GovernanceViolation):
            self.gw.execute_adapter(bad_permit, req)

    def test_mutation_04_policy_revision_mismatch_caught(self):
        """M-04: Ignoring policy revision mismatch must be detected."""
        req = ReplayRequest.from_dict(self.base_dict)
        decision, _, _ = self.gw.decide(req, requested_policy_rev="tampered-policy-0.0.0")
        self.assertEqual(decision, "DENY_POLICY_MISMATCH")

    def test_mutation_05_side_effects_caught(self):
        """M-05: Allowing side-effects must fail adapter verification."""
        req = ReplayRequest.from_dict(self.base_dict)
        _, permit, _ = self.gw.decide(req)
        bad_permit = ReplayPermit(
            permit_version=permit.permit_version,
            permit_id=permit.permit_id,
            request_digest=permit.request_digest,
            fixture_id=permit.fixture_id,
            policy_revision=permit.policy_revision,
            execution_mode=permit.execution_mode,
            adapter_id=permit.adapter_id,
            not_before_epoch=permit.not_before_epoch,
            not_after_epoch=permit.not_after_epoch,
            side_effects_allowed=True,
        )
        with self.assertRaises(GovernanceViolation):
            self.gw.execute_adapter(bad_permit, req)

    def test_mutation_06_unverified_result_caught(self):
        """M-06: Altering execution output must fail result verification."""
        req = ReplayRequest.from_dict(self.base_dict)
        _, permit, _ = self.gw.decide(req)
        exec_res = self.gw.execute_adapter(permit, req)
        # Tamper output without recomputing result_digest
        exec_res["output"]["status"] = "TAMPERED"
        verified = self.gw.verify_result(req, permit, exec_res)
        self.assertFalse(verified)

    def test_mutation_07_float_leak_caught(self):
        """M-07: Allowing floating point values must be caught."""
        d = dict(self.base_dict)
        d["input"] = {"leak": 0.001}
        with self.assertRaises(ValueError):
            ReplayRequest.from_dict(d)

    def test_mutation_08_provenance_bypass_caught(self):
        """M-08: Omitting provenance requirement must be denied."""
        d = dict(self.base_dict)
        d["provenance_required"] = False
        req = ReplayRequest.from_dict(d)
        decision, _, _ = self.gw.decide(req)
        self.assertEqual(decision, "DENY")


if __name__ == "__main__":
    unittest.main()
