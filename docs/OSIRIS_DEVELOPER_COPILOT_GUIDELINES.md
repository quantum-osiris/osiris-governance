# OSIRIS Sovereign Architecture Group: Developer & Copilot Instructions
## Sovereign Quantum-Biological Substrate, Governance Framework & Dual-Node Invariants
**Affiliation**: Agile Defense Systems, LLC (CAGE: 9HUP5), Lexington, Kentucky  
**Architect**: Devin Phillip Davis  
**Version**: 4.5.0 / Dual-Node Master Spec v1.2  
**Epistemic Axiom**: *"Models propose; deterministic code decides, measures, and records."*

---

## 1. Core System Axioms & Governance Framework

### 1.1. Context & Strategic Importance Mandate
The OSIRIS architecture establishes an impermeable epistemological boundary between generative artificial intelligence and deterministic physical execution. Generative Artificial Intelligence (LLMs, Copilot, Antigravity) operate strictly as **untrusted, non-deterministic proposal engines**. They possess **zero execution authority**, **zero self-certification privileges**, and **zero unmediated access** to host infrastructure, quantum hardware, or low-level operating system resources.

Every proposed mutation, shell command, code diff, or configuration change must be intercepted at a deterministic boundary, validated against formal pre-registered bounds and Abstract Syntax Tree (AST) rules, and cryptographically committed to an immutable append-only ledger before any side effect is permitted.

### 1.2. The Command Interposition Layer (CIL) 7-Layer Pipeline
Every incoming command or tool call is intercepted by the fail-closed CIL pipeline (`core/cil.py` / `dna_cli/cil.py`) evaluated strictly from Layer 0 through Layer 6:

| Layer | Layer Name | Validation Function | Operational Risk | Fail-Closed Action |
| :--- | :--- | :--- | :--- | :--- |
| **L0** | **Syntax Sanity** | Intercepts raw CLI strings; verifies structural formatting, bracket bounds (`()`, `[]`, `{}`), strips/neutralizes DECSET 2004 escape sequences (`\x1b[?2004h/l`), rejects null bytes. | SAFE | Rejects malformed strings; aborts process spawning. |
| **L1** | **Intent Classification** | Classifies requested actions into discrete operational intent vectors (`READ`, `WRITE`, `DESTRUCTIVE`, `SLASH_COMMAND`). | SAFE to LOW | Flags unmapped intent patterns; blocks execution if intent is unclassified. |
| **L2** | **Context Binding** | Validates environment variables, current working directories, workspace boundaries, and role scopes. Strictly blocks hardcoded paths (e.g. `~/fold/`). | LOW to MEDIUM | Restricts execution paths strictly to allowlisted, mutable workspace directories. |
| **L3** | **Risk Scoring** | Computes normalized risk vectors (0.0 to 1.0) based on path sensitivity, privilege level, and system impact (`SAFE`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`). | MEDIUM to HIGH | Terminates evaluation if calculated risk exceeds configured safety caps. |
| **L4** | **Enhancement Synthesis** | Injects runtime sandboxing flags, resource budgets, CPU/memory quotas, and isolation bounds. | MEDIUM | Appends forced isolation parameters and resource constraints to payload. |
| **L5** | **Deterministic Rewrite** | Rewrites hazardous, un-sanitized commands into safe, deterministic primitives (e.g., rewriting `rm -rf` directly to `trash-put`). | HIGH to CRITICAL | Deterministically neutralizes destructive operations. |
| **L6** | **Execution & Telemetry** | Dispatches rewritten payload within an isolated runtime container; captures stdout, stderr, and SHA-256 digests. | CRITICAL | Commits immutable execution receipts to the write-ahead cryptographic evidence ledger. |

### 1.3. Parameter Refutations & Origin-Tag Enforcements
System safety requires absolute fidelity to versioned governance parameters defined in `policy.json` v3:
- **$\theta_{\text{lock}} = 51.843^\circ$ Refutation**: Formally withdrawn per **Erratum v4.2.0 (Zenodo Record 10.5281/zenodo.19505923)**. Policy enforcement strictly mandates `operational_allowed = False` and `is_allowed_as_recovery_gate() = False`. Any attempt by an LLM or legacy script to use $51.843^\circ$ as an operational gate is blocked at runtime.
- **$\Gamma_{\text{floor}} = 0.0920$ / $\Gamma = 0.95$**: Verified operational thresholds governing physical system stability baselines.
- **136-bit "Negentropy Gap" Refutation**: Proven to be a finite-sample plug-in estimator artifact ($\log_2(10^6) = 19.93$ bits). Macroscopic quantum attractors and non-thermalization conjectures are permanently withdrawn.
- **NCLM Speaking Gate**: The Non-Causal Living Language Model (`osiris.nclm`) operates under a code-enforced output speaking gate (`osiris_cli_core/nclm_gate.py`). The core model is strictly prohibited from emitting responses in its own voice until compression loss achieves $\le 2.0$ bits/byte (BPB) across 30 held-out text exchanges (current: 7.6 BPB vs 5.03 unigram baseline). All conversational outputs default to labeled mentor models (e.g., local Ollama/Qwen).
- **2026-10-11 W8L-1 Incident Precedent**: Model-supplied values must NEVER be accepted as authoritative governance parameters or confirmed constraints. All model-derived inputs are origin-tagged `MODEL_PROPOSED` and quarantined behind the SYS-024 Claims Firewall.

---

## 2. Dual-Substrate Hardware Mesh & Execution Invariants

### 2.1. Dynamic Substrate Detection (`detect_substrate()`)
All OSIRIS operations, scripts, CLI tools, and agent proposals must dynamically determine host hardware via `osiris_hardware_mesh.py`:
- **Never Hardcode Paths**: Never assume `~/fold/` when executing on PC, or desktop-only paths when in Termux. Resolve paths dynamically via environment and workspace inspection.

### 2.2. Substrate Profile Mapping

| Operational Metric | Node Alpha (Mobile Edge Substrate) | Node Beta (Compute Workstation Substrate) |
| :--- | :--- | :--- |
| **Physical Platform** | Android Termux / ARM64 (Pixel 10 Pro Fold) | WSL2 Ubuntu / Windows x86_64 (Intel Core Ultra) |
| **Hardware Acceleration** | NEON SIMD Vector Acceleration | AVX2 / AVX-VNNI Instruction Sets |
| **Thermal Ceiling** | $42^\circ\text{C}$ Maximum Operating Temperature | Unconstrained Workstation Thermal Ceiling |
| **Execution Horizon** | Strict 300-Second Temporal Execution Lock | 1800-Second High-Throughput Execution Horizon |
| **Primary Workload** | Local AST Parsing, Edge Lexing, Lightweight Orchestration | Qiskit Runtime QPU Dispatch & Batch Tensor Simulation |
| **Storage & Memory** | Bounded In-Memory Buffers, Local JSONL | High-Throughput Matrix Storage, Multi-Qubit Workloads |

### 2.3. Dynamic Failover & Manifold Stability
- **$W_2$ Metric**: Evaluates empirical counts with pure-Python stdlib or NumPy-accelerated 1D Wasserstein-2 ($W_2$) distance between physical execution outputs and logical manifold states.
- **Decoherence Intervention**: If $W_2 > 0.10$, the runtime automatically injects Wheeler-DeWitt holonomy corrections and XY4 dynamical decoupling sequences.
- **State Transition Matrix**:
  $$\text{INITIALIZING} \longrightarrow \text{READY} \longrightarrow \text{RUNNING} \longrightarrow \text{DEGRADED} \longrightarrow \text{ROLLBACK\_PENDING} \longrightarrow \text{RECOVERING} / \text{QUARANTINED}$$
- If thermal limits ($> 42^\circ\text{C}$) or execution time ($> 300\text{s}$) are breached on Node Alpha, edge tasks fail over deterministically to Node Beta.

---

## 3. Developer Coding Standards & AST Security Firewalls

### 3.1. Prohibited Syntax & Denylist (`core/ast_verify.py`)
Static AST verification intercepts all candidate code prior to compilation or execution. Submissions violating these rules trigger instantaneous rejection:

```python
# 1. DYNAMIC EXECUTION PRIMITIVES (Strict Rejection)
exec(...)
eval(...)
compile(...)
__import__(...)

# 2. UN-SANITIZED SUBPROCESS INVOCATIONS
os.system(...)
subprocess.Popen(..., shell=True)
subprocess.run(..., shell=True)

# 3. IMMUTABLE GOVERNANCE PATHS (Raises ImmutablePathModifiedError)
open("policy.json", "w")
open("tests/core_test.py", "w")
open("cloudbuild.yaml", "w")
open("QUARANTINE_NOTICE.md", "w")

# 4. MOCK BACKEND DISGUISES (Raises MockDisguiseFirewallError)
# REJECTED: Synthetic mock classes pretending to be physical QPU hardware
class MockQPUBackend(PhysicalQPU):
    pass
```

### 3.2. 9-Step Engineering Sprint Workflow
1. **Discover**: Identify defects or bottlenecks via static analysis.
2. **Specify**: Define precise acceptance criteria, scope bounds, and capability requirements.
3. **Failing Test**: Construct an isolated unit test reproducing the defect or specifying new functionality.
4. **Patch Proposal**: Generate minimal code modifications restricted strictly to permitted, mutable workspace paths.
5. **Sandbox Run**: Apply candidate patches inside a disposable, isolated staging worktree.
6. **Diff Review**: Perform static inspection of proposed unified diffs against protected system boundaries.
7. **Regression Testing**: Execute the full verification suite (`pytest`) in the isolated sandbox (zero exit code).
8. **Evidence Recording**: Capture execution logs, resource consumption, and SHA-256 patch digests.
9. **Promotion Request**: Submit verified evidence artifacts to the human-in-the-loop promotion gate.

---

## 4. Edge Ingestion Protocols (Node Alpha)

### 4.1. Android IME In-Memory AST Capture (`OsirisIME.kt`)
- Text selected or entered on mobile edge devices is processed directly in memory via `InputConnection.getSelectedText(0)`.
- The global Android `ClipboardManager` is strictly bypassed to eliminate credential leakage.
- Payloads are framed and transmitted via Unix Domain Socket (`$PREFIX/tmp/osiris.sock`, permissions `0600`).
- **Buffer Safety**: In-memory `CircularBuffer` capped at 2,048 entries (`maxlen=2048`) with drop-head eviction under backpressure. Extended socket disconnections spill to local `osiris_ime_buffer.jsonl`.

### 4.2. Bluetooth Peripheral SCO Audio Pipeline
- Locks `AudioManager` into HFP/SCO mode (`startBluetoothSco()`, `setBluetoothScoOn(true)`).
- Captures 16kHz mono 16-bit PCM buffers for on-device speech-to-text inference (Whisper TFLite / VOSK) with zero cloud network connectivity.
- **AVRCP Hardware Controls**: Double-tap initiates voice capture; triple-tap triggers an immediate ledger commit and system checkpoint.

---

## 5. Scientific Rigor, QEC Pre-Registration & Cryptographic Provenance

### 5.1. QEC-REPL-1 Google 2022 Surface Code Replication
The independent replication of Google's 2022 surface code scaling result (*Nature 614, 676–681*) adheres to binding pre-registered decision rules:
- **Scaling Regression Formula**:
  $$1 - 2\cdot p_L(r) = A \cdot (1 - 2\varepsilon)^r$$
  Fitted using Weighted Least Squares (WLS) on $\log(1 - 2\cdot p_L(r))$ with binomial weights across round counts $r \in \{1, 3, \dots, 25\}$.
- **Metric R1 (Software Reproducibility)**: Running open-source PyMatching on detection events with `circuit_detector_error_model.dem` must reproduce `obs_flips_predicted_by_pymatching.01` on $\ge 99.9\%$ of experimental shots.
- **Metric R2 (Scaling Independence)**: Replicated successfully only if the 95% bootstrap confidence interval (1,000 resamples at strict seed `20261008`) for $\Lambda = \varepsilon_3 / \varepsilon_5$ strictly excludes the baseline 1.0 ($\Lambda > 1$).
- **Metric R3 (Headline Parity)**: Fitted values must fall within twice the combined standard error of Google's published abstract results ($\varepsilon_5 = 2.914\% \pm 0.016\%$ and $\varepsilon_3 = 3.028\% \pm 0.023\%$).

### 5.2. W8L-1 QLDPC Campaign Freeze Strictures
- **Sealed Commit**: Bound hermetically to Git commit `053c00b291fb2d0305d9bcd8771bb786fb5a2330`.
- **Resource Ceilings**: Strict 24.0 CPU-hour ceiling, 24.0 wall-clock ceiling, and an absolute candidate budget of exactly 50 permutations.
- **15 Release Gates (R1 to R15)**:
  - Gate R11: Statically bounds entropy seeds to `[101, 211, 307]`, strictly prohibiting "seed-shopping".
  - Gate R15: External human cryptographic authorization strictly required; autonomous launch prohibited.
- **Origin-Tag Invariant (SYS-024)**: Model-proposed parameters are quarantined. Models may not authoritatively supply or certify execution bounds.

### 5.3. 7 Epistemic Claim Categories & Ledger Integrity
All empirical records in `ledger.jsonl` use RFC 8785 canonical JSON serialization with SHA-256 predecessor hash chaining:
1. `IMPLEMENTED`: Functional code deployed in the repository.
2. `SIMULATED`: Computational outputs derived from classical mathematical models.
3. `MEASURED`: Observations captured directly from live physical hardware.
4. `REPRODUCED`: Independent replication confirming previously measured results.
5. `VERIFIED`: Formally validated claims satisfying all specification gates.
6. `UNRESOLVED`: Active hypotheses or experiments undergoing evaluation.
7. `FALSIFIED`: Hypotheses or claims explicitly refuted by empirical data.

*Bell State Fidelity Bound*: Physical measurements must be validated against the theoretical maximum fidelity bound:
$$F_{\text{max}} = 1 - \phi^{-8} \approx 0.9787$$

---

## 6. Enterprise Cloud Topologies & CI/CD Integrations (OSIRIS v4.5.0)

### 6.1. Migr8 6-Week Enterprise Pilot Framework
Commercial deployments follow a strict 6-week phased lifecycle governed by exit gates:

| Timeline | Migration Phase | Primary Activity | Deliverable Artifact | Exit Governance Gate |
| :--- | :--- | :--- | :--- | :--- |
| **Week 1** | **Discover** | Workflow selection, dependency mapping, baseline definition. | Pilot Specification v1 | **Gate 1**: GO / REVISE |
| **Week 2** | **Model** | DNA-Lang representation and policy boundary design. | Versioned `.dna` Genome & Hash | **Gate 2**: GOVERNANCE PASS |
| **Week 3** | **Execute** | Controlled execution and telemetry capture in sandboxes. | Initial Evidence Dataset | **Gate 3**: MEASUREMENT PASS |
| **Week 4** | **Evaluate** | Failure mode analysis, deterministic replay, integrity audits. | Evidence Ledger & KPI Report | **Gate 4**: EVIDENCE REVIEW |
| **Week 5** | **Reproduce** | Independent replay within clean baseline environments. | Reproduction Report | **Gate 5**: REPRODUCTION PASS |
| **Week 6** | **Validate** | Final recommendations, ROI evaluation, customer decision. | Evidence Package | **Gate 6**: CUSTOMER VALIDATION |

### 6.2. Google Cloud Platform (GCP) Topology & CI/CD Security
- **Cloud Run Execution**: Staging instances are severely restricted to 1GiB RAM, 1 vCPU, and `--max-instances=2` to mitigate denial-of-wallet vectors and agent resource runaway.
- **Vertex AI Gemini Integration**: When `OSIRIS_GCP_PROJECT` is set, LLM inquiries route via Vertex AI with IAM OAuth authentication, eliminating static API keys.
- **Secret Manager Integration**: When `OSIRIS_SECRETS_SOURCE=gcp` is active, configurations pool directly from Secret Manager targeting secrets labeled `osiris=env`. Plaintext secrets in source trees are eradicated.
- **Cloud Build (`cloudbuild.yaml`)**:
  - Executes parallel test matrices on Python 3.11 and 3.12.
  - Scans for leaked credential signatures (`sk-...`, `ibmq_...`).
  - Compiles immutable Docker containers tagged with the exact Git commit SHA. Zero-exit-code correctness is mandatory before container promotion.

---

## 7. The 5 Non-Negotiable Directives for AI Agents & Copilots

1. **Enforce Hardware Verification**: Actively detect the host platform (`Node Alpha` vs `Node Beta`) via `detect_substrate()` before proposing operations or execution paths. Never hardcode static paths.
2. **Respect AST Firewalls**: Reject dynamic code execution (`exec`, `eval`, `compile`) and never mutate immutable governance artifacts (`policy.json`, `tests/core_test.py`, `cloudbuild.yaml`, `QUARANTINE_NOTICE.md`).
3. **Ensure Cryptographic Provenance**: Format ledger entries using RFC 8785 canonical JSON and commit verifiable SHA-256 digests to the write-ahead ledger prior to promotion or execution.
4. **Maintain Epistemic Integrity**: Maintain strict separation between classical simulations and physical hardware observations. Never substitute mocked simulation data for empirical hardware claims.
5. **Acknowledge The Execution Boundary**: Operate purely as an unprivileged proposal engine subject to the Command Interposition Layer (CIL L0–L6). Deterministic code decides, measures, and records.
