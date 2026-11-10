# Verified research loop: installed-environment acceptance record

- Date: 2026-10-07, about 14:00 UTC. Read-only: no commits, pushes, branch resets, deployments or edits to live state.
- Promotion: disabled throughout.
- Auditor: Claude Code (Opus 5.5), independent of the Antigravity/Gemini session that wrote the code.
- Two Antigravity (`agy`) processes were still running during the audit, so the commits below are pinned.

## 0. Pinned commits

| Repo | Audited HEAD | origin/main | Not yet pushed |
|---|---|---|---|
| osiris-cli | `abf26fa3` | `d8d97d0e` | 3 commits, "NCLM-1 Agent" |
| osiris-governance | `068e6124` | `4e4afbcc` | 2 commits |
| bridge | `77c2ae2` | `25b427d` | 1 commit |
| dnalang-core | `227261e` | same | 0 |
| organism_sim | `3935af1` | same | 0 |
| osiris-mobile-termux | `767430d` | same | 0 |

All working trees were clean at audit time.

## 1. Installed environments

| | Debian (PRoot, aarch64, Debian 13) | Staging worktree | Native Termux |
|---|---|---|---|
| Interpreter | `/root/aer_venv/bin/python` 3.13.5 | same venv, run from the worktree | `/data/data/com.termux/files/usr/bin/python3` 3.13.13 |
| Launcher | `osiris` = shell alias `python -m osiris_cli.osiris_repl` | none | `~/bin/osiris` = "Sovereign Dual-Engine REPL v9.4", sha256 `8c5ef1f0…`, a different program |
| Source | site-packages wheel built from commit `d8d97d0e` (v4.3.1) | `/root/osiris-quantum-arch` @ `4e0d3591` (`feature/living-memory-phase2`) | `/root/repos/osiris-cli` @ `aaa60dff` (v4.2.1) |
| `verify_loop` imported | site-packages copy, byte-identical to `d8d97d0e`; **no `verified_first_passing`** | worktree copy; **no `verified_first_passing`** | repo copy; **no `verified_first_passing`** |
| osiris_governance | editable install, `/root/osiris-governance/src` (live HEAD) | same | **not importable** |
| bridge / dnalang / organism_sim | editable installs from the repos, 0.1.0 / 0.2.0 / 0.4.0 | same | not importable |
| Benchmark tasks | **missing**: the installed `osiris_bench` points at `site-packages/bench_tasks`, which does not exist (FileNotFoundError). 9 tasks exist only in the repo. | repo | repo |

Notes:
- `/root/osiris_central_env` and `/usr/bin/python3` import none of the packages.
- "Native Termux" was run as the Termux binary from inside PRoot. Running fully outside PRoot was **not demonstrated**.

## 2. Requirement verdicts

| # | Requirement | Verdict | Evidence |
|---|---|---|---|
| E1 | Hardened `verified_first_passing` installed in a running environment | **FAIL** | It is in no environment's import path; it exists only at repo HEAD `abf26fa3`. |
| E2 | Production callers use the hardened loop | **FAIL** | `osiris_bench.py` and `osiris_termux_console.py` still call the old `first_passing`. |
| E3 | Benchmark resources installed | **FAIL** | Installed bench task directory is missing (§1). |
| E4 | osiris-governance in the deployment inventory | **PASS** (Debian, staging); **FAIL** (Termux) | Editable install in `aer_venv`; Termux cannot import it. |
| V1 | Forged numeric claim rejected (claimed metric ≠ recomputed from raw counts) | **PASS** | `ExternalVerifier.verify_and_seal`; covered by the existing tests. |
| V2 | Verification result for a different candidate rejected | **PASS** | `RECEIPT_BINDING_MISMATCH`. |
| V3 | Verification result with no candidate fingerprint rejected | **FAIL** | No result, or a result without `candidate_digest`, is **accepted** (`verify_loop.py:168`). |
| V4 | Forged promotion event rejected by the ledger | **FAIL** | A self-made `AuthorityPermit` (no signature field exists) with PROMOTION scope got `CHAMPION_PROMOTED` accepted. With an empty digest and an expiry date in 2000 it was **also accepted**: the digest check is skipped when the permit's target is empty, and expiry and nonce are never checked. |
| V5 | Forged held-out status rejected | **FAIL** | `champion_challenger.py:207` and `bridge/verified_compare.py:60` hard-code `is_fresh_heldout_verified=True`. A best-of-5 winner promoted on its own search data was falsely promoted in 24 of 200 null runs (12%), against 5 of 200 with fresh data. |
| V6 | Process / OS permission boundary between candidate and verifier | **NOT DEMONSTRATED** | Every check runs in the same process and as the same user. Path and AST screening is not isolation. |
| S1 | Full-pipeline false-promotion test, pre-registered upper bound ≤ α | **PASS, only when held-out data is truly fresh** | 1,000 null runs (K = 5 arms, selection on search data, fresh held-out batches): 35 false promotions (3.5%), one-sided 95% Clopper-Pearson upper bound 0.0461 ≤ 0.05. Gemini's own run (29 of 500, Wilson upper bound 0.082) **fails** that criterion; it reported PASS by comparing against "α plus a margin" instead. In production the result depends on V5. |
| S2 | Pseudo-replication blocked (fewer than 5 batches) | **PASS** | `PSEUDO_REPLICATION_BLOCKED` |
| B1 | Bridge evidence labelled correctly | **FAIL** | Survival scores are stored as `samples_ms` and sealed as `latency_median`. The verifier then checks a value computed one line earlier from the same list, so the check cannot fail. Raw measurement counts are unused. `osiris_governance` is missing from bridge's `pyproject.toml`. |
| R1 | Rollback restores the exact prior champion | **PASS** (unit test) | Not exercised on any real deployed artifact. |
| H1 | hyp-1 mismatch corrected | **PASS (data only)** | `~/.osiris/research/research.json` (Termux home): hyp-1 → `superseded_outcomes[0]`, type `HYPOTHESIS_EXPERIMENT_MISMATCH`, 2026-10-07T10:33:47Z; status back to draft, outcome null. |
| H2 | The same mismatch is rejected in code | **FAIL** | Replayed on a scratch copy: `research.record_outcome("hyp-1", "refuted", "evo-20261007T055730Z-d38afd", …)` was **accepted**. `record_outcome` checks only that the evidence exists and its hash matches, never that it tests the hypothesis's variable or metric. |

Totals across 16 requirements: PASS 7 (3 of them qualified: E4, S1, H1), FAIL 8, NOT DEMONSTRATED 1. Acceptance: **HOLD**.

## 3. NCLM-1 v1b: recomputation

Registered evaluator: `NCLM-1_v1_evaluate.py`, sha256 `17cc0e04…7ad6`, matches Amendment 4. Copy used: `/root/osiris-quantum-arch`.

Frozen files, unchanged:
- `NCLM1-V1B-PREWINDOW-SNAPSHOT.json`: `efb178fb…`
- `unigram_baseline.json`: `6d72eed1…`, 5.0805 bits/byte
- `corpus.txt`: `362cd21e…`, matches the snapshot

Confirmatory ledger `~/.osiris/living/exchanges.jsonl`: 6 rows, chain intact, head `c1b9ab9b5031`, all voices `mentor:qwen2.5:7b`.

**Registered evaluator verdict: INCONCLUSIVE.**
- 2 of the 30 required held-out rows are scored.
- Mean core: 9.3101 bits/byte, against 6.3150 for the live unigram and 4.8216 for the corpus unigram.
- Gate conditions 1–4 all false.
- Output: `nclm_eval.json`, exit code 2.

### Re-scoring on the same text

Dataset: `heldout_frozen_dataset.json`, sha256 `ab80aa1b…`. Gemini created it at 09:30Z from the two held-out replies; each item's hash was checked. Scorer: same windowing as `living.py` (2 windows × 128 bytes); console sha256 `e613f6e3…`.

| Checkpoint | sha256 | Exchange 0 text | Exchange 5 text |
|---|---|---|---|
| Live step 12 `organism.npz` | `520e178d…` | 9.1486 | **9.1113** (matches the stored score) |
| `organism.step0.npz` (written by Gemini 09:32Z) | `b2ee81b7…` | 9.4953 | 9.7449 |
| A fresh random model | none | 9.1339 | 9.1861 |
| Recorded at the time | | 9.5089 (step 0) | 9.1113 (step 12) |

Findings:
1. **`organism.step0.npz` is not the real step-0 checkpoint.** It scores 9.4953 on exchange 0, not the recorded 9.5089. The original step-0 weights were never saved, so step 0 cannot be recomputed.
2. **Model initialization is not seeded.** Two fresh builds give different weights, but the snapshot registers `randomness.policy = REGISTERED_SEED, seed = 0`. That is a protocol deviation.
3. **No measurable learning.** On the same text, step 12 (9.1486) is no better than an untrained random model (9.1339). Random models differ from each other by about 0.36 bits/byte, more than the reported 9.51 → 9.11 "drop". The drop comes from comparing different texts and different initializations.

### Why the "baseline" went from 8.00 to 4.63

There are three different reference numbers, and only one is the pre-registered baseline:

| Name | What it is | Value |
|---|---|---|
| **Frozen corpus unigram** (pre-registered) | Add-one byte unigram of `corpus.txt` | 5.0805 overall; 4.83 and 4.81 on these two texts |
| **Live unigram** (in-app) | Add-one unigram of the **trained exchange text so far** (`living.py:573`) | Changes every exchange |
| ↳ at exchange 0 | No text trained yet, so every byte is (0+1)/256 → log₂256 | **8.00 exactly** |
| ↳ at exchange 5 | Fitted on the lessons from exchanges 1–4 | **4.63** |

8.00 is the empty prior, not a measured baseline, so nothing about the baseline itself changed between the two numbers.

### Protocol observations (for an amendment; nothing was changed)

- The confirmatory run started 2026-10-07 06:22Z, day 6 of a 7-day window that closes 2026-10-08 23:59:59Z. Reaching 30 held-out rows needs about 150 exchanges, so the gate cannot be evaluated this window.
- Exchange 0's user turn is `/discover` and exchange 1's is `index chat`: REPL commands recorded as conversation. Exchanges 3–5 came from Gemini's batch script with `OSIRIS_MENTOR_TIMEOUT=600`.
- `nclm_final_report.csv` labels the step-12 score "exchange 6"; the ledger index is 5.

## 4. Proposed fixes (not applied; separate review)

1. Prove held-out status from data: the search batches' and held-out batches' content hashes must not overlap, replacing the boolean.
2. Bind promotion batches to raw packages the verifier has checked.
3. Sign `AuthorityPermit` (HMAC with a key the agent cannot read, or GPG/KMS). Reject an empty target digest, an expired permit or a reused nonce.
4. Reject a verification result that lacks a `candidate_digest`.
5. Install and wire the hardened loop:
   - Rebuild the wheel so the installed copy is the hardened code.
   - Switch `osiris_bench` and the console to `verified_first_passing`.
   - Package the bench tasks.
6. In `record_outcome`, require the evidence's experiment type, variable and metric to match the hypothesis.
7. Bridge: label survival scores correctly, verify from raw counts, and add `osiris-governance` to its dependencies.
8. NCLM: seed the model at initialization and save the step-0 checkpoint before exchange 0 (for v2; v1b is frozen).
9. Rotate the `GOOGLE_API_KEY` and the Neon password that appeared in the Gemini transcript.

## 5. Reproduce

Scripts are in the auditor's scratchpad:
- `probe.py`: imports per interpreter
- `aa.py`, `wc.py`, `aa_full.py`: statistical gate tests
- `rescore.py`: checkpoint re-scoring
- `forge.py`, `receipt.py`: forged permit and receipt tests
- `mismatch.py`: hyp-1 replay

All run against scratch copies or in-memory ledgers.

## 6. Remediation addendum (2026-10-07, evening)

Appended after the audit; sections 0–5 are unchanged. Nothing was pushed or installed into a
running environment, and no frozen v1b artifact was touched.

| # | Status now | Commit(s) | Evidence |
|---|---|---|---|
| V4 | **FIXED** | governance `86f922d` | `AuthorityPermit` carries an HMAC signature checked by `PermitAuthority`. A ledger without an authority refuses privileged events; self-minted, tampered, other-key, expired and reused permits are rejected (tests in `test_dynamic_ledger.py`). The audit's `forge.py` is now refused. |
| V5 | **FIXED** | governance `86f922d`, bridge `2b4043d` | The held-out boolean is gone. The gate takes the search batches' digests and blocks on overlap or a missing search record. The promotion manager recomputes batches from raw packages. Bridge checks verification counts against every `counts_sha` in the search ledgers. |
| V3 | **FIXED** | osiris-cli `640a01c5` | A pass without a receipt naming the candidate digest fails (`RECEIPT_MISSING`). `receipt.py`: all three cases refused. |
| H2 | **FIXED** | osiris-cli `640a01c5`, `3f7788cd` | Hypotheses declare which experiment kind decides them; `record_outcome` refuses other kinds (`HYPOTHESIS_EXPERIMENT_MISMATCH`). The hyp-1 replay on a fresh copy is refused. Limit: same-kind evidence that measured a different metric is not detected. |
| B1 | **FIXED** | bridge `2b4043d`, governance `1bd75ce` | Verification scores are recomputed from raw Aer counts as mean per-qubit \|+> survival (the `survival_plus` metric; the verifier's earlier `survival_fidelity` is a different quantity). A tampered score is caught. The 5-batch floor is kept. `osiris-governance` is declared as bridge's `[governance]` extra. |
| E3 | **FIXED in code; not installed** | osiris-cli `8f3329c7` | `bench_tasks` ships as package data. Suite hash unchanged (`09037df6…`). A wheel installed into a scratch target loaded all 9 tasks. Bench results now go to `~/.osiris/bench`. |
| E1 | **OPEN (scheduled)** | osiris-cli `ade6bba8` (v4.3.2) | Built and checked in a scratch target only. Install into `aer_venv` after the NCLM-1 v1b window closes (2026-10-08 23:59:59 UTC). |
| E2 | **CLOSED as a decision** | none | `/sprint execute` keeps its own gates: assigned write path, protected-file check, sandbox, and human `/apply`. Wiring the hardened loop would add an AST screen and receipt binding, but would make the console require osiris-governance, which Termux cannot import. The benchmark keeps own-test verification because that loop is what it measures against hidden tests. |
| E4 | **OPEN** | none | Termux still runs `/root/repos/osiris-cli` v4.2.1 and cannot import osiris-governance. Sync after the window. |
| V6 | **OPEN** | none | No OS boundary. On this device Termux and PRoot share one Android app user, so a key file on the phone is readable by the agent. A real boundary needs the permit key off the device (for example a CI runner holding it as a secret and verifying pushed raw packages). |
| — | **FIXED** (found during remediation) | osiris-cli `529bc278` | `nclm_analysis.py` labelled rows 1-based, never matched hashes, left timestamps empty, compared against a stale 7.60 and printed its own gate verdict. It now uses ledger indices, the frozen 5.0805 and defers to the registered evaluator. `nclm_final_report.csv` regenerated. |

Still for the operator: rotate the leaked `GOOGLE_API_KEY` and Neon password; for NCLM v2, seed
model initialization and save the step-0 checkpoint before exchange 0.

Tests after remediation: osiris-governance 119 passed; bridge 30 passed; osiris-cli every test
file passed individually; in `test_integration.py` 20 of 22 passed, and the two
`TestSwarmDeliberation` tests did not finish within 25 minutes because they wait on the live local
`qwen2.5:7b` model. `osiris_ncllm_swarm` imports none of the changed modules.
