# OSIRIS Governance: Replay-Only Core

This package provides the minimal, side-effect-free replay proof for the OSIRIS governance framework.

## Boundaries & Non-Authority Guarantees

- **Capability**: Strictly limited to `Capability.REPLAY` and `ActionKind.REPLAY_FIXTURE`.
- **Target**: Fixed in-memory fixture identifiers only.
- **Side Effects**: Zero. No filesystem paths, no subprocess spawns, no network sockets, no cloud dispatch.
- **Permit Model**: `ReplayExecutionPermit` is a process-local, non-authoritative binding that mechanically expires upon process restart or window expiry. It is not a digital signature, cloud credential, or external grant.
