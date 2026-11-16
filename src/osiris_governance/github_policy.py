"""Deterministic policy for GitHub operations proposed by OSIRIS components.

The policy decides; it never executes. The same proposal bytes, policy bytes, observed login and
evaluation time always produce the same ``PolicyDecision`` and the same ``decision_sha256``.

Read capabilities are allowed for allowlisted repositories once the authenticated login matches the
policy. Write capabilities additionally need ``writes_enabled`` and every declared security gate in
state ``PASSED``. Even then the decision only says ``ALLOW`` with ``requires_grant=True``: the
caller must still present the owner's payload-bound SYS-021 grant for this exact proposal digest.
This module does no file, network or subprocess I/O.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, FrozenSet, Mapping, Optional, Tuple

from .canonical import canonical_sha256, canonicalize_json, strict_parse_json

GITHUB_ACTION_KIND = "GITHUB_OPERATION"
POLICY_SCHEMA = "osiris-github-policy/v1"

READ_CAPABILITIES: FrozenSet[str] = frozenset({
    "github.identity.read",
    "github.repo.read",
    "github.branch.read",
    "github.commit.read",
    "github.issue.read",
    "github.pr.read",
    "github.workflow.read",
    "github.contents.read",
})
WRITE_CAPABILITIES: FrozenSet[str] = frozenset({
    "github.pr.create",
    "github.issue.create",
    "github.issue.comment",
})
ALL_CAPABILITIES = READ_CAPABILITIES | WRITE_CAPABILITIES

_REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
_PROPOSAL_FIELDS = ("proposal_id", "request_id", "proposer_id", "action_kind", "capability",
                    "fixture_id", "arguments", "nonce", "created_at_utc", "expires_at_utc")


class PolicyError(ValueError):
    """The policy document itself is malformed. Callers must fail closed."""


def _utc(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class GitHubPolicy:
    policy_version: str
    expected_login: str
    repositories: Mapping[str, FrozenSet[str]]
    writes_enabled: bool = False
    security_gates: Mapping[str, str] = field(default_factory=dict)
    policy_sha256: str = ""

    @classmethod
    def from_json(cls, data: bytes) -> "GitHubPolicy":
        try:
            doc = strict_parse_json(data)
        except Exception as exc:  # canonical module raises several types; all mean "reject"
            raise PolicyError(f"policy is not strict JSON: {exc}") from exc
        if not isinstance(doc, dict) or doc.get("schema") != POLICY_SCHEMA:
            raise PolicyError(f"policy schema must be {POLICY_SCHEMA!r}")
        for key in ("policy_version", "expected_login", "repositories"):
            if key not in doc:
                raise PolicyError(f"policy is missing {key!r}")
        if not isinstance(doc["expected_login"], str) or not doc["expected_login"]:
            raise PolicyError("expected_login must be a non-empty string")
        repos: Dict[str, FrozenSet[str]] = {}
        if not isinstance(doc["repositories"], dict) or not doc["repositories"]:
            raise PolicyError("repositories must be a non-empty mapping")
        for repo, caps in doc["repositories"].items():
            if not _REPO_RE.match(repo):
                raise PolicyError(f"invalid repository name {repo!r}")
            if not isinstance(caps, list) or not all(isinstance(c, str) for c in caps):
                raise PolicyError(f"capabilities for {repo} must be a list of strings")
            unknown = set(caps) - ALL_CAPABILITIES
            if unknown:
                raise PolicyError(f"unknown capabilities for {repo}: {sorted(unknown)}")
            repos[repo.lower()] = frozenset(caps)
        gates = doc.get("security_gates", {})
        if not isinstance(gates, dict) or not all(isinstance(v, str) for v in gates.values()):
            raise PolicyError("security_gates must map gate ids to status strings")
        writes = doc.get("writes_enabled", False)
        if not isinstance(writes, bool):
            raise PolicyError("writes_enabled must be a boolean")
        return cls(policy_version=str(doc["policy_version"]), expected_login=doc["expected_login"],
                   repositories=repos, writes_enabled=writes, security_gates=dict(gates),
                   policy_sha256=canonical_sha256(canonicalize_json(doc)))


@dataclass(frozen=True)
class PolicyDecision:
    decision: str                 # "ALLOW" | "DENY"
    capability: str
    repository: str
    is_write: bool
    requires_grant: bool
    reasons: Tuple[str, ...]
    proposal_sha256: str
    policy_sha256: str
    policy_version: str
    evaluated_at_utc: str
    decision_sha256: str = ""

    @property
    def allowed(self) -> bool:
        return self.decision == "ALLOW"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["reasons"] = list(self.reasons)
        return d


def _decide(reasons, capability, repository, is_write, proposal_sha, policy, now) -> PolicyDecision:
    body = dict(decision="DENY" if reasons else "ALLOW", capability=capability, repository=repository,
                is_write=is_write, requires_grant=is_write, reasons=tuple(reasons),
                proposal_sha256=proposal_sha, policy_sha256=policy.policy_sha256,
                policy_version=policy.policy_version, evaluated_at_utc=now.isoformat())
    digest_src = dict(body, reasons=list(body["reasons"]))
    return PolicyDecision(**body, decision_sha256=canonical_sha256(canonicalize_json(digest_src)))


def evaluate_github_proposal(proposal_bytes: bytes, policy: GitHubPolicy, *, observed_login: Optional[str],
                             now: datetime) -> PolicyDecision:
    """Evaluate one GitHub action proposal. Never raises for a bad proposal: it returns DENY with reasons."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    proposal_sha = canonical_sha256(proposal_bytes) if isinstance(proposal_bytes, bytes) else ""
    reasons = []
    try:
        p = strict_parse_json(proposal_bytes)
    except Exception as exc:
        return _decide([f"PROPOSAL_MALFORMED: {exc}"], "", "", False, proposal_sha, policy, now)
    if not isinstance(p, dict):
        return _decide(["PROPOSAL_MALFORMED: root is not an object"], "", "", False, proposal_sha, policy, now)
    missing = [f for f in _PROPOSAL_FIELDS if f not in p]
    if missing:
        return _decide([f"PROPOSAL_MALFORMED: missing {missing}"], "", "", False, proposal_sha, policy, now)
    # The proposal bytes must already be canonical: what was hashed is exactly what is evaluated.
    if canonicalize_json(p) != proposal_bytes:
        reasons.append("PROPOSAL_NOT_CANONICAL")

    capability = p["capability"] if isinstance(p["capability"], str) else ""
    repository = p["fixture_id"].lower() if isinstance(p["fixture_id"], str) else ""
    is_write = capability in WRITE_CAPABILITIES

    if p["action_kind"] != GITHUB_ACTION_KIND:
        reasons.append(f"ACTION_KIND_NOT_PERMITTED: {p['action_kind']!r}")
    if capability not in ALL_CAPABILITIES:
        reasons.append(f"CAPABILITY_UNKNOWN: {capability!r}")
    if not observed_login:
        reasons.append("IDENTITY_UNAVAILABLE")
    elif observed_login != policy.expected_login:
        reasons.append(f"IDENTITY_MISMATCH: authenticated as {observed_login!r}, policy expects "
                       f"{policy.expected_login!r}")
    if capability != "github.identity.read":
        allowed_caps = policy.repositories.get(repository)
        if allowed_caps is None:
            reasons.append(f"REPOSITORY_NOT_ALLOWLISTED: {repository!r}")
        elif capability not in allowed_caps:
            reasons.append(f"CAPABILITY_NOT_GRANTED_FOR_REPOSITORY: {capability!r} on {repository!r}")
    try:
        if not (_utc(p["created_at_utc"]) <= now < _utc(p["expires_at_utc"])):
            reasons.append("PROPOSAL_EXPIRED_OR_NOT_YET_VALID")
    except (ValueError, TypeError, AttributeError):
        reasons.append("PROPOSAL_TIMESTAMP_MALFORMED")
    if is_write:
        if not policy.writes_enabled:
            reasons.append("WRITES_DISABLED_BY_POLICY")
        unmet = sorted(g for g, s in policy.security_gates.items() if s != "PASSED")
        if unmet:
            reasons.append(f"SECURITY_GATES_NOT_PASSED: {unmet}")
    return _decide(reasons, capability, repository, is_write, proposal_sha, policy, now)
