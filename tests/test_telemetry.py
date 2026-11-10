"""OSIRIS-TELEMETRY-V1: frames, actions, run chains and seals.

Synthetic runs only. Nothing here represents a real experiment.
"""

import hashlib
import json
import re

import pytest

from osiris_governance import telemetry
from osiris_governance.canonical import canonicalize_json
from osiris_governance.errors import TelemetryValidationError
from osiris_governance.telemetry import TelemetryRun, quantity, verify_run

SYNTHETIC = {"kind": "SYNTHETIC", "node": "test_node", "generator": "test-lattice 0.0", "seed": 7}
HARDWARE = {"kind": "HARDWARE", "node": "test_node", "generator": "test-probe 0.0"}
DEG360 = quantity(360, 0, "deg")


def window(start="2026-10-07T11:28:30Z", end="2026-10-07T11:28:31Z", samples=256):
    return {"start": start, "end": end, "samples": samples}


def w2(value=321412):
    return {"w2_distance": quantity(value, 6, "1")}


def trigger(frame_seq=1, observed=321412, comparison="GT", threshold=None):
    return {"frame_seq": frame_seq, "metric": "w2_distance", "observed": quantity(observed, 6, "1"),
            "comparison": comparison, "threshold": threshold or quantity(1, 1, "1")}


def phase(period=DEG360):
    par = {"name": "drive_phase", "unit": "deg"}
    if period is not None:
        par["period"] = period
    return par


def started(source=SYNTHETIC, evidence_class="SIMULATED"):
    run = TelemetryRun("run-test-1", source, evidence_class)
    lines = [run.frame("2026-10-07T11:28:31.4Z", window(), w2())]
    return run, lines


def codes(error_or_violations):
    """The distinct violation codes, without "line N: " prefixes or messages."""
    violations = getattr(error_or_violations, "violations", error_or_violations)
    return sorted({re.sub(r"^line \d+: ", "", v).split(":")[0] for v in violations})


def recode(line, **changes):
    """A record rewritten in canonical form, as a careless or dishonest writer might."""
    record = json.loads(line)
    record.update(changes)
    return canonicalize_json(record)


# -- writing and verifying --------------------------------------------------------

def test_a_written_run_verifies_and_anyone_can_recompute_its_digests():
    run, lines = started()
    lines.append(run.action("2026-10-07T11:28:31.5Z", "RECALIBRATION", phase(), quantity(10, 0, "deg"),
                            quantity(12, 0, "deg"), True, trigger()))
    summary = verify_run(lines)
    assert summary.ok and summary.records == 2 and summary.run_id == "run-test-1"
    assert json.loads(lines[1])["prev"] == "sha256:" + hashlib.sha256(lines[0]).hexdigest()
    assert summary.head == "sha256:" + hashlib.sha256(lines[1]).hexdigest() == run.summary().head
    assert verify_run(b"".join(line + b"\n" for line in lines).splitlines()) == summary


def test_lines_with_newlines_from_a_binary_file_verify(tmp_path):
    _, lines = started()
    path = tmp_path / "run.jsonl"
    path.write_bytes(b"".join(line + b"\n" for line in lines))
    with open(path, "rb") as handle:
        assert verify_run(handle).ok


# -- source and evidence class ----------------------------------------------------

@pytest.mark.parametrize("source, evidence_class", [
    (SYNTHETIC, "MEASURED"),
    ({**SYNTHETIC, "kind": "SIMULATOR"}, "MEASURED"),
    (HARDWARE, "SIMULATED"),
])
def test_only_hardware_telemetry_is_measured(source, evidence_class):
    with pytest.raises(TelemetryValidationError) as err:
        started(source, evidence_class)
    assert codes(err.value) == ["SOURCE_CLASS_MISMATCH"]


def test_hardware_telemetry_is_measured():
    assert started(HARDWARE, "MEASURED")[0].summary().records == 1


def test_synthetic_telemetry_names_its_seed():
    unseeded = {k: v for k, v in SYNTHETIC.items() if k != "seed"}
    with pytest.raises(TelemetryValidationError) as err:
        started(unseeded)
    assert codes(err.value) == ["UNSEEDED_SYNTHETIC"]


def test_a_bad_vocabulary_value_is_reported_not_crashed_on():
    violations = telemetry.record_violations(json.loads(recode(started()[1][0], evidence_class=["MEASURED"])))
    assert codes(violations) == ["SCHEMA_ENUM"]


# -- quantities and windows --------------------------------------------------------

def test_floats_never_reach_a_run():
    _, lines = started()
    floated = lines[0].replace(b'{"scale":6,"unit":"1","value":321412}', b"0.321412")
    assert codes(verify_run([floated]).violations) == ["NOT_CANONICAL_JSON"]
    assert "FLOAT_FORBIDDEN" in verify_run([floated]).violations[0]


def test_quantities_are_exact():
    assert telemetry.magnitude(quantity(3214, 4, "1")) == telemetry.magnitude(quantity(32140, 5, "1"))
    assert str(telemetry.magnitude(quantity(51843, 3, "deg"))) == "51843/1000"


@pytest.mark.parametrize("win, code", [
    (window(start="2026-10-07T11:28:32Z"), "WINDOW_ORDER"),
    (window(end="2026-10-07T11:28:32Z"), "WINDOW_AFTER_RECORD"),
    (window(samples=0), "SCHEMA_TYPE"),
    ({"start": "2026-10-07T11:28:30Z", "end": "2026-10-07T11:28:31Z"}, "SCHEMA_MISSING"),
    (window(start="2026-13-07T11:28:30Z"), "SCHEMA_TIMESTAMP"),
])
def test_a_frame_states_the_window_its_metrics_summarize(win, code):
    run = TelemetryRun("run-test-1", SYNTHETIC, "SIMULATED")
    with pytest.raises(TelemetryValidationError) as err:
        run.frame("2026-10-07T11:28:31.4Z", win, w2())
    assert code in codes(err.value)


# -- actions -----------------------------------------------------------------------

@pytest.mark.parametrize("old, new, period", [
    (quantity(51843, 3, "deg"), quantity(51843, 3, "deg"), DEG360),
    (quantity(10, 0, "deg"), quantity(370, 0, "deg"), DEG360),
    (quantity(10, 0, "deg"), quantity(-350, 0, "deg"), DEG360),
    (quantity(10, 0, "deg"), quantity(730, 0, "deg"), DEG360),
    (quantity(5, 1, "deg"), quantity(50, 2, "deg"), None),
])
def test_an_action_that_changes_nothing_is_not_applied(old, new, period):
    run, _ = started()
    with pytest.raises(TelemetryValidationError) as err:
        run.action("2026-10-07T11:28:31.5Z", "RECALIBRATION", phase(period), old, new, True, trigger())
    assert codes(err.value) == ["NO_OP_APPLIED"]
    assert run.action("2026-10-07T11:28:31.5Z", "RECALIBRATION", phase(period), old, new, False, trigger())


def test_circular_distance_takes_the_short_way_round():
    assert telemetry.distance(quantity(359, 0, "deg"), quantity(1, 0, "deg"), DEG360) == 2
    assert telemetry.distance(quantity(359, 0, "deg"), quantity(1, 0, "deg")) == 358
    assert telemetry.distance(quantity(10, 0, "deg"), quantity(370, 0, "deg")) == 360
    assert telemetry.distance(quantity(0, 0, "deg"), quantity(725, 0, "deg"), DEG360) == 5


def test_a_change_may_be_recorded_as_not_applied():
    run, lines = started()
    lines.append(run.action("2026-10-07T11:28:31.5Z", "RECALIBRATION", phase(), quantity(10, 0, "deg"),
                            quantity(12, 0, "deg"), False, trigger()))
    assert verify_run(lines).ok


@pytest.mark.parametrize("trig, code", [
    (trigger(frame_seq=2), "TRIGGER_NOT_EARLIER"),
    (trigger(observed=999), "TRIGGER_NOT_MET"),
    (trigger(observed=321413), "TRIGGER_MISMATCH"),
    (trigger(comparison="ABOVE"), "SCHEMA_ENUM"),
    (trigger(threshold=quantity(1, 1, "deg")), "UNIT_MISMATCH"),
])
def test_an_action_records_the_frame_value_that_triggered_it(trig, code):
    run, _ = started()
    with pytest.raises(TelemetryValidationError) as err:
        run.action("2026-10-07T11:28:31.5Z", "RECALIBRATION", phase(), quantity(10, 0, "deg"),
                   quantity(12, 0, "deg"), True, trig)
    assert code in codes(err.value)


def test_a_trigger_names_a_frame_in_the_same_run():
    run, lines = started()
    lines.append(run.action("2026-10-07T11:28:31.5Z", "RECALIBRATION", phase(), quantity(10, 0, "deg"),
                            quantity(12, 0, "deg"), True, trigger()))
    third = recode(lines[1], seq=3, prev=verify_run(lines).head, trigger=trigger(frame_seq=2))
    assert codes(verify_run(lines + [third]).violations) == ["TRIGGER_UNKNOWN_FRAME"]


def test_parameter_values_share_the_parameter_unit():
    run, _ = started()
    with pytest.raises(TelemetryValidationError) as err:
        run.action("2026-10-07T11:28:31.5Z", "RECALIBRATION", phase(), quantity(10, 0, "rad"),
                   quantity(12, 0, "deg"), True, trigger())
    assert codes(err.value) == ["UNIT_MISMATCH"]


# -- retracted constructs ----------------------------------------------------------

@pytest.mark.parametrize("name", ["phi", "lambda_c", "gamma", "xi", "chi_pc", "consciousness_state",
                                  "theta_lock_deg", "phase_lock_deg"])
def test_retracted_metric_names_are_refused(name):
    run = TelemetryRun("run-test-1", SYNTHETIC, "SIMULATED")
    with pytest.raises(TelemetryValidationError) as err:
        run.frame("2026-10-07T11:28:31.4Z", window(), {name: quantity(1, 0, "1")})
    assert codes(err.value) == ["RETRACTED_CONSTRUCT"]


def test_the_phase_lock_parameter_is_refused():
    run, _ = started()
    par = {"name": "phase_lock_deg", "unit": "deg", "period": DEG360}
    with pytest.raises(TelemetryValidationError) as err:
        run.action("2026-10-07T11:28:31.5Z", "RECALIBRATION", par, quantity(10, 0, "deg"),
                   quantity(12, 0, "deg"), True, trigger())
    assert codes(err.value) == ["RETRACTED_CONSTRUCT"]


def test_a_state_label_has_no_field_to_live_in():
    record = json.loads(started()[1][0])
    record["consciousness_state"] = "emerging"
    record["claim_ceiling"] = "LOCAL_TEST_RESULT"
    violations = telemetry.record_violations(record)
    assert codes(violations) == ["RETRACTED_CONSTRUCT", "SCHEMA_UNKNOWN_FIELD"]


def test_a_pcrb_row_carried_over_field_for_field_is_refused():
    """The frame on line 3 of evidence/pcrb_telemetry_ledger.jsonl, carried over to V1 field for field."""
    run = TelemetryRun("pcrb", {"kind": "SYNTHETIC", "node": "NODE_BETA_COMPUTE", "generator": "SYNTHETIC_LATTICE"},
                       "MEASURED")
    metrics = {"phi": quantity(291576, 6, "1"), "lambda_c": quantity(86433, 5, "1"), "gamma": quantity(100166, 6, "1"),
               "xi": quantity(2515973, 6, "1"), "w2_distance": quantity(321412, 6, "1"),
               "shannon_entropy": quantity(2874727, 6, "bit")}
    with pytest.raises(TelemetryValidationError) as err:
        run.frame("2026-10-07T11:28:31.396607Z", window(), metrics)
    assert codes(err.value) == ["RETRACTED_CONSTRUCT", "SOURCE_CLASS_MISMATCH", "UNSEEDED_SYNTHETIC"]
    assert sum("RETRACTED_CONSTRUCT" in v for v in err.value.violations) == 4


# -- chains ------------------------------------------------------------------------

def two_frames():
    run, lines = started()
    lines.append(run.frame("2026-10-07T11:28:32Z", window("2026-10-07T11:28:31Z", "2026-10-07T11:28:32Z"), w2()))
    return lines


def test_a_second_genesis_is_a_second_run_not_a_continuation():
    lines = two_frames()
    restarted = recode(lines[1], prev=telemetry.GENESIS_DIGEST)
    assert codes(verify_run([lines[0], restarted]).violations) == ["CHAIN_RESTART"]


def test_an_edited_line_breaks_the_chain_after_it():
    lines = two_frames()
    edited = recode(lines[0], metrics=w2(300000))
    assert codes(verify_run([edited, lines[1]]).violations) == ["CHAIN_BROKEN"]


@pytest.mark.parametrize("change, code", [
    ({"seq": 1}, "SEQ_ORDER"),
    ({"run_id": "run-test-2"}, "RUN_ID_CHANGED"),
    ({"recorded_at": "2026-10-07T11:28:31.39Z",
      "window": window("2026-10-07T11:28:30Z", "2026-10-07T11:28:31Z")}, "TIME_ORDER"),
])
def test_one_run_counts_up_in_time(change, code):
    lines = two_frames()
    assert codes(verify_run([lines[0], recode(lines[1], **change)]).violations) == [code]


def test_a_reformatted_line_is_not_canonical():
    lines = two_frames()
    pretty = json.dumps(json.loads(lines[0]), indent=1).encode()
    assert codes(verify_run([pretty]).violations) == ["NOT_CANONICAL"]


# -- seals -------------------------------------------------------------------------

def test_a_seal_covers_every_line():
    pytest.importorskip("cryptography")
    from osiris_governance import signing

    lines = two_frames()
    key = signing.load_private_key_pem(signing.generate_private_key_pem())   # test key: seals no evidence
    signature = signing.sign_bytes(key, telemetry.seal_payload(verify_run(lines)))
    assert signing.verify_signature(key.public_key(), signature, telemetry.seal_payload(verify_run(lines)))
    shortened = telemetry.seal_payload(verify_run(lines[:1]))
    assert not signing.verify_signature(key.public_key(), signature, shortened)
    with pytest.raises(TelemetryValidationError):
        telemetry.seal_payload(verify_run([recode(lines[0], metrics=w2(300000)), lines[1]]))


def test_an_empty_run_cannot_be_sealed():
    with pytest.raises(TelemetryValidationError):
        telemetry.seal_payload(verify_run([]))
