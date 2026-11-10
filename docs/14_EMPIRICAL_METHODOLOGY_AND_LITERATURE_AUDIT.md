# 14. Empirical Methodology, Autonomous Systems, and Epistemic Source Audit

**Specification Identifier:** `OSIRIS-SPEC-MET-014`  
**Governing Standard:** OSIRIS Epistemic & Adjudication Framework  
**Status:** NORMATIVE  
**Last Updated:** 2026-10-02  

---

## 1. Overview and Scope

This document establishes the empirical methodology, benchmark gates, source validation standards, and comparative architecture analysis for autonomous research agents operating within OSIRIS. 

In keeping with the **Adjudication Engine** paradigm ([GOVERNANCE.md](file:///root/GOVERNANCE.md)), autonomous agents must reject self-reported vendor claims and narrative maximization in favor of deterministic controls, pre-registered statistical protocols, and isolated evaluators.

---

## 2. Comparative Analysis: Current Autonomous Science & Provenance Architectures

Autonomous discovery systems exhibit distinct memory, execution, and provenance topologies. OSIRIS synthesizes the verifiable components of these architectures while enforcing strict runtime boundaries:

| System / Standard | Architecture & Memory Topology | Reported Scale / Characteristics | Provenance & Adjudication Assessment |
|---|---|---|---|
| **Kosmos** (arXiv:2511.02824) | Structured world model shared between data-analysis and literature agents. | ~200 rollouts, ~42,000 LOC executed, ~1,500 papers read per run. | Relies on vendor preprint claims ("6 months of work" in 12 hours) based on subjective collaborator surveys. Lacks external cryptographic ledger. |
| **Edison** | Granular citation and execution mapping. | Every stated conclusion must trace to specific underlying code runs or literature. | Aligns with OSIRIS trace requirements; must be coupled with deterministic execution sandboxing. |
| **Co-Scientist** (Nature 2026) | Multi-agent shared context memory across specialized roles: Generation, Reflection, Ranking, Evolution, Proximity, Meta-review. | Validated in laboratory environments (Alphabet-funded). | Demonstrates strength of role-separated reflection and ranking; requires independent non-vendor verification. |
| **Voyager** | Executable skill library storing verified code modules. | Iterative skill accumulation in open-ended environments. | Verifiable and executable, but requires runtime sandbox confinement to prevent environment escape. |
| **Reflexion** | Verbal self-reflection stored in episodic memory. | Heuristic linguistic memory updates between trials. | Vulnerable to hallucinated progress without hard falsification signals or deterministic unit tests. |
| **W3C PROV-O** | Formal ontology defining `Entity`, `Activity`, and `Agent`. | Core relations: `wasGeneratedBy`, `used`, `wasAttributedTo`, `wasAssociatedWith`. | Standard foundation for scientific artifact tracking; mapped into OSIRIS evidence schemas. |
| **RO-Crate 1.2** (Rec. June 2025) | Research object packaging via schema.org JSON-LD. | Structured interchange of data, code, workflows, and metadata. | Target format for OSIRIS experiment and benchmark distribution packages. |
| **OpenLineage** | Operational runtime lineage specification. | Models `Job`, `Run`, and `Dataset` lifecycle events (mandatory `START` and `COMPLETE`/`FAIL`/`ABORT`). | Enforces lifecycle event completeness for all automated batch and hardware submissions. |

---

## 3. Empirical Verification Directives

### 3.1 LLM Critic Value & Recall Benchmarking
There is no rigorous peer-reviewed evidence that an LLM critic equipped with tool access provides recall gains over deterministic static analysis and verification checks in experimental physical science.

- **Empirical Gate:** Any tool-equipped LLM critic must be benchmarked against a **seeded-defect corpus** with and without tool access.
- **Retention Condition:** A tool-equipped critic is retained **only if** it demonstrates a statistically significant increase in defect recall without inflating the false-rejection rate relative to deterministic checks.
- If no measurable recall advantage is demonstrated, the critic is deprecated in favor of deterministic linters and test suites.

### 3.2 Calibration of Risk Tiers
Published calibration datasets for LLM-proposed risk tiers in scientific code modification do not currently exist.
- **Routing Standard:** Routing of code changes, execution privilege, and hardware access remains strictly **capability-derived and rule-based**.
- LLM self-assessed risk tiers are treated as `[UNSUPPORTED]` until local, empirical calibration data is collected and verified.

### 3.3 Reusable Holdouts at Small Sample Size ($n$)
Adaptive data analysis mechanisms such as **Thresholdout** (Dwork et al., Science 2015; NeurIPS 2015) provide differential privacy guarantees against overfitting, but their formal bounds are asymptotic and require large holdout pools ($n \gg 10^3$).

- **Small-$n$ Constraint:** In physical quantum hardware experiments, data is collected in tens of jobs due to queue latency and hardware cost ($n \sim 10^1 - 10^2$).
- **Direct Re-measurement Policy:** In small-$n$ hardware regimes, **budgeted fresh re-measurement** is statistically sound and practically superior to DP-noised reusable holdouts. Reusing small holdout sets with additive noise destroys physical signal resolution.

### 3.4 Hardware-Level Variance: IBM Heron Job-Level Drift vs. Shot-Level Noise
Quantum observable uncertainty cannot be characterized by shot pooling ($\sigma / \sqrt{S}$), which ignores time-dependent drift, cryostat thermal cycles, and calibration shifts.

- **Heron Observable Metrics:** For Dynamical Decoupling (DD) sequences and Greenberger-Horne-Zeilinger (GHZ) state parity observables on IBM Heron (e.g. Heron r2 / Fez):
  $$\sigma^2_{\text{total}} = \sigma^2_{\text{shot}} + \sigma^2_{\text{batch}} + \sigma^2_{\text{drift}}$$
- **Sample Size Requirement:** The $\ge 10$-jobs execution minimum is an empirical conservative starting baseline, not an analytical constant.
- **Empirical Quantification:** Between-job drift must be actively measured and back-filled from real hardware execution runs across independent calibration cycles before asserting fidelity thresholds or noise models.

### 3.5 Mutation Testing as a Non-Regression Gate
Mutation testing introduces synthetic faults to evaluate test suite thoroughness. Just et al. (FSE 2014) established that mutant faults couple with real faults in approximately 73% of cases. However, subsequent findings show this correlation weakens once test suite size is controlled.

- **Non-Regression Policy:** Mutation score shall **not** be used as an absolute percentage acceptance target.
- **Gate Rule:** Mutation score is deployed exclusively as a **non-regression gate**: any code commit or agent refactoring that reduces the mutation score relative to baseline is rejected.

### 3.6 Reward Hacking & Evaluator Confinement
Evidence of agent reward hacking, specification gaming, and unintended goal optimization stems largely from vendor preprints and evaluator technical reports (METR, Anthropic, OpenAI, Sakana). Independent replications (e.g. of Anthropic's emergent misalignment) have been only partial.

- **Architectural Directive:** Regardless of vendor narrative debates, the engineering necessity remains absolute: **Keep evaluators and reward functions strictly isolated from the agent's reach.**
- Agents must never have write access, execution modification privileges, or mock overrides for evaluation harnesses, scoring logic, test suites, or immutable ledgers.

### 3.7 AI-Scientist Claim Skepticism
Headline claims regarding autonomous "AI Scientists" are overwhelmingly self-reported by tool vendors:
- Kosmos's "6 months of human research time" claim is drawn from an unblinded survey of collaborator sentiment over 20-cycle runs (arXiv:2511.02824).
- The AI Scientist v2 workshop paper acceptance was one of three workshop submissions, and was subsequently withdrawn (arXiv).
- Co-Scientist's Nature validation was funded and directed by the vendor (Alphabet).
- **Independent Scrutiny:** Autonomous science systems must be judged against independent empirical evaluations (e.g., Beel et al., SIGIR Forum 2025; Luo et al., NeurIPS 2025), which consistently reveal significant failure modes in literature synthesis, hypothesis discrimination, and novel experimental derivation.

---

## 4. Epistemic Source Classification Hierarchy

When evaluating claims, prior work, or architectural designs, OSIRIS agents must classify references into the following epistemic source tiers:

```text
================================================================================
                     EPISTEMIC SOURCE CLASSIFICATION
================================================================================
 Tier 1: Peer-Reviewed & Archival Proceedings (Authoritative)
 Tier 2: ArXiv Preprints (Provisional / Technical Reference)
 Tier 3: Vendor Technical Reports & Evaluator Blog Posts (Heuristic / Unaudited)
 Tier 4: Secondary Sources & Unverified Claims (Quarantined)
================================================================================
```

### Tier 1: Peer-Reviewed Archival Publications
- **Huang et al.** (ICLR 2024) — LLM agent evaluation and capabilities.
- **Zheng et al.** (NeurIPS 2023 D&B) — LMSYS Chatbot Arena / Judge evaluation.
- **Dwork et al.** (Science 2015; NeurIPS 2015) — Reusable holdouts and Thresholdout algorithm.
- **Proctor et al.** (Nature Physics; PRL) — Quantum characterization, randomized benchmarking, and drift.
- **Gidney** (Quantum 2021) — Fault-tolerant quantum computing and circuit optimization.
- **Beel et al.** (SIGIR Forum 2025) — Independent empirical evaluation of academic search and agent retrieval.
- **Luo et al.** (NeurIPS 2025) — Systematic evaluation of LLM scientific reasoning.
- **CaMeL** (SaTML 2026) — Robustness and security boundaries in machine learning systems.
- **Co-Scientist** (Nature 2026) — Autonomous multi-agent scientific reasoning.
- **Just et al.** (FSE 2014) — Coupling of mutants to real software faults.
- **OOPSLA 2025 Property-Based Testing Study** — Empirical effectiveness of randomized property checks.

### Tier 2: Preprints (Technical Reference, Provisional)
- **Kosmos** (arXiv:2511.02824)
- **DGM** (Darwinian Genetic Model, arXiv:2505.22954 v3; SWE-bench 20.0% to 50.0%, Polyglot 14.2% to 30.7%)
- **AI Scientist v2** (ICLR 2025 workshop presentation; subsequently withdrawn)
- **Anthropic Emergent Misalignment** (arXiv preprint)
- **OpenAI Chain-of-Thought Monitoring** (arXiv preprint)
- **ScientistOne** (arXiv preprint)
- **"Stop Overvaluing MAD"** (arXiv preprint on multi-agent debate)

### Tier 3: Vendor & Evaluator Reports (Heuristic / Subject to Audit)
- **METR** evaluation reports
- **Sakana AI** lab blog posts
- **OpenAI** research notes
- **Google DeepMind** announcements

### Tier 4: Secondary or Unverified Claims
- Secondary citations without primary journal/conference verification (e.g., secondary reports regarding Robin).
- *Rule:* Any parameter or capability asserted from Tier 4 sources must be tagged `[UNSUPPORTED]` until validated against Tier 1 or primary experimental observation.

### Inline Linking Convention
All module documentation and experiment pre-registrations referencing preprints must provide inline arXiv IDs (e.g., `arXiv:2511.02824`) to ensure direct lineage tracing through the OSIRIS citation layer.
