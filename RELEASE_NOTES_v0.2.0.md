# OSIRIS Governance v0.2.0: Deterministic Control Plane, RFC 8785 Canonical JSON & Two-Stage Claim Closure

**Release Date:** October 31, 2026  
**Author:** Devin Phillip Davis  
**Affiliation:** Agile Defense Systems LLC / OSIRIS Sovereign Architecture Project  
**Repository:** [osiris-dnalang/osiris-governance](https://github.com/osiris-dnalang/osiris-governance)  
**Concept DOI:** [10.5281/zenodo.22980007](https://doi.org/10.5281/zenodo.22980007)  
**Governance Invariant:** SYS-021 (Zero Self-Supplied Authorization) & Gate 0 Invariant 6  

---

## 1. Executive Summary

`osiris-governance v0.2.0` ratifies the authoritative deterministic control plane and execution boundary for the OSIRIS sovereign intelligence ecosystem. Building upon the initial reference beta, this release establishes:
1. **RFC 8785 Canonical JSON Serialization** (`osiris_governance.canonical`): Cryptographically deterministic canonical JSON hashing (`canonical_sha256`) conforming strictly to RFC 8785 with safe integer bounds and Unicode normalization policies.
2. **Two-Stage Cryptographic Claim Closure** (`osiris_governance.closure`, `closure_verify`): Formal signing payloads and disk-artifact verification for empirical claim packs.
3. **SYS-021 Authority Permit Gating**: Strict enforcement of external operator permits (`AuthorityPermit`, `ReplayExecutionPermit`) before any execution or ledger mutation can occur.
4. **Node Beta Phase-Conjugate Recalibration (PCRB) Ledger**: Cryptographic event chaining for cross-plane telemetry and lattice state verification.

---

## 2. Key Modules & Technical Architecture

### A. RFC 8785 JSON Canonicalization Engine
* Pure-Python, high-assurance JCS implementation ensuring identical SHA-256 digests across disparate architectures (x86_64, ARM64, Big-Endian/Little-Endian).
* Fail-closed rejection of non-finite floats, out-of-bounds integers ($> 2^{53}-1$), and unnormalized Unicode control characters.

### B. Cryptographic Claim Pack Closure & Verification
* Two-stage claim verification pipeline:
  1. `sign_closure`: Computes payload digest over empirical artifacts and signs with operator enclave key.
  2. `verify_closure`: Deterministically inspects filesystem artifacts against signed manifests and Merkle receipts.

### C. Capability Governor & Replay Confinement
* Confinement probes, least-privilege descriptor manifests, and openat2-style path resolution preventing sandbox escape.
* Replay execution adapter ensuring identical pre- and post-execution filesystem snapshots.

---

## 3. Test & Verification Suite

* **Verification Result**: **199 passed, 2 skipped, 0 failed** in 85.04s under Python 3.12 (`pytest-9.1.1`).
* **Contract Rehearsal**: Interactive REPL state machine validated across `/ignite`, `/experiment`, `/dna`, and `/ledger` stages.
