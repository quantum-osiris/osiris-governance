"""Core contracts and immutable data structures for OSIRIS Governance.

Defines the side-effect-free replay proof data model:
- ActionKind: REPLAY_FIXTURE only
- Capability: REPLAY only
- ActionProposal: Frozen envelope specification
- ReplayExecutionPermit: Process-local non-authoritative permit
- ReplayResult: Deterministic normalized replay output
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ActionKind(str, Enum):
    """Permitted action kinds. The replay-only core admits only REPLAY_FIXTURE."""
    REPLAY_FIXTURE = "REPLAY_FIXTURE"


class Capability(str, Enum):
    """Permitted capabilities. The replay-only core admits only REPLAY."""
    REPLAY = "REPLAY"


def _freeze_val(val: Any) -> Any:
    """Recursively freeze mapping and sequence structures into immutable tuples."""
    if isinstance(val, dict):
        return tuple(sorted((k, _freeze_val(v)) for k, v in val.items()))
    if isinstance(val, (list, tuple)):
        return tuple(_freeze_val(v) for v in val)
    if isinstance(val, (int, float, str, bool)) or val is None:
        return val
    raise TypeError(f"Unsupported non-primitive value in immutable contract: {type(val).__name__}")


def _unfreeze_val(val: Any) -> Any:
    """Recursively unfreeze tuples representing dictionaries back to standard dicts."""
    if isinstance(val, tuple):
        # Check if it looks like an associative mapping of (str, Any) pairs
        if val and all(isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str) for item in val):
            return {k: _unfreeze_val(v) for k, v in val}
        return [_unfreeze_val(v) for v in val]
    return val


@dataclass(frozen=True)
class ActionProposal:
    """Immutable, typed proposal requesting fixture replay.

    Contains zero filesystem paths, zero subprocess commands, zero network specs.
    """
    format_id: str
    format_version: str
    schema_id: str
    schema_version: str
    proposal_id: str
    action_kind: ActionKind
    capability: Capability
    fixture_id: str
    parameters: tuple[tuple[str, Any], ...]
    created_at_utc: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionProposal":
        """Construct a validated ActionProposal from dictionary."""
        return cls(
            format_id=str(data["format_id"]),
            format_version=str(data["format_version"]),
            schema_id=str(data["schema_id"]),
            schema_version=str(data["schema_version"]),
            proposal_id=str(data["proposal_id"]),
            action_kind=ActionKind(data["action_kind"]),
            capability=Capability(data["capability"]),
            fixture_id=str(data["fixture_id"]),
            parameters=_freeze_val(data.get("parameters", {})),
            created_at_utc=str(data["created_at_utc"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to standard dictionary for canonical serialization."""
        return {
            "format_id": self.format_id,
            "format_version": self.format_version,
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "proposal_id": self.proposal_id,
            "action_kind": self.action_kind.value,
            "capability": self.capability.value,
            "fixture_id": self.fixture_id,
            "parameters": _unfreeze_val(self.parameters),
            "created_at_utc": self.created_at_utc,
        }


@dataclass(frozen=True)
class ReplayExecutionPermit:
    """Non-authoritative, process-local execution permit.

    Valid ONLY inside the active replay process.
    Not a digital signature, not a cloud credential, not an external-execution grant.
    Expires on process restart or expiry timestamp.
    """
    proposal_sha256: str
    canonicalization_version: str
    policy_version: str
    fixture_id: str
    nonce: str
    process_epoch_id: str
    issued_at_utc: str
    expires_at_utc: str

    scope: str = "REPLAY_ONLY_NON_CRYPTOGRAPHIC"
    issuer: str = "local-replay-governor"


@dataclass(frozen=True)
class ReplayResult:
    """Deterministic result of a replay execution."""
    status: str
    fixture_id: str
    normalized_output: tuple[tuple[str, Any], ...]
    output_sha256: str
    replayed_at_utc: str

    def output_as_dict(self) -> dict[str, Any]:
        """Convert normalized output to dictionary."""
        return _unfreeze_val(self.normalized_output)
