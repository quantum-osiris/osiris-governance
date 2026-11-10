"""The PCRB correction (COR-2026-10-27-PCRB-001) checked against the ledger it corrects.

Each finding the correction states has a test here. The ledger stays byte-for-byte as committed
in 71ee6ef: the correction cites its rows and never rewrites them.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from osiris_governance import telemetry
from osiris_governance.canonical import canonicalize_json, strict_parse_json

ROOT = Path(__file__).parent.parent
LEDGER = ROOT / "evidence" / "pcrb_telemetry_ledger.jsonl"
CORRECTION = ROOT / "evidence" / "corrections" / "COR-2026-10-27-PCRB-001.json"
ZEROS = "0" * 64


def ledger_lines():
    return LEDGER.read_bytes().splitlines()


def rows():
    """line number -> parsed record, for every line that is a record."""
    return {n: json.loads(line) for n, line in enumerate(ledger_lines(), 1) if line.startswith(b"{")}


def correction():
    return strict_parse_json(CORRECTION.read_bytes())


def frames():
    return {n: r for n, r in rows().items() if "frame" in r}


def actions():
    return {n: r for n, r in rows().items() if "action" in r}


def utc(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc)


# -- the record itself ------------------------------------------------------------

def test_the_correction_binds_the_ledger_as_committed():
    doc = correction()
    subject = doc["subject"]
    assert subject["path"] == LEDGER.relative_to(ROOT).as_posix()
    assert subject["sha256"] == "sha256:" + hashlib.sha256(LEDGER.read_bytes()).hexdigest()
    cited = {entry["line"]: entry for entry in subject["lines"]}
    lines = ledger_lines()
    assert sorted(cited) == list(range(1, len(lines) + 1))
    for number, line in enumerate(lines, 1):
        assert cited[number]["line_sha256"] == "sha256:" + hashlib.sha256(line).hexdigest()
    for number, row in rows().items():
        assert (cited[number]["record_id"], cited[number]["entry_hash"]) == (row["record_id"], row["entry_hash"])
        assert cited[number]["kind"] == ("FRAME" if "frame" in row else "ACTION")
    assert doc["original_rows_modified"] is False


def test_the_correction_is_canonical_json_and_claims_no_signature():
    doc = correction()
    canonicalize_json(doc)                                    # no floats, NFC, ASCII keys
    assert doc["document_type"] == "OSIRIS_EVIDENCE_CORRECTION"
    assert doc["reclassification"]["corrected"] == {"evidence_class": "SIMULATED", "evidence_role": "NONE", "supports": []}
    assert doc["signing"]["required_signer"] == "an enrolled node key"


def test_every_retracted_name_in_the_rows_is_named_by_the_correction():
    named = {field for item in correction()["retracted_fields"] for field in item["fields"]}
    found = set()
    for row in rows().values():
        if "frame" in row:
            found |= {f"frame.{key}" for key in row["frame"] if telemetry.retracted(key)}
        else:
            if telemetry.retracted(row["action"]["target_parameter"]):
                found.add("action.target_parameter")
    assert found == {"frame.phi", "frame.lambda_c", "frame.gamma", "frame.xi", "frame.consciousness_state",
                     "action.target_parameter"}
    assert found <= named


def test_every_finding_names_a_test_in_this_module():
    for finding in correction()["findings"]:
        assert callable(globals().get(finding["test"])), finding["id"]


# -- findings ---------------------------------------------------------------------

def test_f1_every_frame_is_synthetic_but_marked_measured():
    assert sorted(frames()) == [3, 6]
    for row in frames().values():
        assert (row["frame"]["telemetry_source"], row["evidence_status"]) == ("SYNTHETIC_LATTICE", "MEASURED")


def test_f2_every_recalibration_leaves_the_parameter_where_it_was():
    assert sorted(actions()) == [2, 4, 5, 7]
    for row in actions().values():
        act = row["action"]
        assert act["target_parameter"] == "phase_lock_deg"
        assert act["old_value"] == act["new_value"] == 51.843
    # Two actions per frame, each quoting that frame's W_2.
    for frame_line, action_lines in ((3, (2, 4)), (6, (5, 7))):
        w2 = f"W_2={rows()[frame_line]['frame']['w2_distance']:.4f}"
        assert all(w2 in rows()[n]["action"]["reason"] for n in action_lines)


def test_f3_the_file_holds_two_one_frame_runs():
    starts = [n for n, row in rows().items() if row["prev_hash"] == ZEROS]
    assert starts == [2, 5]
    previous = None
    for number, row in rows().items():
        if number not in starts:
            assert row["prev_hash"] == previous
        previous = row["entry_hash"]
    assert [rows()[n]["record_id"] for n in frames()] == ["PCRB-TR-00000001"] * 2
    assert [rows()[n]["frame"]["frame_seq"] for n in frames()] == [1, 1]
    assert [rows()[n]["frame"]["consciousness_state"] for n in frames()] == ["dormant", "emerging"]
    assert [utc(rows()[n]["timestamp"]).strftime("%Y-%m-%dT%H:%M:%SZ") for n in starts] == [
        "2026-10-07T11:28:31Z", "2026-10-07T11:35:02Z"]


def test_f4_xi_is_computed_from_the_other_three():
    for row in frames().values():
        f = row["frame"]
        assert abs(f["xi"] - f["lambda_c"] * f["phi"] / f["gamma"]) < 3e-5
        assert abs(f["xi"] - f["lambda_c"] * f["phi"] / (f["gamma"] + 1e-6)) < 1e-5


def test_f5_each_first_action_is_chained_before_its_frame():
    for action_line, frame_line in ((2, 3), (5, 6)):
        assert action_line < frame_line
        assert rows()[action_line]["timestamp"] > rows()[frame_line]["timestamp"]
        assert rows()[frame_line]["prev_hash"] == rows()[action_line]["entry_hash"]


def test_f6_no_line_is_canonical_telemetry():
    assert ledger_lines()[0].startswith(b"#")
    summary = telemetry.verify_run(ledger_lines())
    assert not summary.ok
    assert [v.split(":")[0] for v in summary.violations] == [f"line {n}" for n in range(1, 8)]
    assert all("NOT_CANONICAL_JSON" in v for v in summary.violations)
    assert all("FLOAT_FORBIDDEN" in v for v in summary.violations[1:])
