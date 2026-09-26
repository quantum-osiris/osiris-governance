# OSIRIS Governance: Replay-Only Reference Implementation

**Version**: `0.1.0-reference`  
**Classification**: `REPLAY_ONLY_REFERENCE_IMPLEMENTATION`  
**Review Status**: `SELF_REVIEW` (Pending Independent Review)  

`osiris-governance` provides an experimental, self-reviewed reference implementation of canonical proposal binding and in-memory replay-only permit validation. It has no authority outside replay fixtures and does not provide cryptographic authorization, durable anti-replay protection, sandboxing, cloud execution, or provider integration.

## Boundaries & Non-Authority Guarantees

- **Capability**: Strictly limited to `Capability.REPLAY` and `ActionKind.REPLAY_FIXTURE`.
- **Target**: Fixed in-memory fixture identifiers only (`DEFAULT_FIXTURE_REGISTRY`).
- **External Side Effects**: Unimplemented. No filesystem paths, no subprocess spawns, no network sockets, no cloud dispatch, no credential lookup.
- **Permit Model**: `ReplayExecutionPermit` is a process-local, non-authoritative binding that mechanically expires upon process restart or window expiry. It is an integrity binding identifier, not a digital signature, cloud credential, or external grant.
- **Canonical Serialization**: Implements `OSIRIS-CANONICAL-JSON-V1`, a project-local canonical JSON profile using JCS-inspired code point key sorting, duplicate key rejection, float NaN/inf rejection, and Unicode NFC normalization. It is not claimed to be RFC 8785 conformant until conformance test vectors are evaluated.
- **Anti-Replay Persistence**: Nonce tracking is strictly in-memory per process epoch. Durable anti-replay protection across restarts is not implemented.
- **Testing**: Zero-dependency test suite implemented exclusively with the Python standard library `unittest`. No pytest dependencies or shims.
