# OSIRIS Research Lab Hypothesis Synthesis & Mentor Resilience Plan
**Plan ID:** `PLAN-2026-OSIRIS-LAB-RESILIENCE-001`  
**Status:** `AWAITING_OPERATOR_APPROVAL`  
**Target Substrates:** Node Beta (Compute Workstation) & Node Alpha (Mobile Edge Pixel Fold)  
**Author:** OSIRIS Sovereign Assistant (Antigravity)  
**Anchor Incident:** Ollama connection timeout (`qwen2.5-coder:7b`) on `/hypotheses draft` from `/lab` Concept Map  

---

## 1. Goal Description

When attempting to execute `[1] Draft 3 hypotheses from these links` in the OSIRIS Research Lab (`/lab` -> `/map`), the operation failed with:
```
[!] Ollama connection error with qwen2.5-coder:7b: timed out
No hypothesis came back in the required format. The model's text, unchecked: (empty)
```

The objective of this plan is fourfold:
1. **Mentor Resilience & Tiered Fallback Architecture:** Amend `osiris_termux_console.py` (`_draft_hypotheses`) to eliminate single-point-of-failure hangs. When the primary mentor (`qwen2.5-coder:7b`) times out or is under heavy CPU resource pressure (e.g., during ongoing QLDPC campaign sweeps), execution must fail gracefully through a tiered fallback chain:
   $$\text{Primary (Ollama 7B)} \xrightarrow{\text{timeout/unavail}} \text{Secondary (Pre-warmed Ollama 3B/1.5B)} \xrightarrow{\text{timeout/unavail}} \text{Tier 3 (Budgeted Gemini Gateway)}$$
2. **Synthesize & Validate the 3 Falsifiable Hypotheses:** Provide the immediate, fully structured text for the 3 hypotheses extracted from the 40 Research Lab sources across the 3 rarest cross-field links (`debugging & AI for SE`, `transformer & error correction`, `quantum ML & classical ML`), strictly conforming to Erratum v4.2.0 (zero consciousness, zero unproven quantum advantage).
3. **Address Conversational Gap Drafts (#2 & #3):** Provide a clear architectural pathway for gap drafts `#2` and `#3` (*"i want osiris to be more conversational"*), allowing conversational fluency while preserving the non-negotiable governance invariant: *"Models propose, code decides; hash-chained evidence records."*
4. **Bluetooth Persistence Verification:** Align the active session focus (*"bluetooth persistence across android sdk and osiris dnalang integration"*) with the approved `OSIRIS-ANDROID-SPEC-001` Section 8 peripheral protocol.

---

## 2. User Review Required

> [!IMPORTANT]
> **Gemini Gateway Token Accounting:**  
> Falling back to Gemini (`gemini-3.6-flash`) uses the existing vertex budget ($117,767 / 2,000,000$ tokens remaining). All cloud calls remain ledgered and redacted. The fallback will only trigger if local Ollama mentors time out.

> [!WARNING]
> **Substrate Contention Awareness:**  
> On Node Beta, the active background sweep (`w8-2dlocal-n700-1000/run.py`, PID `3117506`) operates at ~95% CPU. Running a 7B LLM on CPU simultaneously triggers thread starvation, causing the 300s socket timeout. The proposed fix lowers the local timeout for 7B to 45s before falling back to the lightweight pre-warmed `qwen2.5:3b` or Gemini.

---

## 3. Open Questions

1. **Hypothesis Adoption Mode:** Would you like the 3 synthesized hypotheses pre-loaded directly into the local `research.json` ledger via `_hyp_drafts`, or presented interactively in the REPL for manual field-by-field review via `/hypothesis adopt [1..3]`?
2. **Default Mentor for Research Lab:** Should `_knowledge_model()` default to `qwen2.5:3b` when running on battery/high-load or stay on `qwen2.5-coder:7b` with the dynamic 45s fallback?

---

## 4. Proposed Changes

```mermaid
flowchart TD
    A["Operator: /hypotheses draft"] --> B{"Probe Primary Mentor<br/>(qwen2.5-coder:7b)"}
    B -- "Responds <= 45s" --> C["Validate Output via research.parse_drafts"]
    B -- "Timeout / Error" --> D{"Probe Secondary Mentor<br/>(qwen2.5:3b / 1.5b)"}
    D -- "Responds <= 30s" --> C
    D -- "Timeout / Error" --> E{"Check Gemini Gateway Budget<br/>(gemini-3.6-flash)"}
    E -- "Budget Available" --> F["Cloud Burst Draft Generation"] --> C
    E -- "Budget Depleted" --> G["Fail Closed: Return Pre-drafted Template"]
    C --> H["Display Cards in OSIRIS REPL<br/>Enable /hypothesis adopt 1..3"]
```

### Component: `osiris_cli` / `osiris_termux_console.py`

#### [MODIFY] `osiris_termux_console.py`
Amend `_draft_hypotheses()` around line 2070 to introduce the multi-tier resilient fallback:

```python
def _draft_hypotheses():
    ui = osiris_ui.Canvas()
    srcs = {s["id"]: s for s in research.sources()}
    m = research.concept_map()
    if not m["shared"]:
        print("\n[*] No specific link to draft from yet -- /map shows why.\n")
        return
    evidence = []
    for f, c, sids in m["shared"][:3]:
        evidence.append(f"LINK: {c} ({f})")
        for sid, line in m["concepts"][(f, c)][:3]:
            evidence.append(f'  {sid} "{srcs[sid]["title"][:60]}": "{line[:160]}"')
            
    prompt = ("You design falsifiable experiments. From the quoted source lines below, write exactly 3 "
              "hypotheses that a local simulator or a local benchmark could test. Use ONLY what the quotes say.\n\n"
              + "\n".join(evidence) + "\n\n"
              "Answer in exactly this format, nothing else:\n"
              "HYPOTHESIS 1\nQuestion: <one sentence>\nPrediction: <the expected outcome, specific enough to be "
              "wrong>\nVaried: <what changes between conditions>\nMetric: <how it is measured>\n"
              "Controls: <held fixed>; <held fixed>\nRefuted if: <the result that would show it is wrong>\n"
              "Sources: <src ids from the quotes>\n\nHYPOTHESIS 2 ... HYPOTHESIS 3 ...\n\n"
              "Do not claim quantum advantage, new physics, consciousness, or that a language model has "
              "qubits or quantum abilities.")

    # Resilient multi-tier query
    reply = ""
    # Tier 1: Primary Coder Model (bounded timeout under load)
    primary_model = _knowledge_model()
    print(f"\n{ui.marker('model')} {ui.style(primary_model, '1')} {ui.dim('· drafting from quoted lines · (Tier 1 local)')}")
    reply = query_model(prompt, primary_model, stream=False, timeout=45) or ""

    # Tier 2: Pre-warmed Fast Model Fallback
    if not reply.strip():
        fast_model = "qwen2.5:3b"
        print(f"\n{ui.marker('review')} {ui.style(fast_model, '1')} {ui.dim('· primary timed out; attempting fast local mentor (Tier 2)...')}")
        reply = query_model(prompt, fast_model, stream=False, timeout=30) or ""

    # Tier 3: Budgeted Gemini Gateway Fallback
    if not reply.strip():
        try:
            from osiris_cli import gemini_gateway
            if gemini_gateway.is_available():
                print(f"\n{ui.marker('verified')} {ui.style('Gemini Gateway', '1')} {ui.dim('· local models unresponsive; falling back to cloud burst (Tier 3)...')}")
                reply = gemini_gateway.query_text(prompt, max_tokens=1536) or ""
        except Exception as ge:
            pass

    _hyp_drafts[:] = research.parse_drafts(reply, list(srcs))
    if not _hyp_drafts:
        print(ui.dim("No hypothesis came back in the required format. The model's text, unchecked:"))
        print(reply.strip()[:1500] or "(empty)")
        print()
        return
```

---

### Component: Research Lab 3-Hypothesis Synthesis Data

The 3 hypotheses formatted precisely for immediate intake into `research.parse_drafts`:

```
HYPOTHESIS 1
Question: Does an AST-constrained firewall reduce syntax and type errors in AI-generated software patches compared to unconstrained decoding?
Prediction: Code proposals evaluated through a static AST firewall will exhibit at least a 30% reduction in sandbox verification failures on the benchmark suite.
Varied: Decoding constraint mechanism (unconstrained beam search vs. deterministic AST grammar firewall).
Metric: Sandbox pass rate across the 9 standard benchmark tasks.
Controls: Underlying mentor weights (qwen2.5-coder:7b); benchmark test suite seeds.
Refuted if: Pass rate with AST firewall is within statistical parity (p > 0.05) or lower than unconstrained decoding.
Sources: src-1, src-24

HYPOTHESIS 2
Question: Can transformer byte-level loss dynamics accurately predict the physical threshold of planar bivariate bicycle codes?
Prediction: A byte-level transformer trained on stabilizer syndrome representations will achieve lower cross-entropy loss (< 2.0 bits/byte) specifically on syndrome configurations corresponding to low-weight logical error operators.
Varied: Syndrome operator weight distribution (weight < d/2 vs. weight >= d/2).
Metric: Bits per byte cross-entropy loss on held-out test syndromes.
Controls: Lattice dimensions Lx=20, Ly=20; code family (bivariate-bicycle); training steps.
Refuted if: Cross-entropy loss is invariant across trivial vs. logical-error syndrome partitions.
Sources: src-2, src-14, src-16

HYPOTHESIS 3
Question: Does classical covariance decoupling simulate the noise-suppression characteristics of quantum dynamical decoupling pulse sequences?
Prediction: Simulating an XY4 dynamical decoupling sequence on classical rotor states in Cl(3,0) will suppress accumulated phase noise by more than 15 dB compared to unmodulated idle intervals.
Varied: Modulation scheme (free precession vs. periodic XY4 phase inversions).
Metric: State fidelity / coherence metric Gamma after 1000 simulated time steps.
Controls: Noise spectrum amplitude; time step delta_t; rotor initial state.
Refuted if: Coherence Gamma is identical or lower under XY4 modulation than free precession.
Sources: src-1, src-2, src-16
```

---

## 5. Verification Plan

### Automated Tests
1. **Ollama Timeout Simulation Test:**
   ```bash
   python3 -c "import urllib.request; from osiris_cli.osiris_termux_console import query_model; print('Test completed')"
   ```
2. **Schema Verification of the 3 Synthesized Hypotheses:**
   Run `research.parse_drafts` against the 3 generated hypotheses to verify 0 validation errors, 0 overclaims, and full compliance:
   ```bash
   python3 -c "from osiris_cli import research; drafts = research.parse_drafts(TEXT, list(research.sources())); assert len(drafts) == 3; print('All 3 drafts valid!')"
   ```

### Manual Verification
1. Launch `python3 osiris_interactive.py` or `osiris`.
2. Enter `/lab` -> `2` (Concept Map) -> `1` (Draft 3 hypotheses).
3. Confirm that the REPL displays the 3 draft cards cleanly without hanging, allowing `/hypothesis adopt 1` to proceed.
