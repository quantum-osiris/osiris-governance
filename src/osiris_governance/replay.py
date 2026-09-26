"""Deterministic replay execution engine for OSIRIS Governance.

Executes side-effect-free replay against in-process fixture registry.
Enforces the 5 hard boundary invariants:
1. Permit scope check (PERMIT_SCOPE_INVALID)
2. Process epoch match (PERMIT_PROCESS_EPOCH_MISMATCH)
3. Expiry check (PERMIT_EXPIRED)
4. Canonical proposal byte binding (PROPOSAL_BINDING_MISMATCH)
5. Canonicalization version check (CANONICALIZATION_VERSION_MISMATCH)
"""

from typing import Any, Mapping

from .canonical import (
    CANONICALIZATION_VERSION,
    canonicalize_json,
    compute_proposal_sha256,
    parse_canonical_json,
)
from .contracts import ReplayExecutionPermit, ReplayInvocation, ReplayResult, _freeze_val
from .errors import GovernanceViolation, ReplayError

# Fixed in-memory fixture registry. Zero disk or network access.
DEFAULT_FIXTURE_REGISTRY: Mapping[str, Mapping[str, Any]] = {
    "replay-fixture-v1": {
        "status": "DETERMINISTIC_REPLAY_SUCCESS",
        "benchmark_score": 1.0,
        "sample_counts": {"00": 512, "11": 512},
        "description": "Baseline Bell-state test fixture for side-effect-free verification",
    },
    "telemetry-fixture-v1": {
        "status": "TELEMETRY_RECORD_VERIFIED",
        "tick": 42,
        "readout_fidelity": 0.998,
        "description": "Observational telemetry record for replay validation",
    },
    "benchmark-fixture-v1": {
        "status": "BENCHMARK_COMPLETED",
        "eval_metrics": {"loss": 0.0012, "accuracy": 0.999},
        "description": "Synthetic benchmark fixture for compiler lowering proof",
    },
}


def prepare_replay(
    proposal_bytes: bytes,
    permit: ReplayExecutionPermit,
    active_process_epoch_id: str,
    now_utc: str,
) -> ReplayInvocation:
    """Validate all boundary invariants and package a minimal ReplayInvocation.

    Carries strictly:
    - fixture_id
    - canonical_proposal_bytes
    - nonce
    - process_epoch_id

    Carries zero filesystem paths, zero subprocess commands, zero network specs,
    zero cloud tokens, and zero callables.

    Raises GovernanceViolation if any invariant check fails.
    """
    # Invariant 1: Permit scope check
    if permit.scope != "REPLAY_ONLY_NON_CRYPTOGRAPHIC":
        raise GovernanceViolation(
            "PERMIT_SCOPE_INVALID",
            f"Permit scope '{permit.scope}' is not valid for replay execution",
        )

    # Invariant 2: Process epoch check (mechanical restart invalidation)
    if permit.process_epoch_id != active_process_epoch_id:
        raise GovernanceViolation(
            "PERMIT_PROCESS_EPOCH_MISMATCH",
            f"Permit epoch '{permit.process_epoch_id}' does not match active epoch '{active_process_epoch_id}'",
        )

    # Invariant 3: Expiry window check
    if now_utc > permit.expires_at_utc:
        raise GovernanceViolation(
            "PERMIT_EXPIRED",
            f"Permit expired at '{permit.expires_at_utc}', current time is '{now_utc}'",
        )

    # Invariant 4: Exact canonical proposal byte binding
    computed_proposal_hash = compute_proposal_sha256(proposal_bytes)
    if computed_proposal_hash != permit.proposal_sha256:
        raise GovernanceViolation(
            "PROPOSAL_BINDING_MISMATCH",
            f"Proposal hash '{computed_proposal_hash}' does not match permit binding '{permit.proposal_sha256}'",
        )

    # Invariant 5: Canonicalization version check
    if permit.canonicalization_version != CANONICALIZATION_VERSION:
        raise GovernanceViolation(
            "CANONICALIZATION_VERSION_MISMATCH",
            f"Permit canonicalization version '{permit.canonicalization_version}' != '{CANONICALIZATION_VERSION}'",
        )

    # Parse and validate proposal content fixture ID match
    parsed_proposal = parse_canonical_json(proposal_bytes)
    proposal_fixture_id = str(parsed_proposal.get("fixture_id", ""))
    if proposal_fixture_id != permit.fixture_id:
        raise GovernanceViolation(
            "FIXTURE_ID_MISMATCH",
            f"Proposal fixture_id '{proposal_fixture_id}' != permit fixture_id '{permit.fixture_id}'",
        )

    return ReplayInvocation(
        fixture_id=permit.fixture_id,
        canonical_proposal_bytes=proposal_bytes,
        nonce=permit.nonce,
        process_epoch_id=active_process_epoch_id,
    )


def execute_replay(
    proposal_bytes: bytes | ReplayInvocation,
    permit: ReplayExecutionPermit | None = None,
    active_process_epoch_id: str | None = None,
    now_utc: str | None = None,
    fixture_registry: Mapping[str, Mapping[str, Any]] | None = None,
) -> ReplayResult:
    """Execute deterministic fixture replay under strict permit governance.

    Accepts either:
    1. A pre-validated ReplayInvocation (as first positional argument) and optional now_utc
    2. (proposal_bytes, permit, active_process_epoch_id, now_utc)

    Returns:
        ReplayResult with deterministic normalized output and byte digest.

    Raises:
        GovernanceViolation: If any boundary invariant fails.
        ReplayError: If the fixture does not exist in registry.
    """
    if isinstance(proposal_bytes, ReplayInvocation):
        invocation = proposal_bytes
        ts_now = now_utc or ""
    else:
        if permit is None or active_process_epoch_id is None or now_utc is None:
            raise ValueError(
                "permit, active_process_epoch_id, and now_utc are required when passing raw proposal_bytes"
            )
        invocation = prepare_replay(
            proposal_bytes=proposal_bytes,
            permit=permit,
            active_process_epoch_id=active_process_epoch_id,
            now_utc=now_utc,
        )
        ts_now = now_utc


    # Lookup fixture in memory
    registry = fixture_registry if fixture_registry is not None else DEFAULT_FIXTURE_REGISTRY
    if invocation.fixture_id not in registry:
        raise ReplayError(
            "FIXTURE_NOT_FOUND",
            f"Fixture '{invocation.fixture_id}' not found in in-memory registry",
        )

    fixture_data = registry[invocation.fixture_id]
    parsed_proposal = parse_canonical_json(invocation.canonical_proposal_bytes)

    # Deterministic normalization of output
    normalized_dict = {
        "fixture_id": invocation.fixture_id,
        "fixture_data": dict(fixture_data),
        "requested_parameters": parsed_proposal.get("parameters", {}),
        "replay_status": "DETERMINISTIC_REPLAY_SUCCESS",
    }

    # Compute deterministic output hash
    output_bytes = canonicalize_json(normalized_dict)
    output_sha256 = compute_proposal_sha256(output_bytes)

    return ReplayResult(
        status="REPLAYED",
        fixture_id=invocation.fixture_id,
        normalized_output=_freeze_val(normalized_dict),
        output_sha256=output_sha256,
        replayed_at_utc=ts_now,
    )

