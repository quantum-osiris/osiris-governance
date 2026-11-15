"""Deterministic GitHub policy: reads allowed, writes gated, every denial has a reason."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from osiris_governance.canonical import canonicalize_json
from osiris_governance.github_policy import (
    GITHUB_ACTION_KIND,
    GitHubPolicy,
    PolicyError,
    evaluate_github_proposal,
)

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)


def policy(**over):
    doc = {
        "schema": "osiris-github-policy/v1",
        "policy_version": "test/1",
        "expected_login": "quantum-osiris",
        "repositories": {
            "quantum-osiris/osiris-cli": ["github.repo.read", "github.pr.read", "github.pr.create"],
            "ENKI-420/quantum-ide": ["github.repo.read"],
        },
        "writes_enabled": False,
        "security_gates": {"S0-ACCOUNT": "NOT_MET"},
    }
    doc.update(over)
    return GitHubPolicy.from_json(json.dumps(doc).encode())


def proposal(capability="github.repo.read", repo="quantum-osiris/osiris-cli", **over):
    p = {
        "proposal_id": "p1", "request_id": "r1", "proposer_id": "test", "action_kind": GITHUB_ACTION_KIND,
        "capability": capability, "fixture_id": repo, "arguments": {"title": "x"}, "nonce": "n1",
        "created_at_utc": (NOW - timedelta(minutes=1)).isoformat(),
        "expires_at_utc": (NOW + timedelta(minutes=10)).isoformat(),
        "schema_version": "action-proposal/v1",
    }
    p.update(over)
    return canonicalize_json(p)


def decide(prop, pol=None, login="quantum-osiris"):
    return evaluate_github_proposal(prop, pol or policy(), observed_login=login, now=NOW)


def test_read_on_allowlisted_repo_is_allowed_without_grant():
    d = decide(proposal())
    assert d.allowed and not d.is_write and not d.requires_grant and d.reasons == ()


def test_repository_names_are_case_insensitive():
    assert decide(proposal(repo="enki-420/QUANTUM-IDE")).allowed


def test_identity_mismatch_denies_even_reads():
    d = decide(proposal(), login="someone-else")
    assert not d.allowed and any(r.startswith("IDENTITY_MISMATCH") for r in d.reasons)


def test_missing_identity_denies():
    d = decide(proposal(), login=None)
    assert not d.allowed and "IDENTITY_UNAVAILABLE" in d.reasons


def test_unlisted_repository_denied():
    d = decide(proposal(repo="attacker/osiris-cli"))
    assert not d.allowed and any(r.startswith("REPOSITORY_NOT_ALLOWLISTED") for r in d.reasons)


def test_capability_not_granted_for_repository():
    d = decide(proposal(capability="github.pr.read", repo="ENKI-420/quantum-ide"))
    assert any(r.startswith("CAPABILITY_NOT_GRANTED_FOR_REPOSITORY") for r in d.reasons)


def test_unknown_capability_and_action_kind_denied():
    d = decide(proposal(capability="github.repo.delete", action_kind="SHELL"))
    assert not d.allowed
    assert any(r.startswith("CAPABILITY_UNKNOWN") for r in d.reasons)
    assert any(r.startswith("ACTION_KIND_NOT_PERMITTED") for r in d.reasons)


def test_write_denied_while_writes_disabled_and_gates_unmet():
    d = decide(proposal(capability="github.pr.create"))
    assert not d.allowed and d.is_write
    assert "WRITES_DISABLED_BY_POLICY" in d.reasons
    assert any(r.startswith("SECURITY_GATES_NOT_PASSED") for r in d.reasons)


def test_write_with_enabled_policy_and_passed_gates_still_requires_grant():
    pol = policy(writes_enabled=True, security_gates={"S0-ACCOUNT": "PASSED"})
    d = decide(proposal(capability="github.pr.create"), pol)
    assert d.allowed and d.requires_grant


def test_write_on_read_only_repository_denied_even_when_enabled():
    pol = policy(writes_enabled=True, security_gates={})
    d = decide(proposal(capability="github.pr.create", repo="ENKI-420/quantum-ide"), pol)
    assert not d.allowed


def test_expired_proposal_denied():
    d = decide(proposal(expires_at_utc=(NOW - timedelta(seconds=1)).isoformat()))
    assert "PROPOSAL_EXPIRED_OR_NOT_YET_VALID" in d.reasons


def test_non_canonical_bytes_denied():
    pretty = json.dumps(json.loads(proposal()), indent=2).encode()
    assert "PROPOSAL_NOT_CANONICAL" in decide(pretty).reasons


@pytest.mark.parametrize("raw", [b"not json", b"[]", b'{"a":1,"a":2}', b'{"capability":"x"}'])
def test_malformed_proposals_denied_not_raised(raw):
    d = decide(raw)
    assert not d.allowed and d.reasons[0].startswith("PROPOSAL_MALFORMED")


def test_altered_payload_changes_proposal_digest():
    a, b = decide(proposal()), decide(proposal(arguments={"title": "y"}))
    assert a.proposal_sha256 != b.proposal_sha256


def test_decision_is_deterministic():
    a, b = decide(proposal()), decide(proposal())
    assert a == b and a.decision_sha256 and a.decision_sha256 == b.decision_sha256


def test_naive_time_rejected():
    with pytest.raises(ValueError):
        evaluate_github_proposal(proposal(), policy(), observed_login="quantum-osiris", now=datetime(2026, 1, 1))


@pytest.mark.parametrize("over", [
    {"schema": "other"},
    {"repositories": {}},
    {"repositories": {"bad name": ["github.repo.read"]}},
    {"repositories": {"a/b": ["github.everything"]}},
    {"writes_enabled": "yes"},
    {"expected_login": ""},
])
def test_malformed_policy_rejected(over):
    with pytest.raises(PolicyError):
        policy(**over)
