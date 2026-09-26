# Separate-Agent Review Report: `osiris-governance`

**Document ID:** OSIRIS-GOV-REV-2026-09-26-001  
**Date:** 2026-09-26  
**Reviewer Identity:** Separate-Agent Context Reviewer (Subagent `7150b3ca`)  
**Review Independence:** `NOT_ESTABLISHED` (Internal separate-context review under NIST SP 800-218 SSDF PW.2.1; not an external third-party certification)  
**Subject:** `osiris-governance` Reference Implementation  
**Evaluated Target:** `/tmp/osiris-governance`  
**Durable Mirror Target:** `/home/enki/analysis/osiris-governance`  
**Review Determination:** `SEPARATE-AGENT REVIEW RESULT: REVIEWED_CANDIDATE_ACCEPTED_FOR_LOCAL_OFFLINE_IN-MEMORY_REPLAY_EXPERIMENTATION_ONLY`

---

## 1. Executive Summary & Review Scope

A separate-context clean-room software, security, and static code analysis review of the `osiris-governance` reference implementation (version `0.1.0-reference`) was conducted across both the build repository `/tmp/osiris-governance` and its durable mirror `/home/enki/analysis/osiris-governance`.

### Limits & Scope Statement
- **Scope:** `REPLAY_ONLY_NON_CRYPTOGRAPHIC` in-memory reference implementation.
- **Accepted For:** Local offline in-memory deterministic replay experimentation only.
- **Independence Classification:** `review_independence: NOT_ESTABLISHED`. The review was executed by a separate subagent within the same operator/IDE conversation and workspace, fulfilling the spirit of a separate-context internal review under NIST SP 800-218 (SSDF) PW.2.1, but not an independent external third-party security assessment.
- **Assurance Limits (What This Review Is NOT):**
  - **NOT an independent third-party certification** or regulatory compliance audit.
  - **NOT production control-plane authorization** or a production-ready authority layer.
  - **NOT whole-process side-effect freedom:** While source-level static analysis verified no direct standard I/O calls in `src/osiris_governance`, this does not govern the hosting Python runtime, parent process I/O, native C-extensions, or garbage collector hooks.
  - **NOT verification of compiler/interpreter behavior:** Does not assess Python bytecode compiler bugs, memory safety of the CPython interpreter, or CPU hardware timing side channels.
- **Qualified Source-Level I/O Finding:** No direct use of configured I/O, socket, and subprocess APIs was found in the reviewed `src/osiris_governance` source tree.
- **Explicit Functional Exclusions:**
  - External action execution
  - Filesystem access or path resolution
  - Network communication or socket operations
  - Hardware / QPU access
  - Credential handling or identity federation
  - Cloud provider integration (GCP, AWS, Azure)
  - Persistent distributed nonce enforcement
  - Cryptographic digital authorization or asymmetric signature verification
  - Production deployment or production control-plane authorization

---

## 2. Environment Metadata

The separate-agent audit and verification test suite were executed in the following clean-room environment:

| Property | Value |
| :--- | :--- |
| **Python Version** | `3.12.3 (main, Aug 31 2026, 10:18:26) [GCC 13.3.0]` |
| **Operating System** | `Linux 6.18.33.2-microsoft-standard-WSL2 #1 SMP PREEMPT_DYNAMIC` |
| **Platform Identifier** | `Linux-6.18.33.2-microsoft-standard-WSL2-x86_64-with-glibc2.39` |
| **Hardware Architecture** | `x86_64` |
| **Test Runner** | Python standard library `unittest` (`python3 -m unittest`) |
| **External Package Dependencies** | Zero (`dependencies = []`) |
| **Review Independence Level** | `NOT_ESTABLISHED` (SSDF PW.2.1 separate-context internal review) |

---

## 3. 13-Item Review Checklist & Verification Results

| # | Checklist Item | Evaluation Outcome | Summary of Evidence & Verification |
| :-: | :--- | :-: | :--- |
| **1** | Clean Source Clone & Commit Verification | **PASS** | Validated git commit chain, commit hashes, parents, trees, and strict object integrity (`git fsck --full --strict`). Details recorded in Section 4. |
| **2** | Hash Verification | **PASS** | Recomputed SHA-256 for all 12 tracked repository files against `osiris-governance-sha256.txt` and `package-manifest.json`. 100% byte equivalence confirmed. |
| **3** | Clean Working Tree | **PASS** | `git status` confirmed zero untracked and zero modified files in both `/tmp/osiris-governance` and `/home/enki/analysis/osiris-governance` prior to report emission. |
| **4** | Packaging & SCA / SBOM Inspection | **PASS** | Software Composition Analysis (SCA) verified zero runtime dependencies (`dependencies = []`). Only Python standard library components are utilized. Zero third-party wheels, zero vendored dependencies. |
| **5** | Framework Shadowing Check | **PASS** | Verified no `pytest.py` shim or framework interceptor exists anywhere in `tests/` or the repository. Legacy shim was cleanly deleted in commit `64c710a35f3b268f8bd930beb9a8a7bcc774cf13`. |
| **6** | Zero-Dependency Test Execution | **PASS** | Ran `PYTHONPATH=src python3 -m unittest discover tests`. All 21 tests pass with 0 failures and 0 errors in 0.019s. (19 tests passed in commit `64c710a`; 2 additional boundary tests added in HEAD commit `8c5f37c`). |
| **7** | Canonicalization Profile Review | **PASS** | `canonical.py` implements `OSIRIS-CANONICAL-JSON-V1`: Unicode NFC normalization, code point sorted keys, duplicate-key rejection hook, float NaN/inf rejection (`allow_nan=False`), unkeyed SHA-256. Explicitly disclaims uncertified RFC 8785 compliance. |
| **8** | Deep Immutability Verification | **PASS** | `ActionProposal`, `ReplayExecutionPermit`, `ReplayInvocation`, and `ReplayResult` are `@dataclass(frozen=True)`. Nested parameters and outputs recursively frozen to immutable sorted tuples via `_freeze_val`. Mutation attempts raise `FrozenInstanceError`. |
| **9** | Five Invariant Bounds | **PASS** | `governor.py` (`replay_governor.py`) and `replay.py` enforce all 5 hard boundary invariants, each covered by negative denial unit tests: SCOPE (`PERMIT_SCOPE_INVALID`), EPOCH (`PERMIT_PROCESS_EPOCH_MISMATCH`), EXPIRY (`PERMIT_EXPIRED`), BINDING (`PROPOSAL_BINDING_MISMATCH`), CANONICAL_VERSION (`CANONICALIZATION_VERSION_MISMATCH`). |
| **10** | AST Static Audit & SAST Bounds | **PASS** | AST static analysis over `src/osiris_governance/` confirmed no direct use of configured I/O, socket, and subprocess APIs (`os`, `socket`, `subprocess`, `urllib`, `requests`, `google`, `cloud`, `pathlib`, `httpx`, `boto`, `secret`, `dotenv`, `ctypes`, `pickle`, `multiprocessing`, `threading`, `tempfile`, `shutil`) and zero calls to `eval`/`exec`. |
| **11** | Tested Import Isolation | **PASS** | Verified `sys.modules` contains zero references or bindings to quarantined `/home/enki/fold/osiris`. Package loads strictly from local `src/osiris_governance`. |
| **12** | Consumer Independence | **PASS** | Verified `osiris_governance` is not installed into global Python environment (`find_spec('osiris_governance')` is `None`). Scanned workspace `/home/enki/fold` and verified zero external consumers import `osiris_governance`. |
| **13** | Review Artifact Synchronization | **PASS** | Formal separate-agent review report published to `/home/enki/analysis/osiris-governance/INDEPENDENT_REVIEW_REPORT.md` and mirrored to `/tmp/osiris-governance/INDEPENDENT_REVIEW_REPORT.md`. |

---

## 4. Repository Provenance & Commit Lineage

### Provenance Classification
- **Classification:** `LOCAL_REPOSITORY_SYNCHRONIZATION_AND_BYTE_EQUIVALENCE_CHECK`
- **Notice:** This verification certifies local byte-equivalence and structural integrity across the build directory (`/tmp/osiris-governance`) and durable storage (`/home/enki/analysis/osiris-governance`). It does NOT constitute third-party independent remote provenance verification.

### Git Object & Lineage Verification
`git fsck --full --strict` reported zero corrupt objects and full structural integrity.

#### Commit Lineage Record:
1. **HEAD Commit:** `8c5f37ca389f696b586d5f6499f5e0d2302c8ab5`
   - **Tree:** `35e9ccc807f5da8b1007c74100ea9933043e4487`
   - **Parent:** `a7693d1ff1720cdc56d6e6abe18d61db0b9588f2`
   - **Author/Committer:** OSIRIS Governance Replay Core `<governance@osiris.local>` (1790421325 -0400)
   - **Message:** `feat(replay): implement prepare_replay with ReplayInvocation, ASCII authority constraints, and 21 passing tests`
2. **Parent Commit:** `a7693d1ff1720cdc56d6e6abe18d61db0b9588f2`
   - **Tree:** `043ae895fb2e3ca701df3d2c1cdf4b4440a55ad3`
   - **Parent:** `64c710a35f3b268f8bd930beb9a8a7bcc774cf13`
   - **Message:** `Update manifests and checksum records`
3. **Commit:** `64c710a35f3b268f8bd930beb9a8a7bcc774cf13`
   - **Tree:** `9307c00bfce4670ad63fc2d38501ae8ec7239a7b`
   - **Parent:** `a6cd8ad740380abd17043cd1297e40e99442e083`
   - **Message:** `Refactor tests to unittest, clarify canonical profile, update to 0.1.0-reference`
4. **Root Commit:** `a6cd8ad740380abd17043cd1297e40e99442e083`
   - **Tree:** `f9ad9842f910bfa90e1c88a54fb9f8e0139c2c91`
   - **Message:** `Initial release of osiris-governance replay-only reference implementation`

### SHA-256 Byte Integrity Manifest
All files verified matching `osiris-governance-sha256.txt` and `package-manifest.json`:

```
715d5cd6d3ce92a92af39575163f3a149a1f7cfabfa2f59ab9b51f3b73a448d9  README.md
95994f62733747349c7459823c711a3d0ece6f4cd4d601b25e32ababee406aed  pyproject.toml
2492d10c4769309ad1f5e12191e546f674334aedb45543076af330ed4fdcce0b  run_tests.py
dad7aa3b8c953a44442eb13fdeb2b49d330894f90ea9820ba83ec9316c51be87  src/osiris_governance/__init__.py
6c05c4369732ea8632be81bc88f5bea87cc435af42b990a98d6ab49ff78b6ac1  src/osiris_governance/canonical.py
5f2c535b42ab7bde477597b590d6b37d8a9d8ceee8110658ff98ea8d781c781f  src/osiris_governance/contracts.py
7e5edabf09d86970c7bc4dd154b8beeecd22ebf7a260254713a9e178ed45e47a  src/osiris_governance/errors.py
077165a998c308e4237c0b450ba0d09d618c1861f3724465fac39a9e9e65a9a0  src/osiris_governance/replay.py
e3711acf7ec1e27c9fabfb718ad9751ee67dd64c92fd8aa6e6954bada36cac79  src/osiris_governance/replay_governor.py
b5238c450adf234951b75e37f9a56e469503d81b9364528680dfeb8494b07c7e  tests/test_canonical_binding.py
13d160b436a778efd5545e66e0fa23a42fd8ddf76bde4d7e3c5f0def6a62b689  tests/test_replay_governor.py
0f3315617b13fadad03a48fb6628b45814b37d7ca6ea36a2bb3b3b61f5aae50e  test_report.json
```
`package-manifest.json` SHA-256 matches `package-manifest.sha256`:  
`3480be63b0a2333fe38779c855a90d96d934bb7d83ca9473d3284ff80ba174e2`

---

## 5. Critical Boundary & Security Analysis

### 5.1 Replay Invocation Boundary
1. **Fixture ID Resolution:**
   - In `replay.py`, `invocation.fixture_id` resolves solely against the in-memory dictionary `DEFAULT_FIXTURE_REGISTRY` (or an explicitly supplied `fixture_registry` mapping).
   - Lookup is performed exclusively via Python key matching: `registry[invocation.fixture_id]`.
   - Cannot resolve to arbitrary code, dynamic module imports, filesystem files, URLs, or external resources.
   - If a fixture identifier is not explicitly registered, execution fails closed with `ReplayError("FIXTURE_NOT_FOUND")`.
2. **Raw Proposal Data Handling:**
   - `canonical_proposal_bytes` is exclusively parsed as raw data using standard `json.loads` through `parse_canonical_json`.
   - Never passed to `eval()`, `exec()`, template engines, pickle, or dynamic callback registries.
3. **Nonce and Process Epoch Validation:**
   - Nonces and process epoch IDs are strictly validated as ASCII strings via `_require_ascii_identifier`.
   - `nonce` is tracked exclusively in-memory within `ReplayGovernor._consumed_nonces: set[str]`. It is never utilized as a filesystem path, cache key with path traversal, or dynamic code lookup. Re-presentation within the same process epoch fails closed with `GovernanceViolation("NONCE_ALREADY_CONSUMED")`.
   - `process_epoch_id` is evaluated via direct string equality check against `active_process_epoch_id`.
4. **Registry Mutability:**
   - `DEFAULT_FIXTURE_REGISTRY` is defined as a module-level constant dictionary. During replay execution, it is only read.
   - In `execute_replay`, fixture data is shallow-copied (`dict(fixture_data)`) and deeply frozen into `ReplayResult.normalized_output` via `_freeze_val`.
   - *Recommendation:* For further defense-in-depth in future iterations, wrap `DEFAULT_FIXTURE_REGISTRY` in `types.MappingProxyType`.
5. **Replay Result State Isolation:**
   - `ReplayResult` is `@dataclass(frozen=True)` with normalized output stored as recursively frozen tuples.
   - `result.output_as_dict()` creates fresh dictionary instances on demand.
   - No mutable state leaks across sequential or concurrent replay invocations.
6. **Side Effect & Interaction Audit:**
   - Error handling: Exceptions (`GovernanceViolation`, `CanonicalizationError`, `ReplayError`) only store error code strings and messages. No telemetry, syslog, or logging side effects.
   - Logging: No standard `logging` module or custom logger is imported or invoked.
   - Source-Level I/O Audit: No direct use of configured I/O, socket, and subprocess APIs was found in the reviewed `src/osiris_governance` source tree.

### 5.2 Unicode & Identifier Grammar Policy
1. **Authority Identifiers:**
   - In `contracts.py`, `_require_ascii_identifier(name, val)` enforces that all authority-bearing fields (`format_id`, `format_version`, `schema_id`, `schema_version`, `proposal_id`, `fixture_id`, `nonce`, `process_epoch_id`, `scope`, `policy_version`, `canonicalization_version`) must be strings and satisfy `val.isascii()`.
   - Any non-ASCII Unicode characters (e.g., `\u00e9`, `\u03c0`) are immediately rejected with `CanonicalizationError("NON_ASCII_IDENTIFIER")`.
   - *Grammar Observation:* Currently, `_require_ascii_identifier` validates ASCII character set membership (`isascii()`). Because `fixture_id` is solely looked up in a closed in-memory dictionary, path characters (e.g., `..`, `/`) do not lead to filesystem traversal. For future formal production control-planes, adopting an explicit regex grammar (e.g., `^[A-Za-z][A-Za-z0-9_-]{0,63}$`) is recommended to reject delimiters and control characters at the grammar level.
2. **Payload Values & NFC Normalization:**
   - In `canonical.py`, `unicodedata.normalize("NFC", raw_str)` is applied to all serialized JSON payloads.
   - This NFC normalization is an **intentional semantic transformation rule** in `OSIRIS-CANONICAL-JSON-V1`. Composed and decomposed Unicode character sequences (such as `café` vs `cafe\u0301`) intentionally produce identical canonical byte sequences and identical SHA-256 digests.
3. **Explicit Boundary Test Coverage:**
   - Verified that `tests/test_canonical_binding.py::TestCanonicalBinding::test_non_ascii_identifier_rejection` explicitly exercises and confirms rejection of non-ASCII characters in `proposal_id` and `fixture_id`.
   - Verified that `tests/test_canonical_binding.py::TestCanonicalBinding::test_unicode_normalization_nfc` explicitly tests decomposed and precomposed Unicode strings to confirm deterministic byte matching.

### 5.3 Five Invariant Verification Matrix
All five invariants are tested and pass negative denial verification in `tests/test_replay_governor.py`:

```
[Invariant 1: Scope Validation]
Input:  Permit scope = "EXECUTION_GRANT_EXTERNAL"
Result: Denied with GovernanceViolation("PERMIT_SCOPE_INVALID")

[Invariant 2: Epoch Restart Invalidation]
Input:  Active process epoch = "epoch-restarted-new", Permit epoch = "epoch-initial"
Result: Denied with GovernanceViolation("PERMIT_PROCESS_EPOCH_MISMATCH")

[Invariant 3: Expiry Window Enforcement]
Input:  Current time "2026-09-26T06:01:01Z" > Expiry "2026-09-26T06:01:00Z"
Result: Denied with GovernanceViolation("PERMIT_EXPIRED")

[Invariant 4: Canonical Proposal Byte Binding]
Input:  Tampered proposal parameter {"run_mode": "tampered"}
Result: Denied with GovernanceViolation("PROPOSAL_BINDING_MISMATCH")

[Invariant 5: Canonicalization Version Match]
Input:  Permit version = "UNKNOWN-CANONICAL-V2"
Result: Denied with GovernanceViolation("CANONICALIZATION_VERSION_MISMATCH")
```

---

## 6. Review Determination & Outcome

```
================================================================================
                       SEPARATE-AGENT REVIEW RESULT
================================================================================

  DETERMINATION: REVIEWED_CANDIDATE_ACCEPTED_FOR_LOCAL_OFFLINE_IN-MEMORY_REPLAY_EXPERIMENTATION_ONLY

  REVIEW INDEPENDENCE: NOT_ESTABLISHED
  (Separate-agent context review under NIST SP 800-218 SSDF PW.2.1; not third-party certification)

  STATUS: ACCEPTED FOR LOCAL OFFLINE IN-MEMORY DETERMINISTIC REPLAY EXPERIMENTATION ONLY.

  EXCLUSIONS & BOUNDARIES:
    - NOT AN INDEPENDENT THIRD-PARTY CERTIFICATION
    - NOT PRODUCTION CONTROL-PLANE AUTHORIZATION
    - NOT WHOLE-PROCESS SIDE-EFFECT FREEDOM
    - NOT ACCEPTED FOR EXTERNAL ACTION EXECUTION
    - NOT ACCEPTED FOR FILESYSTEM ACCESS OR PATH RESOLUTION
    - NOT ACCEPTED FOR NETWORK OR SOCKET COMMUNICATION
    - NOT ACCEPTED FOR HARDWARE OR QPU ACCESS
    - NOT ACCEPTED FOR CREDENTIAL OR SECRET HANDLING
    - NOT ACCEPTED FOR CLOUD PROVIDER INTEGRATION
    - NOT ACCEPTED FOR PERSISTENT DISTRIBUTED NONCE ENFORCEMENT
    - NOT ACCEPTED FOR CRYPTOGRAPHIC DIGITAL SIGNATURE AUTHORIZATION
    - NOT ACCEPTED FOR PRODUCTION SYSTEM CONTROL PLANE DEPLOYMENT

================================================================================
```

**Signed by:**  
*Separate-Agent Context Reviewer (Subagent `7150b3ca`)*  
Internal Clean-Room Review Context under NIST SP 800-218 (SSDF) PW.2.1  
Date: 2026-09-26  
