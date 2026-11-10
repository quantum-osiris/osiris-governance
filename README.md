# OSIRIS Governance & Authority Control Plane

`osiris-governance` provides the deterministic capability governor and provider-neutral authority boundary for the OSIRIS ecosystem.

## Core Architectural Invariants

1. **Cognition Proposes; Governance Authorizes**: No cognitive substrate (Gemini, Antigravity, local model, or replay fixture) possesses execution authority. Substrates generate serialized `ActionProposal` records only.
2. **Deterministic Byte Binding**: Authorization decisions bind strictly to the exact serialized canonical bytes of the proposal via SHA-256. Any byte modification invalidates the binding.
3. **Fail-Closed Execution**: Action proposals are denied unless explicitly permitted by policy. All denials occur *prior* to adapter invocation.
4. **Zero Filesystem Authority in Replay**: In the offline replay slice, the adapter has zero filesystem, subprocess, network, or environment access.
5. **Non-Authoritative Replay Permits**: In offline replay, execution tokens are typed `ReplayExecutionPermit` with scope `REPLAY_ONLY_NON_CRYPTOGRAPHIC`. They confer zero authority for real-world side effects.

## Layout

```text
src/osiris_governance/
├── __init__.py
├── contracts.py       # ActionProposal, ReplayExecutionPermit, Enums
├── canonical.py       # OSIRIS-CANONICAL-JSON-V1 serialization & hashing (strict RFC 8785 subset)
├── closure.py         # Claim closure schema, policy v1, signed payload
├── closure_verify.py  # Closure signing and stage-B verification (pure)
├── signing.py         # Ed25519 over canonical bytes (optional `cryptography`)
├── governor.py        # Deterministic CapabilityGovernor & Policy
├── replay.py          # Pure in-memory ReplayAdapter (Zero filesystem)
└── errors.py          # Typed GovernanceViolation hierarchy
```

## Governance & Architecture Documentation Suite

- [`OSIRIS_GOVERNANCE_PRINCIPLES.md`](docs/OSIRIS_GOVERNANCE_PRINCIPLES.md): Core axioms, cross-plane non-substitution invariant ($\text{SCIENCE} \not\vdash \text{DEPLOYMENT}$), adverse-first rule, and vocabulary standards.
- [`OSIRIS_RELEASE_TARGET_ARCHITECTURE.md`](docs/OSIRIS_RELEASE_TARGET_ARCHITECTURE.md): Revised 8-gate release architecture with implementation status per gate and authority monotonicity ($\text{Eligible}_{i+1} \subseteq \text{Eligible}_i$).
- [`OSIRIS_CLOUD_RUN_SECURITY_BASELINE.md`](docs/OSIRIS_CLOUD_RUN_SECURITY_BASELINE.md): Managed Cloud Run sandbox, IAM identity separation (`actAs`), Secret Manager integration, and digest pinning (`sha256:`).
- [`OSIRIS_ANDROID_EDGE_PROTOTYPE.md`](docs/OSIRIS_ANDROID_EDGE_PROTOTYPE.md): Android evidence cockpit and constrained node boundaries, SQLite WAL store-and-forward, and StrongBox Key Attestation target.
- [`OSIRIS_EVIDENCE_MODEL.md`](docs/OSIRIS_EVIDENCE_MODEL.md): RFC 8785 Canonical JSON profile, four-coordinate scope binding, local hash-linked ledger model, and deterministic replay protocol.
- [`INCIDENT_SECRET_EXPOSURE_20260927.md`](docs/INCIDENT_SECRET_EXPOSURE_20260927.md): Credential exposure incident containment, revocation checklist, and release-blocking incident gate.
- [`OSIRIS_CLAIM_CLOSURE.md`](docs/OSIRIS_CLAIM_CLOSURE.md): Signed claim closure records: pack layout, two-stage verification, policy v1, and what verification does not establish. CLI: `scripts/closure_pack.py`.
- [`CLAIM_AUDIT.md`](docs/CLAIM_AUDIT.md): Master audit and de-scoping register mapping 20 technical assertions to code, tests, and public wording.

