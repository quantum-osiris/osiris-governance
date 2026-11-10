# W8L-1 Campaign Deposit Package & Evidence Ledger
**Campaign ID:** `w8-2dlocal-n700-1000`  
**Grant Authorization:** `GRANT-W8L-002` (`authorized-operator`)  
**Substrate:** Node Beta (Compute Workstation · Intel Core Ultra 7 256V / WSL Ubuntu)  
**Execution Timestamp:** 2026-10-11T15:03:04Z to 2026-10-11T16:36:07Z UTC  
**Deposit Status:** `SEALED_AND_READY_FOR_DEPOSIT`  

---

## 1. Executive Summary & Verification Gates (R1–R15)

The bounded 50-candidate research sweep for **`w8-2dlocal-n700-1000`** has finished with **exit code 0** under strict isolation.

| Gate | Requirement | Evidence / Metric | Verification Status |
| :--- | :--- | :--- | :--- |
| **R1** | Repository Integrity | Commit `0d9808ed317ea270ba190f0b5238fb7df0c3e337`; 0 tracked file modifications | **PASS** |
| **R6** | Locality Classification | Bilayer 2D grid coordinates; verified via `boundary_engine` / `planar.py` | **PASS** |
| **R10**| Pareto Dominance | Exact distance verification against leaderboard; Claims Firewall (SYS-024) active | **PASS** |
| **R11**| Payload Authorization | SHA-256 `08b8848b6d4ba6c0e4d811cb5b130939efd496b9c6bd4ccf144deb319607929d` | **PASS** |
| **R12**| Harness Isolation | Isolated staging directory `GRANT-W8L-002-node-beta`; zero board repository leaks | **PASS** |
| **R13**| Restart Safety | Write-ahead append-only journal (`journal.jsonl`) flushed with fsync | **PASS** |
| **R14**| Deposit Schema | `summary.json`, `manifest.json`, `REPORT.md` conform 100% to `campaign.schema.json`| **PASS** |
| **R15**| Frozen-State Auth | Approved under `GRANT-W8L-002` by authorized operator | **PASS** |

---

## 2. Resource Accounting & Budget Ledger

| Metric | Authorized Ceiling | Consumed | % Spent | Margin Remaining |
| :--- | :--- | :--- | :--- | :--- |
| **Candidates Screened** | 50 | **50** | **100.0%** | 0 (Clean stop condition) |
| **CPU Hours** | 24.000 h | **1.4814 h** | **6.17%** | +22.5186 h |
| **Walltime Hours** | 24.000 h | **1.5501 h** | **6.46%** | +22.4499 h |
| **GPU Hours** | 0.0 h | **0.0 h** | **0.0%** | 0.0 h |

---

## 3. Empirical Results & Findings

- **Total Candidates Evaluated:** 50
- **Valid Planar Codes Screened:** 40
- **Out-of-Bounds Disqualifications:** 10 (Weight $w=12 > 8$, correctly rejected at boundary filter)
- **Surviving Leaderboard Advances:** 0 (All 40 evaluated codes exhibited boundary gauge rank collapse or logical distance $d < 8$, logged as negative results)
- **Scientific Conclusion:**  
  *The bivariate bicycle base pairs under seed 101 on planar bilayer open-boundary lattices in the range $n \in [700, 1000]$ do not support unquarantined distance advances without secondary boundary gauge stabilization. All 50 negative controls have been durably preserved in the research ledger to eliminate redundant future computational expenditure.*

---

## 4. Cryptographic Artifact Manifest

| File | Relative Path | SHA-256 Digest |
| :--- | :--- | :--- |
| **Campaign Definition** | `research/campaigns/w8-2dlocal-n700-1000/campaign.json` | `6baf0b9d087e2241fc6743d4949bca8cae5c9ca9a67e56b005a61be721c59783` |
| **Runner Script** | `research/campaigns/w8-2dlocal-n700-1000/run.py` | `8e3743d89314ef56770354d23241a516239bf48b8856ec653be6646906ec2007` |
| **Write-Ahead Journal** | `research/campaigns/w8-2dlocal-n700-1000/journal.jsonl` | `78f898b1cc85c5588edd32cd66399abf561b9765c79f31c10c8da45e41f1f25b` |
| **Execution Manifest** | `research/campaigns/w8-2dlocal-n700-1000/manifest.json` | `cafb7f79aaadecdd3fdbc7d9ef0e9bb67eebd004d26cb8cd727f73e0a74beb75` |
| **Campaign Summary** | `research/campaigns/w8-2dlocal-n700-1000/summary.json` | `e5b9782f29be1b0ee4f0d711760a5cb3719615e677502bdd956f688977642f6c` |
| **Human Report** | `research/campaigns/w8-2dlocal-n700-1000/REPORT.md` | `6dbde9881a29fc66e0016db43999757e5aa1f71daf5d4a1bee811baa0f1bb657` |

---

## 5. Next Actions for Deposit

The campaign outputs are completely contained within `research/campaigns/w8-2dlocal-n700-1000/`.  
When ready, the operator can:
1. Stage the completed campaign report and ledger:
   ```bash
   git add research/campaigns/w8-2dlocal-n700-1000/
   git commit -m "research(w8-2dlocal): record 50-candidate negative results under GRANT-W8L-002"
   ```
2. Archive or clean up the isolated candidate staging directory `research/candidates/GRANT-W8L-002-node-beta/`.
