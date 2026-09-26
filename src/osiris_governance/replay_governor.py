"""Local capability governor for issuing replay-only execution permits.

Enforces zero-authority replay admission:
- Requires exact ActionKind.REPLAY_FIXTURE and Capability.REPLAY
- Verifies canonical proposal hash binding
- Prevents nonce reuse within the active process epoch
- Generates process-local ReplayExecutionPermit with strict epoch binding
"""

import uuid
from typing import Set

from .canonical import CANONICALIZATION_VERSION, compute_proposal_sha256
from .contracts import ActionKind, ActionProposal, Capability, ReplayExecutionPermit
from .errors import GovernanceViolation


class ReplayGovernor:
    """Local, in-process capability governor for replay operations."""

    def __init__(
        self,
        policy_version: str = "governance-policy-v1",
        process_epoch_id: str | None = None,
    ) -> None:
        self._policy_version = policy_version
        self._process_epoch_id = process_epoch_id or f"epoch-{uuid.uuid4().hex[:16]}"
        self._consumed_nonces: Set[str] = set()

    @property
    def process_epoch_id(self) -> str:
        """The active process epoch ID. Changes mechanically on process restart."""
        return self._process_epoch_id

    @property
    def policy_version(self) -> str:
        """The active policy version."""
        return self._policy_version

    def issue_replay_permit(
        self,
        proposal: ActionProposal,
        canonical_bytes: bytes,
        nonce: str,
        now_utc: str,
        expires_at_utc: str,
    ) -> ReplayExecutionPermit:
        """Evaluate a proposal and issue a bounded, non-cryptographic replay permit."""
        # Check 1: Action kind invariant
        if proposal.action_kind != ActionKind.REPLAY_FIXTURE:
            raise GovernanceViolation(
                "ACTION_KIND_NOT_PERMITTED",
                f"Expected REPLAY_FIXTURE, got {proposal.action_kind}",
            )

        # Check 2: Capability invariant
        if proposal.capability != Capability.REPLAY:
            raise GovernanceViolation(
                "CAPABILITY_NOT_PERMITTED",
                f"Expected REPLAY capability, got {proposal.capability}",
            )

        # Check 3: Canonical byte binding
        computed_sha256 = compute_proposal_sha256(canonical_bytes)

        # Check 4: Anti-replay nonce freshness within process epoch
        if nonce in self._consumed_nonces:
            raise GovernanceViolation(
                "NONCE_ALREADY_CONSUMED",
                f"Nonce '{nonce}' has already been consumed in epoch '{self._process_epoch_id}'",
            )
        self._consumed_nonces.add(nonce)

        # Check 5: Timestamp validation
        if now_utc > expires_at_utc:
            raise GovernanceViolation(
                "INVALID_EXPIRY_WINDOW",
                f"Expiry timestamp '{expires_at_utc}' cannot precede issued timestamp '{now_utc}'",
            )

        return ReplayExecutionPermit(
            proposal_sha256=computed_sha256,
            canonicalization_version=CANONICALIZATION_VERSION,
            policy_version=self._policy_version,
            fixture_id=proposal.fixture_id,
            nonce=nonce,
            process_epoch_id=self._process_epoch_id,
            issued_at_utc=now_utc,
            expires_at_utc=expires_at_utc,
            scope="REPLAY_ONLY_NON_CRYPTOGRAPHIC",
            issuer="local-replay-governor",
        )
