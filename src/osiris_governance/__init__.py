"""OSIRIS Governance Replay-Only Core Package.

This package implements the minimal side-effect-free replay proof:
- Exact proposal canonicalization (OSIRIS-CANONICAL-JSON-V1)
- Non-authoritative process-local ReplayExecutionPermit
- In-memory fixture registry lookup
- Hard runtime boundary checks

Explicitly excluded:
- Filesystem paths, symlinks, traversal logic
- Subprocess, shell, socket, network access
- Cloud dispatch, providers, credentials, cost budgets
- Execution grants and cryptographic signatures
"""

__version__ = "0.1.0"
__all__ = [
    "ActionKind",
    "Capability",
    "ActionProposal",
    "ReplayExecutionPermit",
    "ReplayResult",
    "GovernanceError",
    "GovernanceViolation",
    "CanonicalizationError",
    "ReplayError",
]

from .contracts import (
    ActionKind,
    Capability,
    ActionProposal,
    ReplayExecutionPermit,
    ReplayResult,
)
from .errors import (
    GovernanceError,
    GovernanceViolation,
    CanonicalizationError,
    ReplayError,
)
