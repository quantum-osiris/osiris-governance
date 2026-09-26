"""
OSIRIS Governance Minimal Operator CLI
======================================

Implements the standard commands:
- validate <request.json>
- decide <request.json> [--policy <policy_id>]
- replay <request.json> [--evidence <evidence.json>]
- inspect <evidence-record.json>
- verify-chain <evidence_dir>

Standard library only. Zero imports of os, pathlib, subprocess, socket.
"""

import argparse
import glob
import hashlib
import json
import sys

from .canonical import canonicalize_json
from .gateway import PolicyConfig, ReplayGateway, ReplayRequest


def cmd_validate(args):
    try:
        with open(args.request_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: {args.request_file} does not exist.", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"INVALID: JSON parse error: {e}", file=sys.stderr)
        return 1

    gw = ReplayGateway()
    try:
        req, digest = gw.validate_request(data)
        print("VALID REQUEST:")
        print(f"  Request ID:       {req.request_id}")
        print(f"  Workload Type:    {req.workload_type}")
        print(f"  Fixture ID:       {req.fixture_id}")
        print(f"  Canonical Digest: {digest}")
        return 0
    except Exception as e:
        print(f"REJECTED: Validation failed: {e}", file=sys.stderr)
        return 1


def cmd_decide(args):
    try:
        with open(args.request_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: {args.request_file} does not exist.", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"INVALID: JSON parse error: {e}", file=sys.stderr)
        return 1

    policy_rev = args.policy
    policy = PolicyConfig.default()
    if policy_rev:
        policy = PolicyConfig(
            policy_revision=policy_rev,
            allowed_workloads=("replay_fixture_v1",),
            allowlist=("echo-normalized-input-v1", "replay-fixture-v1"),
            active_epoch=1,
            allow_side_effects=False,
        )

    gw = ReplayGateway(policy)
    try:
        req, digest = gw.validate_request(data)
    except Exception as e:
        print(f"DECISION: DENY_SCHEMA_INVALID ({e})")
        return 1

    decision, permit, reason = gw.decide(req, policy_rev)
    print("================================================================================")
    print(f"GOVERNANCE POLICY DECISION: {decision}")
    print("================================================================================")
    print(f"  Request ID:       {req.request_id}")
    print(f"  Request Digest:   {digest}")
    print(f"  Policy Revision:  {policy.policy_revision}")
    if permit:
        print(f"  Permit ID:        {permit.permit_id}")
        print(f"  Execution Mode:   {permit.execution_mode}")
        print(f"  Side Effects:     {'ALLOWED' if permit.side_effects_allowed else 'FORBIDDEN'}")
    if reason:
        print(f"  Denial Reason:    {reason}")
    print("================================================================================")
    return 0 if decision == "ALLOW_REPLAY" else 1


def cmd_replay(args):
    try:
        with open(args.request_file, "r", encoding="utf-8") as f:
            req_data = json.load(f)
    except FileNotFoundError:
        print(f"Error: {args.request_file} does not exist.", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"INVALID: JSON parse error: {e}", file=sys.stderr)
        return 1

    gw = ReplayGateway()
    try:
        req, digest = gw.validate_request(req_data)
    except Exception as e:
        print(f"REPLAY FAILED: Request invalid: {e}", file=sys.stderr)
        return 1

    decision, permit, reason = gw.decide(req)
    if decision != "ALLOW_REPLAY" or not permit:
        print(f"REPLAY DENIED: Policy decision was {decision} ({reason})", file=sys.stderr)
        return 1

    # Execute fixture
    exec_result = gw.execute_adapter(permit, req)
    verified = gw.verify_result(req, permit, exec_result)
    if not verified:
        print("REPLAY FAILED: Result verification failed", file=sys.stderr)
        return 1

    prev_digest = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
    if args.previous_evidence:
        try:
            with open(args.previous_evidence, "r", encoding="utf-8") as f:
                prev_rec = json.load(f)
                prev_digest = prev_rec.get("integrity", {}).get("record_digest", prev_digest)
        except Exception as e:
            print(f"Error reading previous evidence file: {e}", file=sys.stderr)
            return 1

    evidence_record = gw.seal_evidence_record(
        req, decision, reason, permit, exec_result, previous_record_digest=prev_digest
    )

    # Optional compare with existing evidence
    if args.evidence:
        try:
            with open(args.evidence, "r", encoding="utf-8") as f:
                prior_record = json.load(f)
        except Exception as e:
            print(f"Error reading prior evidence file: {e}", file=sys.stderr)
            return 1

        matches, msg = gw.replay_record(prior_record, req)
        print(f"COMPARISON REPLAY RESULT: {msg}")
        return 0 if matches else 1

    print("================================================================================")
    print("REPLAY EXECUTION SUCCESSFUL")
    print("================================================================================")
    print(f"  Request ID:        {req.request_id}")
    print(f"  Fixture ID:        {permit.fixture_id}")
    print(f"  Adapter:           {permit.adapter_id}")
    print(f"  Result Digest:     {exec_result['result_digest']}")
    print(f"  Evidence Record ID:{evidence_record['record_id']}")
    print(f"  Evidence Digest:   {evidence_record['integrity']['record_digest']}")
    print("================================================================================")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(evidence_record, f, indent=2, sort_keys=True)
        print(f"Evidence saved to {args.output}")

    return 0


def cmd_inspect(args):
    try:
        with open(args.record_file, "r", encoding="utf-8") as f:
            record = json.load(f)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Re-verify integrity digest
    record_copy = json.loads(json.dumps(record))
    recorded_digest = record.get("integrity", {}).get("record_digest", "")
    record_copy["integrity"]["record_digest"] = ""
    canonical_bytes = canonicalize_json(record_copy)
    recomputed_digest = f"sha256:{hashlib.sha256(canonical_bytes).hexdigest()}"
    digest_intact = (recorded_digest == recomputed_digest)

    print("================================================================================")
    print(f"EVIDENCE RECORD INSPECTION: {record.get('record_id')}")
    print("================================================================================")
    print(f"  Timestamp UTC:      {record.get('timestamp_utc')}")
    print(f"  Workload Type:      {record.get('request', {}).get('workload_type')}")
    print(f"  Fixture ID:         {record.get('request', {}).get('fixture_id')}")
    print(f"  Request Digest:     {record.get('request', {}).get('canonical_bytes_digest')}")
    print(f"  Policy Decision:    {record.get('policy', {}).get('decision')}")
    print(f"  Permit ID:          {record.get('permit', {}).get('permit_id') if record.get('permit') else 'NONE'}")
    print(f"  Execution Result:   {record.get('execution', {}).get('result_digest') if record.get('execution') else 'NONE'}")
    print(f"  Previous Digest:    {record.get('integrity', {}).get('previous_record_digest')}")
    print(f"  Record Digest:      {recorded_digest}")
    print(f"  Digest Integrity:   {'INTACT (PASS)' if digest_intact else 'TAMPERED (FAIL)'}")
    print("================================================================================")
    return 0 if digest_intact else 1


def cmd_verify_chain(args):
    files = sorted(glob.glob(f"{args.evidence_dir}/*.json"))
    records = []
    for fl in files:
        with open(fl, "r", encoding="utf-8") as f:
            try:
                rec = json.load(f)
                if "record_id" in rec and "integrity" in rec:
                    records.append(rec)
            except Exception:
                pass

    if not records:
        print("No valid evidence records found in directory.", file=sys.stderr)
        return 1

    print(f"Verifying hash chain across {len(records)} evidence records...")
    chain_intact = True
    for idx, rec in enumerate(records):
        rec_id = rec.get("record_id")
        recorded_digest = rec.get("integrity", {}).get("record_digest", "")

        # 1. Digest integrity check
        rec_copy = json.loads(json.dumps(rec))
        rec_copy["integrity"]["record_digest"] = ""
        recomputed = f"sha256:{hashlib.sha256(canonicalize_json(rec_copy)).hexdigest()}"
        if recomputed != recorded_digest:
            print(f"  [TAMPERED] Record {rec_id} digest mismatch!")
            chain_intact = False
            continue

        # 2. Previous link check
        if idx > 0:
            expected_prev = records[idx - 1]["integrity"]["record_digest"]
            actual_prev = rec["integrity"]["previous_record_digest"]
            if expected_prev != actual_prev:
                print(f"  [BROKEN LINK] Record {rec_id} previous link does not match prior record!")
                chain_intact = False
                continue

        print(f"  [LINK OK]  Record {rec_id}")

    print("--------------------------------------------------------------------------------")
    print(f"Chain Status: {'INTACT' if chain_intact else 'BROKEN'}")
    print("================================================================================")
    return 0 if chain_intact else 1


def main():
    parser = argparse.ArgumentParser(description="OSIRIS Governance Replay CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. validate
    p_val = subparsers.add_parser("validate", help="Validate request schema and NFC encoding")
    p_val.add_argument("request_file", help="Path to request JSON")

    # 2. decide
    p_dec = subparsers.add_parser("decide", help="Evaluate deterministic policy decision")
    p_dec.add_argument("request_file", help="Path to request JSON")
    p_dec.add_argument("--policy", help="Policy revision (default: policy-0.1.0)")

    # 3. replay
    p_rep = subparsers.add_parser("replay", help="Execute deterministic replay fixture")
    p_rep.add_argument("request_file", help="Path to request JSON")
    p_rep.add_argument("--evidence", help="Prior evidence record to compare against")
    p_rep.add_argument("--previous-evidence", help="Path to previous evidence record to chain from")
    p_rep.add_argument("--output", help="Path to write sealed evidence record")

    # 4. inspect
    p_ins = subparsers.add_parser("inspect", help="Inspect sealed evidence record")
    p_ins.add_argument("record_file", help="Path to evidence record JSON")

    # 5. verify-chain
    p_chain = subparsers.add_parser("verify-chain", help="Verify hash chain across evidence records")
    p_chain.add_argument("evidence_dir", help="Directory containing evidence records")

    args = parser.parse_args()

    if args.command == "validate":
        sys.exit(cmd_validate(args))
    elif args.command == "decide":
        sys.exit(cmd_decide(args))
    elif args.command == "replay":
        sys.exit(cmd_replay(args))
    elif args.command == "inspect":
        sys.exit(cmd_inspect(args))
    elif args.command == "verify-chain":
        sys.exit(cmd_verify_chain(args))


if __name__ == "__main__":
    main()
