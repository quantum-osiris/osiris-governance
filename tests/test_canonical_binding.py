"""Test suite for OSIRIS canonical JSON serialization and proposal hash binding.

Uses Python standard library unittest only (no pytest dependencies or shims).
"""

import unittest

from osiris_governance.canonical import (
    CANONICALIZATION_VERSION,
    canonicalize_json,
    compute_proposal_sha256,
    parse_canonical_json,
)
from osiris_governance.contracts import ActionKind, ActionProposal, Capability
from osiris_governance.errors import CanonicalizationError


class TestCanonicalBinding(unittest.TestCase):
    """Test suite for OSIRIS-CANONICAL-JSON-V1 serialization profile and proposal hash binding."""

    def test_canonical_json_sorting_and_compactness(self):
        """Verify keys are sorted in code point order with zero extraneous whitespace."""
        payload = {
            "z": 1,
            "a": 2,
            "m": {"k2": "val2", "k1": "val1"},
        }
        raw = canonicalize_json(payload)
        self.assertEqual(raw, b'{"a":2,"m":{"k1":"val1","k2":"val2"},"z":1}')

    def test_duplicate_key_rejection(self):
        """Verify that JSON payloads containing duplicate object keys are strictly rejected."""
        raw_with_dups = b'{"capability":"REPLAY","capability":"WRITE_FILE"}'
        with self.assertRaises(CanonicalizationError) as ctx:
            parse_canonical_json(raw_with_dups)
        self.assertEqual(ctx.exception.code, "DUPLICATE_KEY_DETECTED")
        self.assertIn("capability", str(ctx.exception))

    def test_unicode_normalization_nfc(self):
        """Verify Unicode strings are normalized to NFC during canonicalization."""
        # Decomposed: 'e' + combining acute accent (\u0301)
        decomposed = "cafe\u0301"
        # Precomposed: 'é' (\u00e9)
        precomposed = "caf\u00e9"
        self.assertNotEqual(decomposed, precomposed)

        canon_decomp = canonicalize_json({"name": decomposed})
        canon_precomp = canonicalize_json({"name": precomposed})

        # Both must canonicalize to byte-identical representation
        self.assertEqual(canon_decomp, canon_precomp)
        self.assertEqual(canon_decomp, b'{"name":"caf\xc3\xa9"}')

    def test_nan_infinity_disallowed(self):
        """Verify NaN and Infinity floats are strictly rejected."""
        with self.assertRaises(CanonicalizationError) as ctx1:
            canonicalize_json({"val": float("nan")})
        self.assertEqual(ctx1.exception.code, "CANONICALIZATION_FAILED")

        with self.assertRaises(CanonicalizationError) as ctx2:
            canonicalize_json({"val": float("inf")})
        self.assertEqual(ctx2.exception.code, "CANONICALIZATION_FAILED")

    def test_top_level_object_required(self):
        """Verify top-level JSON entities that are not objects/dicts are rejected."""
        with self.assertRaises(CanonicalizationError) as ctx:
            parse_canonical_json(b'["REPLAY_FIXTURE"]')
        self.assertEqual(ctx.exception.code, "TOP_LEVEL_OBJECT_REQUIRED")

    def test_malformed_json_rejected(self):
        """Verify malformed JSON syntax is rejected with MALFORMED_JSON."""
        with self.assertRaises(CanonicalizationError) as ctx:
            parse_canonical_json(b'{"key": invalid_json}')
        self.assertEqual(ctx.exception.code, "MALFORMED_JSON")

    def test_proposal_sha256_tamper_sensitivity(self):
        """Verify that altering a single character in a proposal changes the SHA-256 digest."""
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

        # Tamper with 1 parameter
        tampered_dict = dict(proposal_dict)
        tampered_dict["parameters"] = {"mode": "loose"}
        bytes_tampered = canonicalize_json(tampered_dict)
        hash_tampered = compute_proposal_sha256(bytes_tampered)

        self.assertNotEqual(hash_orig, hash_tampered)
        self.assertEqual(len(hash_orig), 64)
        self.assertEqual(len(hash_tampered), 64)

    def test_action_proposal_contract_roundtrip(self):
        """Verify ActionProposal serialization, hash binding, and deserialization."""
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

        self.assertEqual(restored.proposal_id, proposal.proposal_id)
        self.assertEqual(restored.action_kind, ActionKind.REPLAY_FIXTURE)
        self.assertEqual(restored.capability, Capability.REPLAY)
        self.assertEqual(restored.fixture_id, proposal.fixture_id)

    def test_non_ascii_identifier_rejection(self):
        """Verify that authority-bearing identifiers strictly reject non-ASCII Unicode strings."""
        base_dict = {
            "format_id": "osiris.action-proposal",
            "format_version": "1.0.0",
            "schema_id": "urn:osiris:schema:action-proposal",
            "schema_version": "1.0.0",
            "proposal_id": "prop-001",
            "action_kind": "REPLAY_FIXTURE",
            "capability": "REPLAY",
            "fixture_id": "replay-fixture-v1",
            "parameters": {"param1": 123},
            "created_at_utc": "2026-09-26T06:00:00Z",
        }

        # 1. Non-ASCII proposal_id must be rejected
        tampered_id = dict(base_dict)
        tampered_id["proposal_id"] = "prop-\u00e9"
        with self.assertRaises(CanonicalizationError) as ctx:
            ActionProposal.from_dict(tampered_id)
        self.assertEqual(ctx.exception.code, "NON_ASCII_IDENTIFIER")

        # 2. Non-ASCII fixture_id must be rejected
        tampered_fixture = dict(base_dict)
        tampered_fixture["fixture_id"] = "fixture-\u03c0"
        with self.assertRaises(CanonicalizationError) as ctx:
            ActionProposal.from_dict(tampered_fixture)
        self.assertEqual(ctx.exception.code, "NON_ASCII_IDENTIFIER")


if __name__ == "__main__":
    unittest.main()

