# OSIRIS 8-Gate Release Target Architecture

**Classification:** Architectural Target Specification  
**Document ID:** `OSIRIS-REL-TARGET-ARCH-V1`  
**Status:** Target Architecture & Implementation Register  
**Governing Standard:** OSIRIS Adverse-First Monotonic Gating  
**Last Updated:** 2026-09-27T11:22:00Z  

---

## 1. Architectural Philosophy

The OSIRIS release pipeline is structured as an **8-gate monotonic filtration system**. Rather than acting as a checklist where failures can be offset by high scores elsewhere, the architecture enforces strict authority contraction:

$$\text{Eligible}_{i+1} \subseteq \text{Eligible}_{i}$$

If any gate $i$ evaluates to `FAIL` or `BLOCKED`, pipeline progression halts immediately:

$$\mathbf{G}_i = \text{FAIL} \implies \text{Release Status} = \text{BLOCKED}$$

This document formalizes the 8-gate release process as a **target architecture**, explicitly identifying the concrete implementation status of every control to prevent speculative overstatement.

---

## 2. Master 8-Gate Specification Matrix

| Gate | Gate Name | Target Control Objective | Concrete Verification Mechanism | Artifact Generated | Current Implementation Status |
|:---:|---|---|---|---|:---:|
| **G-01** | **Secret & Exposure Detection** | Block repository inclusion or build-time exposure of credentials. | Layered scanning: regex, Shannon entropy, Trufflehog/Gitleaks, pre-commit hooks. | `SECRET_SCAN_REPORT.json` | `IMPLEMENTED_LOCAL` (Local regex scanner and sanitized tokens; CI hook proposed) |
| **G-02** | **Source & Schema Validation** | Ensure AST safety, schema compliance, and dependency integrity. | Python AST parse, JSON schema validation, dependency vulnerability audit. | `SOURCE_AUDIT_REPORT.json` | `IMPLEMENTED_TESTED` (AST checks, RFC 8785 canonical JSON validation) |
| **G-03** | **Offline Test Consistency** | Verify local code correctness and contract compliance. | Pytest test execution across unit and integration suites (`osiris-governance` + `fold`). | `PYTEST_RESULTS.json` | `IMPLEMENTED_TESTED` (75/75 governance + 52/52 fold tests passing) |
| **G-04** | **Deterministic Image Build** | Produce an immutable container image anchored to an exact cryptographic digest. | Docker build with pinned base image; extract `sha256:...` digest; generate CycloneDX SBOM. | `BUILD_PROVENANCE.json` & Image Digest | `PROPOSED_TARGET` (Dockerfile exists; digest promotion workflow specified) |
| **G-05** | **Artifact & Image Analysis** | Verify container vulnerability posture and base image integrity. | Google Artifact Analysis / Trivy scanning for CVEs; check policy thresholds. | `VULN_SCAN_SUMMARY.json` | `PROPOSED_TARGET` (Pending deployment environment configuration) |
| **G-06** | **Runtime Posture & IAM Boundary** | Enforce least-privilege IAM and Cloud Run configuration. | Inspect deployer vs runtime service account bindings; verify ingress and secret mounting. | `IAM_POSTURE_ATTESTATION.json` | `PROPOSED_TARGET` (IAM least-privilege specification documented) |
| **G-07** | **Isolated Staging Deployment** | Deploy container candidate to a private, authenticated staging environment. | Cloud Run deploy with `--no-allow-unauthenticated` and attached dedicated runtime SA. | `STAGING_DEPLOY_LOG.json` | `PROPOSED_TARGET` (Awaiting Cloud Build permissions resolution) |
| **G-08** | **Post-Deploy Behavioral Verification** | Verify authenticated health endpoints, response contracts, and audit logging. | Authenticated HTTP probes, synthetic trace evaluation, log integrity checks. | `ADJUDICATION.json` | `RECORDED_NEGATIVE` (Historical campaign `REAL-CAMPAIGN-20260926T160434Z` recorded `S_deployed = FALSE`) |

---

## 3. Gate-by-Gate Detailed Requirements

### Gate G-01: Secret & Exposure Detection
- **Objective:** Ensure no private keys, database connection strings, cloud API keys, or quantum platform tokens enter source control or build contexts.
- **Fail-Closed Condition:** Detection of any high-entropy token or string matching known provider signatures (IBM, AWS, GCP, Supabase, Neon) halts the build immediately.
- **Critical Policy:** Regex alone is recognized as insufficient; high-entropy string detection and pre-commit scanning are required.

### Gate G-02: Source & Schema Validation
- **Objective:** Ensure code structure conforms to canonical schemas and rejects unsafe constructs (e.g., dynamic `eval()`, unverified deserialization, unconstrained reflection).
- **Fail-Closed Condition:** Syntax errors, schema mismatches against `schemas/`, or forbidden unsafe AST nodes cause immediate rejection.

### Gate G-03: Offline Test Consistency
- **Objective:** Verify deterministic logic, state transition safety, and policy compliance in an isolated local environment.
- **Non-Substitution Boundary:** **A passing test suite establishes internal logic consistency ONLY.** It does *not* establish production readiness, deployment authorization, or external security guarantees.

### Gate G-04: Deterministic Image Build
- **Objective:** Build a container image whose exact content is identified by its cryptographic SHA-256 digest, not a mutable tag.
- **Pinning Rule:** The pipeline must forbid references to mutable tags such as `:latest`, `:dev`, or `:main`. The container digest (`sha256:...`) must be extracted directly from Artifact Registry and pinned in all deployment manifests.

### Gate G-05: Artifact & Image Analysis
- **Objective:** Scan the immutable image digest for known Common Vulnerabilities and Exposures (CVEs) and verify base image provenance.
- **Threshold:** Zero critical or high-severity vulnerabilities in base OS packages and application dependencies.

### Gate G-06: Runtime Posture & IAM Boundary
- **Objective:** Guarantee that runtime privilege separation is maintained in the Cloud Run service definition.
- **Rules:**
  1. **Deployer Identity $\neq$ Runtime Identity:** The Cloud Build runner service account must possess `roles/iam.serviceAccountUser` *only* on the specific runtime service account, with zero project-wide admin privileges.
  2. **Ingress Control:** Ingress configured to `internal` or `internal-and-cloud-load-balancing` unless public access is explicitly authorized and gated.
  3. **No In-Memory Secret Passing via CLI:** Secrets mounted via Cloud Secret Manager; no plaintext environment variables in deployment flags.

### Gate G-07: Isolated Staging Deployment
- **Objective:** Deploy the verified container digest to an isolated staging revision without routing production traffic.
- **Confinement:** Ingress set to authenticated-only (`--no-allow-unauthenticated`).

### Gate G-08: Post-Deploy Behavioral Verification
- **Objective:** Execute authenticated synthetic requests against `/health` and designated API endpoints to verify live behavior.
- **Precedence Rule:** If any post-deployment probe fails, times out, or logs an unhandled exception, `S_deployed` evaluates to `FALSE`, and the revision is quarantined.

---

## 4. Current State: Historical Failed Campaign G-08 Record

In campaign `REAL-CAMPAIGN-20260926T160434Z`, Gate G-08 evaluated to `FALSE` due to observed deployment failures in Cloud Build. In accordance with the OSIRIS Epistemic Non-Substitution Invariant:
1. `S_deployed = FALSE` is immutably recorded in `evidence/operational/REAL-CAMPAIGN-20260926T160434Z/`.
2. The release candidate `v0.1.0-beta.1` remains classified as an **Offline Reference Implementation**, with production deployment status firmly set to `BLOCKED`.
3. Progression to a successor campaign requires closing the open security items tracked outside this repository.
3. Progression to a successor campaign requires resolving the IAM and credential exposure issues documented in `INCIDENT_SECRET_EXPOSURE_20260927.md`.
