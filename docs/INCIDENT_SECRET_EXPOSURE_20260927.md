# INCIDENT REPORT: Secret Exposure in Architecture Specification Document

**Incident ID:** `INC-20260927-01`  
**Classification:** Restricted / Internal Security Remediation  
**Status:** Active Remediation & Containment  
**Date Reported:** 2026-09-27T11:13:57Z  
**Severity:** Critical (P1)  
**Reporting Source:** External Architectural & Security Review of `paste.txt`  

---

## 1. Executive Summary

During an architectural and governance review of the draft specification document `paste.txt` (uploaded to an external S3-hosted file sharing link), live credentials, API keys, and connection strings were identified embedded within illustrative examples. 

In accordance with OSIRIS operational security policy, all credentials appearing in transcripts, documentation, repositories, or external uploads are immediately classified as **compromised**. Partial masking, document deletion, or retraction does not undo exposure. A full containment, revocation, rotation, repository audit, and CI enforcement sequence is mandated.

---

## 2. Identified Exposed Credential Classes

The following credential categories were identified within the unredacted draft:

| Credential Class | Provider / Service | Vulnerability / Exposure Mechanism | Exposure Impact | Containment Action Required |
|---|---|---|---|---|
| **Quantum API Token** | IBM Quantum (`IBM_QUANTUM_TOKEN`) | Plaintext token embedded in benchmark invocation example | Unauthorized QPU job dispatch, account quota exhaustion | Immediate revocation in IBM Quantum Platform console; token re-issuance |
| **Database Connection URI** | PostgreSQL / Neon (`postgresql://...`) | Plaintext user, password, host, and database name in connection string | Database read/write access, schema tampering, data exfiltration | Immediate rotation of DB user credentials; connection termination; audit active queries |
| **Supabase Client Key** | Supabase (`sbp_...` / JWT) | Plaintext key embedded in client initialization code | Public client access; potential RLS bypass if service-role key | Rotate key via Supabase dashboard; audit Row Level Security (RLS) policies |
| **AI Gateway Key** | AI Gateway / LLM Proxy | Plaintext API key embedded in adapter configuration | Unauthorized model inference, cost escalation | Revoke key in provider console; generate scoped replacement secret |
| **Cloud Provider Keys** | Google Cloud / Gemini API | Plaintext API key-like strings (`AIza...`) in sample payloads | Unauthorized Vertex/Gemini API calls, project resource consumption | Audit GCP API keys; delete/restrict keys; enforce Service Account / ADC only |

---

## 3. Immediate Containment & Remediation Sequence

### Phase 1: Provider-Side Revocation and Rotation (Immediate)
1. **IBM Quantum:**
   - Log into IBM Quantum Platform console.
   - Invalidate the active API token.
   - Generate a replacement token and store it exclusively in Google Cloud Secret Manager or local encrypted secret store (`projects/living-language-model/secrets/ibm-quantum-token`).
2. **PostgreSQL / Database:**
   - Terminate active client connections matching the exposed user identity.
   - Issue a database `ALTER ROLE <user> WITH PASSWORD '<new_secure_password>';` or rotate via Neon console.
   - Audit database access logs for unrecognized IP connections during the exposure window.
3. **Supabase Key:**
   - Invalidate the exposed publishable/anon key.
   - Confirm that the `service_role` (admin) key was not exposed.
   - Re-verify that Row Level Security (RLS) is active on all exposed tables.
4. **AI Gateway & Google Cloud:**
   - Revoke active API gateway tokens.
   - Inspect Google Cloud Console (`living-language-model`) under `APIs & Services` > `Credentials`.
   - Delete any exposed unrestricted API keys. Restrict any essential keys by API, HTTP referer, or IP address.

### Phase 2: Repository and History Containment
1. **Repository Audit:**
   - Performed recursive regex scan across `/home/enki/osiris-governance` and `/home/enki/fold`.
   - **Result:** Zero plaintext credentials currently exist in the working tree.
2. **Commit History Sanitization:**
   - Assume any repository or branch that accepted `paste.txt` or derived files is contaminated.
   - Do NOT attempt to fix by committing a "redacted" version on top; rotation must occur first.
   - For public or shared forks, execute a clean history rewrite using `git-filter-repo` or BFG Repo-Cleaner to purge historical blobs.
   - Invalidate and rotate credentials regardless of history rewrite.
3. **Deployment Halts:**
   - Immediately suspend any active automated CI/CD deployment pipelines utilizing the exposed secrets.
   - Block Cloud Run deployments until replacement credentials are injected via verified Google Cloud Secret Manager references.

---

## 4. Architectural Vulnerability Analysis: Over-Reliance on Regex Quarantine

The incident revealed a systemic architectural over-confidence in the initial draft's assertion that:
> *"Gate 01 regex AST scanning guarantees quarantine of all credentials."*

### Audit Findings on Gate 01:
- **Regex Limitations:** Simple regular expressions cannot detect high-entropy hex/base64 strings, customized connection formats, or split-string tokens.
- **Context Blindness:** Regex filters fail when credentials appear within markdown code fences, documentation examples, base64-encoded strings, or configuration snippets.
- **False Negative Risk:** Relying exclusively on regex creates a false sense of security, allowing developers to paste real secrets into "sample" files under the assumption that the tool will catch them.

---

## 5. Prevention & Enforcement Controls

1. **Layered Secret Scanning Pipeline:**
   - Integrate Trufflehog / Gitleaks into local pre-commit hooks (`.git/hooks/pre-commit`).
   - Implement Shannon entropy analysis to detect high-entropy strings regardless of known prefix formats.
   - Establish strict mock allowlists (`MOCK_SYNTHETIC_TEST_TOKEN_...`) strictly scoped to `tests/unit/` directories.
2. **Prohibition of Long-Lived Secrets in Artifacts:**
   - **Android / Termux:** Zero production API keys stored in Android APKs, `BuildConfig`, Termux shell environment variables, or local `.env` files.
   - **Docker / Containers:** Zero build-time `ARG` or `ENV` secrets in Dockerfiles.
   - **Cloud Run:** Zero static environment variables containing secret strings; runtime must retrieve secrets via Cloud Secret Manager volume mounts or runtime API calls via Application Default Credentials (ADC).
3. **Release-Blocking Incident Gate:**
   - Any detected credential exposure immediately places the release candidate in `BLOCKED` status.
   - Monotonic rule: A release candidate cannot advance until an Incident Report is authored, rotation receipts are recorded, and an independent clean scan passes.

---

## 6. Verification Checklist

- [x] Working tree verified clean of exposed secret patterns.
- [ ] Provider consoles accessed; IBM Quantum token revoked and regenerated.
- [ ] Database credentials rotated and connections restarted.
- [ ] Supabase keys rotated; RLS policies audited.
- [ ] AI gateway tokens rotated.
- [ ] GCP API keys audited and restricted in project `living-language-model`.
- [ ] Pre-commit hook installed to block future commits containing high-entropy strings.
- [ ] Target architecture decoupled into modular, un-credentialed specification documents.

**Incident Lead:** Security & Governance Officer  
**Sign-off:** OSIRIS Adjudication Authority  
