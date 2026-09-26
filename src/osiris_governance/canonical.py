"""Canonical JSON serialization and binding for OSIRIS Governance.

Implements OSIRIS-CANONICAL-JSON-V1:
- Project-local canonical JSON profile (JCS-inspired code point key sorting)
- Not claimed to be RFC 8785 conformant until conformance vectors pass
- Strict whitespace elimination (separators=(',', ':'))
- Rejection of duplicate object keys
- Disallowance of NaN, Infinity, -Infinity
- Unicode NFC normalization
- Strict UTF-8 encoding
- Deterministic unkeyed SHA-256 digest generation
"""

import hashlib
import json
import unicodedata
from typing import Any

from .errors import CanonicalizationError

CANONICALIZATION_VERSION = "OSIRIS-CANONICAL-JSON-V1"


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Parse hook that raises CanonicalizationError if duplicate keys are encountered."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalizationError(
                "DUPLICATE_KEY_DETECTED",
                f"Duplicate object key '{key}' detected in JSON payload",
            )
        result[key] = value
    return result


def canonicalize_json(data: Any) -> bytes:
    """Serialize a Python data structure into deterministic canonical JSON bytes.

    Raises CanonicalizationError if data contains non-serializable objects or invalid floats.
    """
    try:
        # Step 1: Serialize with sorted keys and minimal separators
        raw_str = json.dumps(
            data,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        # Step 2: Unicode normalization (NFC)
        normalized_str = unicodedata.normalize("NFC", raw_str)
        return normalized_str.encode("utf-8")
    except (TypeError, ValueError) as err:
        raise CanonicalizationError(
            "CANONICALIZATION_FAILED",
            f"Failed to canonicalize payload: {err}",
        ) from err


def parse_canonical_json(raw_bytes: bytes) -> dict[str, Any]:
    """Strictly parse raw UTF-8 JSON bytes, rejecting duplicate keys and non-conforming formats."""
    if not isinstance(raw_bytes, (bytes, bytearray)):
        raise CanonicalizationError(
            "INVALID_INPUT_TYPE",
            "Expected bytes or bytearray for canonical JSON input",
        )
    try:
        decoded = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as err:
        raise CanonicalizationError(
            "INVALID_UTF8_ENCODING",
            f"Payload is not valid UTF-8: {err}",
        ) from err

    try:
        parsed = json.loads(decoded, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as err:
        raise CanonicalizationError(
            "MALFORMED_JSON",
            f"Failed to parse JSON: {err}",
        ) from err

    if not isinstance(parsed, dict):
        raise CanonicalizationError(
            "TOP_LEVEL_OBJECT_REQUIRED",
            f"Top-level JSON entity must be an object/dict, got {type(parsed).__name__}",
        )
    return parsed


def compute_proposal_sha256(canonical_bytes: bytes) -> str:
    """Compute the unkeyed SHA-256 digest of canonical proposal bytes."""
    if not isinstance(canonical_bytes, (bytes, bytearray)):
        raise CanonicalizationError(
            "INVALID_INPUT_TYPE",
            "Expected bytes for hash computation",
        )
    return hashlib.sha256(canonical_bytes).hexdigest()
