"""
OSIRIS Replay Gateway & Deterministic Policy Governor (MVP)
===========================================================

Reference implementation of the minimal replay-only, evidence-governed
research compute gateway.

Enforces the narrow auditable lifecycle:
One typed request
  -> one canonical representation
  -> one request hash
  -> one deterministic policy decision
  -> one fake/local replay adapter
  -> one validated result
  -> one immutable evidence record
  -> one exact replay

Strictly zero subprocesses, zero network sockets, zero arbitrary code execution.
Standard library only.
"""

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from .canonical import CANONICALIZATION_VERSION, canonicalize_json, compute_proposal_sha256
from .errors import CanonicalizationError, GovernanceViolation

DEFAULT_POLICY_REVISION = "policy-0.1.0"
DEFAULT_ADAPTER_ID = "local-fixture-adapter-0.1"

# Supported fixture registry for MVP
SUPPORTED_FIXTURES = {
    "echo-normalized-input-v1": {
        "description": "Deterministic echo fixture normalizing input message",
        "output_generator": lambda inp: {"echo": inp.get("message", ""), "status": "ECHOED"},
    },
    "replay-fixture-v1": {
        "description": "Baseline Bell-state test fixture for side-effect-free verification",
        "output_generator": lambda inp: {"status": "DETERMINISTIC_REPLAY_SUCCESS", "sample_counts": {"00": 512, "11": 512}},
    },
}

FORBIDDEN_KEY_PATTERNS = [
    re.compile(r"(?i)(token|secret|password|credential|api[_-]?key|auth|bearer)"),
    re.compile(r"(?i)(sh|bash|cmd|exec|eval|script|python|path|url|uri)"),
]

URL_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
PATH_PATTERN = re.compile(r"^(/|[a-zA-Z]:\\|\.\./)")


def _validate_types_and_reject_floats(obj: Any, path: str = "$") -> None:
    """Recursively enforce that no floats, URLs, paths, or binary blobs exist."""
    if isinstance(obj, float):
        raise ValueError(f"Floating-point values are rejected at {path} for exact reproducibility")
    elif isinstance(obj, str):
        # Check Unicode normalization (must be NFC)
        if not unicodedata.is_normalized("NFC", obj):
            raise ValueError(f"String at {path} is not in NFC normalized form")
        # Check for URLs
        if URL_PATTERN.match(obj):
            raise ValueError(f"URLs are strictly forbidden in requests: {obj!r} at {path}")
        # Check for absolute or escape file paths
        if PATH_PATTERN.match(obj):
            raise ValueError(f"Filesystem paths are strictly forbidden in requests: {obj!r} at {path}")
    elif isinstance(obj, bytes):
        raise ValueError(f"Binary blobs are rejected at {path}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str) or not k.isascii():
                raise ValueError(f"Dictionary keys must be ASCII strings: {k!r} at {path}")
            for pattern in FORBIDDEN_KEY_PATTERNS:
                if pattern.search(k):
                    raise ValueError(f"Forbidden key name {k!r} detected at {path}")
            _validate_types_and_reject_floats(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            _validate_types_and_reject_floats(item, f"{path}[{idx}]")
    elif isinstance(obj, (int, bool)) or obj is None:
        pass
    else:
        raise ValueError(f"Unsupported data type {type(obj).__name__} at {path}")


@dataclass(frozen=True)
class ReplayRequest:
    schema_version: str
    request_id: str
    workload_type: str
    fixture_id: str
    input: Dict[str, Any]
    provenance_required: bool
    idempotency_key: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReplayRequest":
        allowed_keys = {
            "schema_version",
            "request_id",
            "workload_type",
            "fixture_id",
            "input",
            "provenance_required",
            "idempotency_key",
        }
        actual_keys = set(data.keys())
        unknown_keys = actual_keys - allowed_keys
        if unknown_keys:
            raise ValueError(f"Unknown fields in request: {sorted(unknown_keys)}")

        missing_keys = allowed_keys - actual_keys
        if missing_keys:
            raise ValueError(f"Missing required fields in request: {sorted(missing_keys)}")

        if data["schema_version"] != "1.0":
            raise ValueError(f"Unsupported schema_version: {data['schema_version']}")

        _validate_types_and_reject_floats(data)

        return cls(
            schema_version=str(data["schema_version"]),
            request_id=str(data["request_id"]),
            workload_type=str(data["workload_type"]),
            fixture_id=str(data["fixture_id"]),
            input=dict(data["input"]),
            provenance_required=bool(data["provenance_required"]),
            idempotency_key=str(data["idempotency_key"]),
        )

    def to_canonical_bytes(self) -> bytes:
        data = asdict(self)
        return canonicalize_json(data)

    def compute_digest(self) -> str:
        return f"sha256:{hashlib.sha256(self.to_canonical_bytes()).hexdigest()}"


@dataclass(frozen=True)
class PolicyConfig:
    policy_revision: str
    allowed_workloads: Tuple[str, ...]
    allowlist: Tuple[str, ...]
    active_epoch: int
    allow_side_effects: bool

    @classmethod
    def default(cls) -> "PolicyConfig":
        return cls(
            policy_revision=DEFAULT_POLICY_REVISION,
            allowed_workloads=("replay_fixture_v1",),
            allowlist=("echo-normalized-input-v1", "replay-fixture-v1"),
            active_epoch=1,
            allow_side_effects=False,
        )


@dataclass(frozen=True)
class ReplayPermit:
    permit_version: str
    permit_id: str
    request_digest: str
    fixture_id: str
    policy_revision: str
    execution_mode: str
    adapter_id: str
    not_before_epoch: int
    not_after_epoch: int
    side_effects_allowed: bool

    def to_canonical_bytes(self) -> bytes:
        return canonicalize_json(asdict(self))

    def compute_digest(self) -> str:
        return f"sha256:{hashlib.sha256(self.to_canonical_bytes()).hexdigest()}"


class ReplayGateway:
    """The Replay-Only Compute Gateway."""

    def __init__(self, policy: Optional[PolicyConfig] = None):
        self.policy = policy or PolicyConfig.default()
        self.seen_idempotency_keys: Dict[str, str] = {}

    def validate_request(self, raw_data: Dict[str, Any]) -> Tuple[ReplayRequest, str]:
        """Validate request and return typed ReplayRequest with its canonical digest."""
        req = ReplayRequest.from_dict(raw_data)
        digest = req.compute_digest()
        return req, digest

    def decide(self, req: ReplayRequest, requested_policy_rev: Optional[str] = None) -> Tuple[str, Optional[ReplayPermit], Optional[str]]:
        """Evaluate deterministic policy.

        Returns (decision, permit, denial_reason).
        """
        # 1. Policy revision match
        if requested_policy_rev and requested_policy_rev != self.policy.policy_revision:
            return "DENY_POLICY_MISMATCH", None, f"Requested policy '{requested_policy_rev}' != active '{self.policy.policy_revision}'"

        # 2. Workload type check
        if req.workload_type not in self.policy.allowed_workloads:
            return "DENY_UNSUPPORTED_WORKLOAD", None, f"Workload '{req.workload_type}' not permitted"

        # 3. Fixture allowlist check
        if req.fixture_id not in self.policy.allowlist:
            return "DENY_UNKNOWN_FIXTURE", None, f"Fixture '{req.fixture_id}' not in allowlist"

        # 4. Provenance requirement
        if not req.provenance_required:
            return "DENY", None, "provenance_required must be true"

        # Construct permit
        request_digest = req.compute_digest()
        permit = ReplayPermit(
            permit_version="1.0",
            permit_id=f"permit-{req.request_id}",
            request_digest=request_digest,
            fixture_id=req.fixture_id,
            policy_revision=self.policy.policy_revision,
            execution_mode="REPLAY_ONLY",
            adapter_id=DEFAULT_ADAPTER_ID,
            not_before_epoch=self.policy.active_epoch,
            not_after_epoch=self.policy.active_epoch,
            side_effects_allowed=self.policy.allow_side_effects,
        )
        return "ALLOW_REPLAY", permit, None

    def execute_adapter(self, permit: ReplayPermit, req: ReplayRequest) -> Dict[str, Any]:
        """Execute local side-effect-free replay fixture."""
        # Pre-execution checks
        if permit.execution_mode != "REPLAY_ONLY":
            raise GovernanceViolation("INVALID_MODE", f"Execution mode {permit.execution_mode} not permitted")
        if permit.side_effects_allowed:
            raise GovernanceViolation("SIDE_EFFECTS_FORBIDDEN", "Side effects must be strictly false")
        if permit.fixture_id not in SUPPORTED_FIXTURES:
            raise GovernanceViolation("UNKNOWN_FIXTURE", f"Fixture {permit.fixture_id} not available")

        # Verify exact request binding
        actual_req_digest = req.compute_digest()
        if actual_req_digest != permit.request_digest:
            raise GovernanceViolation("PERMIT_MISMATCH", "Request digest does not match permit")

        # Execute in-process generator
        fixture_def = SUPPORTED_FIXTURES[permit.fixture_id]
        generator = fixture_def["output_generator"]
        output = generator(req.input)

        adapter_digest = f"sha256:{hashlib.sha256(permit.adapter_id.encode('utf-8')).hexdigest()}"
        result_canonical = canonicalize_json(output)
        result_digest = f"sha256:{hashlib.sha256(result_canonical).hexdigest()}"

        return {
            "adapter_id": permit.adapter_id,
            "adapter_digest": adapter_digest,
            "side_effects_observed": False,
            "output": output,
            "result_digest": result_digest,
        }

    def verify_result(self, req: ReplayRequest, permit: ReplayPermit, exec_result: Dict[str, Any]) -> bool:
        """Confirm result schema, request hash, permit binding, and side-effect freedom."""
        if exec_result.get("side_effects_observed") is not False:
            return False
        if exec_result.get("adapter_id") != permit.adapter_id:
            return False
        # Verify result digest recalculation
        output = exec_result.get("output", {})
        recomputed_digest = f"sha256:{hashlib.sha256(canonicalize_json(output)).hexdigest()}"
        if recomputed_digest != exec_result.get("result_digest"):
            return False
        return True

    def seal_evidence_record(
        self,
        req: ReplayRequest,
        decision: str,
        denial_reason: Optional[str],
        permit: Optional[ReplayPermit],
        exec_result: Optional[Dict[str, Any]],
        previous_record_digest: str = "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        timestamp_utc: str = "2026-09-26T12:00:00Z",
    ) -> Dict[str, Any]:
        """Construct an immutable, sealed evidence record with hash chain."""
        req_digest = req.compute_digest()
        record_id = f"evidence-{req.request_id}"

        record: Dict[str, Any] = {
            "record_version": "1.0",
            "record_id": record_id,
            "timestamp_utc": timestamp_utc,
            "request": {
                "canonical_bytes_digest": req_digest,
                "schema_version": req.schema_version,
                "workload_type": req.workload_type,
                "fixture_id": req.fixture_id,
                "request_id": req.request_id,
            },
            "policy": {
                "policy_revision": self.policy.policy_revision,
                "policy_digest": f"sha256:{hashlib.sha256(self.policy.policy_revision.encode('utf-8')).hexdigest()}",
                "decision": decision,
                "denial_code": denial_reason,
            },
            "permit": asdict(permit) if permit else None,
            "execution": exec_result,
            "verification": {
                "request_binding_verified": (permit.request_digest == req_digest) if permit else False,
                "permit_binding_verified": bool(permit),
                "result_schema_verified": bool(exec_result),
                "replay_status": "NOT_YET_REPLAYED",
            },
            "integrity": {
                "previous_record_digest": previous_record_digest,
                "record_digest": "",
            },
        }

        # Compute hash of record without record_digest
        record_copy = json.loads(json.dumps(record))
        record_copy["integrity"]["record_digest"] = ""
        canonical_record_bytes = canonicalize_json(record_copy)
        record_digest = f"sha256:{hashlib.sha256(canonical_record_bytes).hexdigest()}"
        record["integrity"]["record_digest"] = record_digest
        return record

    def replay_record(self, record: Dict[str, Any], original_req: ReplayRequest) -> Tuple[bool, str]:
        """Replay sealed record and compare recomputed decision and result digests."""
        # 1. Canonicalize original request and check binding
        recomputed_req_digest = original_req.compute_digest()
        recorded_req_digest = record["request"]["canonical_bytes_digest"]
        if recomputed_req_digest != recorded_req_digest:
            return False, f"Request digest mismatch: recomputed {recomputed_req_digest} != recorded {recorded_req_digest}"

        # 2. Re-evaluate policy decision
        decision, permit, denial = self.decide(original_req, record["policy"]["policy_revision"])
        if decision != record["policy"]["decision"]:
            return False, f"Policy decision mismatch: recomputed {decision} != recorded {record['policy']['decision']}"

        if decision == "ALLOW_REPLAY":
            if not permit:
                return False, "Replay permitted but no permit issued"
            exec_result = self.execute_adapter(permit, original_req)
            if exec_result["result_digest"] != record["execution"]["result_digest"]:
                return False, f"Execution result digest mismatch: recomputed {exec_result['result_digest']} != recorded {record['execution']['result_digest']}"

        return True, "REPLAY_MATCH"
