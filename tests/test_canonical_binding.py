"""Test suite for OSIRIS canonical JSON serialization and proposal hash binding."""

import pytest
from osiris_governance.canonical import (
    CANONICALIZATION_VERSION,
    canonicalize_json,
    compute_proposal_sha256,
    parse_canonical_json,
)
from osiris_governance.contracts import ActionKind, ActionProposal, Capability
from osiris_governance.errors import CanonicalizationError


def test_canonical_json_sorting_and_compactness():
    """Verify keys are sorted in code point order with zero extraneous whitespace."""
    payload = {
        "z": 1,
        "a": 2,
        "m": {"k2": "val2", "k1": "val1"},
    }
    raw = canonicalize_json(payload)
    # Expected: {"a":2,"m":{"k1":"val1","k2":"val2"},"z":1}
    assert raw == b'{"a":2,"m":{"k1":"val1","k2":"val2"},"z":1}'


def test_duplicate_key_rejection():
    """Verify that JSON payloads containing duplicate object keys are strictly rejected."""
    raw_with_dups = b'{"capability":"REPLAY","capability":"WRITE_FILE"}'
    with pytest.raises(CanonicalizationError) as exc_info:
        parse_canonical_json(raw_with_dups)
    assert exc_info.value.code == "DUPLICATE_KEY_DETECTED"
    assert "capability" in str(exc_info.value)


def test_unicode_normalization_nfc():
    """Verify Unicode strings are normalized to NFC during canonicalization."""
    # Decomposed: 'e' + combining acute accent (\u0301)
    decomposed = "cafe\u0301"
    # Precomposed: 'é' (\u00e9)
    precomposed = "caf\u00e9"
    assert decomposed != precomposed

    canon_decomp = canonicalize_json({"name": decomposed})
    canon_precomp = canonicalize_json({"name": precomposed})

    # Both must canonicalize to byte-identical representation
    assert canon_decomp == canon_precomp
    assert canon_decomp == b'{"name":"caf\xc3\xa9"}'


def test_nan_infinity_disallowed():
    """Verify NaN and Infinity floats are strictly rejected."""
    with pytest.raises(CanonicalizationError) as exc_info:
        canonicalize_json({"val": float("nan")})
    assert exc_info.value.code == "CANONICALIZATION_FAILED"

    with pytest.raises(CanonicalizationError) as exc_info:
        canonicalize_json({"val": float("inf")})
    assert exc_info.value.code == "CANONICALIZATION_FAILED"


def test_top_level_object_required():
    """Verify top-level JSON entities that are not objects/dicts are rejected."""
    with pytest.raises(CanonicalizationError) as exc_info:
        parse_canonical_json(b'["REPLAY_FIXTURE"]')
    assert exc_info.value.code == "TOP_LEVEL_OBJECT_REQUIRED"


def test_malformed_json_rejected():
    """Verify malformed JSON syntax is rejected with MALFORMED_JSON."""
    with pytest.raises(CanonicalizationError) as exc_info:
        parse_canonical_json(b'{"key": invalid_json}')
    assert exc_info.value.code == "MALFORMED_JSON"


def test_proposal_sha256_tamper_sensitivity():
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

    assert hash_orig != hash_tampered
    assert len(hash_orig) == 64
    assert len(hash_tampered) == 64


def test_action_proposal_contract_roundtrip():
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

    assert restored.proposal_id == proposal.proposal_id
    assert restored.action_kind == ActionKind.REPLAY_FIXTURE
    assert restored.capability == Capability.REPLAY
    assert restored.fixture_id == proposal.fixture_id


if __name__ == "__main__":
    test_canonical_json_sorting_and_compactness()
    test_duplicate_key_rejection()
    test_unicode_normalization_nfc()
    test_nan_infinity_disallowed()
    test_top_level_object_required()
    test_malformed_json_rejected()
    test_proposal_sha256_tamper_sensitivity()
    test_action_proposal_contract_roundtrip()
    print("All canonical binding tests passed.")

