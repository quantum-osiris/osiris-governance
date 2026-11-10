"""Telemetry runs: OSIRIS-TELEMETRY-V1 frames, actions and the chain that links them.

A run is one JSONL file. Each line is the OSIRIS-CANONICAL-JSON-V1 form of one record, so a
record's digest is "sha256:" + SHA-256 of its line, and any tool can recompute it. A record
carries no digest of itself; it names the digest of the line before it in `prev`, and the first
record names GENESIS_DIGEST. The file has no header or comment lines.

Rules:
1. ONE_RUN_PER_CHAIN: one run_id per file; seq counts 1, 2, 3 ... with no gap or reuse; only the
   first record links to genesis.
2. TIME_ORDER: recorded_at never decreases along the chain.
3. SOURCE_BOUNDS_CLASS: HARDWARE telemetry is MEASURED. SYNTHETIC and SIMULATOR telemetry is
   SIMULATED, and SYNTHETIC telemetry names the seed that regenerates it.
4. EXACT_QUANTITIES: canonical JSON has no floats. A quantity is {value, scale, unit}: the integer
   value times 10**-scale, in unit ("1" when dimensionless).
5. EXPLICIT_WINDOW: a frame states the sample window its metrics summarize, which ends no later
   than the frame is recorded.
6. NO_OP_NOT_APPLIED: an action whose new value equals its old one (by circular distance when the
   parameter has a period) has applied = false. A change may still be unapplied, e.g. when blocked.
7. RECORDED_TRIGGER: an action names the earlier frame and metric that triggered it. The observed
   value is that frame's value and meets the stated comparison with the threshold.
8. NO_RETRACTED_CONSTRUCTS: no metric or parameter named for the retracted phase-lock angle,
   phase-conjugate coupling or CCCE metrics, and no state labels.

Records hold measurements, not claims: there is no claim ceiling or deployment authority here.
A claim about a run goes through a closure (closure.py). A run is sealed by signing
seal_payload() with an enrolled node key (signing.py).

Drift checks (bottom of this module) compare one metric's time-ordered series from a verified
run with replicas of that series drawn from a model without drift.

The package does no file I/O (INV-13): callers pass lines in and append the lines returned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from fractions import Fraction
import re
from typing import Any, Dict, Hashable, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from .canonical import JCS_SAFE_INTEGER_MAX, canonical_sha256, canonicalize_json, strict_parse_json
from .errors import SchemaValidationError, TelemetryValidationError
from .ledger import GENESIS_DIGEST

SCHEMA_VERSION = "1.0"
FRAME = "OSIRIS_TELEMETRY_FRAME"
ACTION = "OSIRIS_TELEMETRY_ACTION"
SEAL = "OSIRIS_TELEMETRY_SEAL"
MAX_SCALE = 18

SOURCE_KINDS = frozenset({"HARDWARE", "SIMULATOR", "SYNTHETIC"})
# The EvidenceClass values a frame can hold; everything but HARDWARE is SIMULATED.
EVIDENCE_CLASSES = frozenset({"MEASURED", "SIMULATED"})

_PHASE_LOCK = "the retracted phase-lock angle (theta_lock)"
_CCCE = "a CCCE metric, refuted on hardware"
# Names the retracted claims used. A legitimate quantity that shares one needs a distinct name.
RETRACTED_NAMES: Dict[str, str] = {
    "chi_pc": "the retracted phase-conjugate coupling (chi_pc)",
    "phi": _CCCE,
    "lambda_c": _CCCE,
    "gamma": _CCCE,
    "xi": _CCCE,
}
RETRACTED_FRAGMENTS: Dict[str, str] = {
    "phase_lock": _PHASE_LOCK,
    "theta_lock": _PHASE_LOCK,
    "consciousness": "a CCCE state label, refuted on hardware",
}

_HEADER = ("schema_version", "document_type", "run_id", "seq", "prev", "recorded_at")
_FRAME_FIELDS = _HEADER + ("source", "evidence_class", "window", "metrics")
_ACTION_FIELDS = _HEADER + ("action_type", "parameter", "old_value", "new_value", "applied", "trigger")
_TRIGGER_FIELDS = ("frame_seq", "metric", "observed", "comparison", "threshold")

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_ACTION_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?Z$")
_COMPARE = {
    "GT": lambda a, b: a > b,
    "GE": lambda a, b: a >= b,
    "LT": lambda a, b: a < b,
    "LE": lambda a, b: a <= b,
}


# --------------------------------------------------------------------------------------------
# Quantities
# --------------------------------------------------------------------------------------------

def quantity(value: int, scale: int, unit: str) -> Dict[str, Any]:
    """{value, scale, unit}: value * 10**-scale in unit. quantity(3214, 4, "1") is 0.3214."""
    return {"value": value, "scale": scale, "unit": unit}


def magnitude(q: Mapping[str, Any]) -> Fraction:
    return Fraction(q["value"], 10 ** q["scale"])


def distance(a: Mapping[str, Any], b: Mapping[str, Any], period: Optional[Mapping[str, Any]] = None) -> Fraction:
    """|a - b|, or the shorter way round a circle when the parameter has a period."""
    d = abs(magnitude(a) - magnitude(b))
    if period is None:
        return d
    p = magnitude(period)
    d %= p
    return min(d, p - d)


def retracted(name: str) -> Optional[str]:
    """What retracted construct a metric or parameter name belongs to, or None."""
    if name in RETRACTED_NAMES:
        return RETRACTED_NAMES[name]
    for fragment, reason in RETRACTED_FRAGMENTS.items():
        if fragment in name:
            return reason
    return None


def _instant(ts: str) -> Tuple[datetime, Fraction]:
    whole, _, fraction = ts[:-1].partition(".")
    return datetime.fromisoformat(whole), Fraction(int(fraction or "0"), 10 ** len(fraction))


def _is_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not _TIMESTAMP_RE.match(value):
        return False
    try:
        _instant(value)
    except ValueError:                      # matches the pattern but is no date, e.g. month 13
        return False
    return True


def _member(value: Any, vocabulary: Any) -> bool:
    return isinstance(value, str) and value in vocabulary


# --------------------------------------------------------------------------------------------
# Single records
# --------------------------------------------------------------------------------------------

class _Check:
    """Accumulates violations so one pass reports every problem, not just the first."""

    def __init__(self) -> None:
        self.violations: List[str] = []

    def fail(self, code: str, message: str) -> None:
        self.violations.append(f"{code}: {message}")

    def fields(self, value: Any, path: str, required: Tuple[str, ...], optional: Tuple[str, ...] = ()) -> bool:
        """True when every required field is present (unknown fields are reported, not fatal)."""
        if not isinstance(value, dict):
            self.fail("SCHEMA_TYPE", f"{path} must be an object")
            return False
        for key in required:
            if key not in value:
                self.fail("SCHEMA_MISSING", f"{path}.{key} is required")
        for key in sorted(set(value) - set(required) - set(optional)):
            reason = retracted(key)
            if reason:
                self.fail("RETRACTED_CONSTRUCT", f"{path}.{key} is {reason}")
            else:
                self.fail("SCHEMA_UNKNOWN_FIELD", f"{path}.{key} is not part of OSIRIS-TELEMETRY-V1")
        return all(key in value for key in required)

    def text(self, value: Any, path: str) -> bool:
        if isinstance(value, str) and value.strip():
            return True
        self.fail("SCHEMA_TYPE", f"{path} must be a non-empty string")
        return False

    def integer(self, value: Any, path: str, minimum: int = -JCS_SAFE_INTEGER_MAX, maximum: int = JCS_SAFE_INTEGER_MAX) -> bool:
        if isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum:
            return True
        self.fail("SCHEMA_TYPE", f"{path} must be an integer in [{minimum}, {maximum}]")
        return False

    def timestamp(self, value: Any, path: str) -> bool:
        if _is_timestamp(value):
            return True
        self.fail("SCHEMA_TIMESTAMP", f"{path} must be RFC 3339 UTC like 2026-10-07T11:28:31.396607Z")
        return False

    def name(self, value: Any, path: str) -> bool:
        if not isinstance(value, str) or not _NAME_RE.match(value):
            self.fail("SCHEMA_NAME", f"{path} must be lowercase snake_case, got {value!r}")
            return False
        reason = retracted(value)
        if reason:
            self.fail("RETRACTED_CONSTRUCT", f"{path} {value!r} is {reason}")
            return False
        return True

    def quantity(self, value: Any, path: str) -> bool:
        if not self.fields(value, path, ("value", "scale", "unit")):
            return False
        checks = [
            self.integer(value["value"], f"{path}.value"),
            self.integer(value["scale"], f"{path}.scale", 0, MAX_SCALE),
            self.text(value["unit"], f"{path}.unit"),
        ]
        return all(checks)

    def same_unit(self, quantities: Mapping[str, Mapping[str, Any]], unit: str, path: str) -> bool:
        wrong = sorted(name for name, q in quantities.items() if q["unit"] != unit)
        for name in wrong:
            self.fail("UNIT_MISMATCH", f"{path}.{name} is in {quantities[name]['unit']!r}, not {unit!r}")
        return not wrong


def _frame_rules(chk: _Check, rec: Mapping[str, Any]) -> None:
    src = rec["source"]
    if chk.fields(src, "frame.source", ("kind", "node", "generator"), ("seed",)):
        chk.text(src["node"], "frame.source.node")
        chk.text(src["generator"], "frame.source.generator")
        if "seed" in src:
            chk.integer(src["seed"], "frame.source.seed", 0)
        if not _member(src["kind"], SOURCE_KINDS):
            chk.fail("SCHEMA_ENUM", f"frame.source.kind must be one of {sorted(SOURCE_KINDS)}, got {src['kind']!r}")
        else:
            if src["kind"] == "SYNTHETIC" and "seed" not in src:
                chk.fail("UNSEEDED_SYNTHETIC", "SYNTHETIC telemetry must name the seed that regenerates it")
            expected = "MEASURED" if src["kind"] == "HARDWARE" else "SIMULATED"
            if _member(rec["evidence_class"], EVIDENCE_CLASSES) and rec["evidence_class"] != expected:
                chk.fail("SOURCE_CLASS_MISMATCH",
                         f"{src['kind']} telemetry is {expected}, not {rec['evidence_class']}")
    if not _member(rec["evidence_class"], EVIDENCE_CLASSES):
        chk.fail("SCHEMA_ENUM", f"frame.evidence_class must be one of {sorted(EVIDENCE_CLASSES)}")

    win = rec["window"]
    if chk.fields(win, "frame.window", ("start", "end", "samples")):
        chk.integer(win["samples"], "frame.window.samples", 1)
        times = [chk.timestamp(win["start"], "frame.window.start"), chk.timestamp(win["end"], "frame.window.end")]
        if all(times) and _instant(win["start"]) > _instant(win["end"]):
            chk.fail("WINDOW_ORDER", "frame.window.start is after frame.window.end")
        if all(times) and _is_timestamp(rec["recorded_at"]) and _instant(win["end"]) > _instant(rec["recorded_at"]):
            chk.fail("WINDOW_AFTER_RECORD", "a frame cannot summarize samples taken after it was recorded")

    metrics = rec["metrics"]
    if not isinstance(metrics, dict) or not metrics:
        chk.fail("SCHEMA_EMPTY", "frame.metrics must be a non-empty object of name -> quantity")
        return
    for name, q in sorted(metrics.items()):
        chk.name(name, "frame.metrics key")
        chk.quantity(q, f"frame.metrics.{name}")


def _action_rules(chk: _Check, rec: Mapping[str, Any]) -> None:
    if not isinstance(rec["action_type"], str) or not _ACTION_TYPE_RE.match(rec["action_type"]):
        chk.fail("SCHEMA_NAME", "action.action_type must be UPPER_SNAKE_CASE")
    if not isinstance(rec["applied"], bool):
        chk.fail("SCHEMA_TYPE", "action.applied must be a boolean")

    par = rec["parameter"]
    values = {"old_value": rec["old_value"], "new_value": rec["new_value"]}
    # all([...]), not all(...): every check runs, so every problem is reported.
    sound = all([chk.quantity(q, f"action.{k}") for k, q in values.items()])
    if chk.fields(par, "action.parameter", ("name", "unit"), ("period",)):
        chk.name(par["name"], "action.parameter.name")
        sound = chk.text(par["unit"], "action.parameter.unit") and sound
        if "period" in par:
            periodic = chk.quantity(par["period"], "action.parameter.period")
            if periodic and magnitude(par["period"]) <= 0:
                chk.fail("SCHEMA_VALUE", "action.parameter.period must be positive")
                periodic = False
            values["parameter.period"] = par["period"]
            sound = sound and periodic
        if sound and chk.same_unit(values, par["unit"], "action") and isinstance(rec["applied"], bool):
            if rec["applied"] and distance(rec["old_value"], rec["new_value"], par.get("period")) == 0:
                way = " modulo the period" if "period" in par else ""
                chk.fail("NO_OP_APPLIED", f"new_value equals old_value{way}, so applied must be false")

    trig = rec["trigger"]
    if chk.fields(trig, "action.trigger", _TRIGGER_FIELDS):
        chk.name(trig["metric"], "action.trigger.metric")
        if chk.integer(trig["frame_seq"], "action.trigger.frame_seq", 1) and isinstance(rec["seq"], int):
            if trig["frame_seq"] >= rec["seq"]:
                chk.fail("TRIGGER_NOT_EARLIER", "action.trigger.frame_seq must name an earlier record")
        pair = {"observed": trig["observed"], "threshold": trig["threshold"]}
        if all([chk.quantity(q, f"action.trigger.{k}") for k, q in pair.items()]):
            if chk.same_unit(pair, trig["observed"]["unit"], "action.trigger"):
                compare = _COMPARE[trig["comparison"]] if _member(trig["comparison"], _COMPARE) else None
                if compare and not compare(magnitude(trig["observed"]), magnitude(trig["threshold"])):
                    chk.fail("TRIGGER_NOT_MET",
                             f"observed {magnitude(trig['observed'])} is not {trig['comparison']} "
                             f"threshold {magnitude(trig['threshold'])}")
        if not _member(trig["comparison"], _COMPARE):
            chk.fail("SCHEMA_ENUM", f"action.trigger.comparison must be one of {sorted(_COMPARE)}")


def record_violations(record: Any) -> List[str]:
    """Schema and single-record rules ("CODE: message"); an empty list means valid on its own."""
    chk = _Check()
    if not isinstance(record, dict):
        chk.fail("SCHEMA_TYPE", "a telemetry record must be an object")
        return chk.violations
    kind = record.get("document_type")
    if kind not in (FRAME, ACTION):
        chk.fail("SCHEMA_VALUE", f"document_type must be {FRAME} or {ACTION}, got {kind!r}")
        return chk.violations
    path = "frame" if kind == FRAME else "action"
    if not chk.fields(record, path, _FRAME_FIELDS if kind == FRAME else _ACTION_FIELDS):
        return chk.violations
    if record["schema_version"] != SCHEMA_VERSION:
        chk.fail("SCHEMA_VALUE", f"{path}.schema_version must be {SCHEMA_VERSION!r}")
    chk.text(record["run_id"], f"{path}.run_id")
    chk.integer(record["seq"], f"{path}.seq", 1)
    if not isinstance(record["prev"], str) or not _DIGEST_RE.match(record["prev"]):
        chk.fail("SCHEMA_DIGEST", f"{path}.prev must be sha256:<64 lowercase hex>")
    chk.timestamp(record["recorded_at"], f"{path}.recorded_at")
    (_frame_rules if kind == FRAME else _action_rules)(chk, record)
    return chk.violations


# --------------------------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------------------------

class _Chain:
    """What a run has accepted so far: rules that depend on earlier records live here."""

    def __init__(self) -> None:
        self.run_id: Optional[str] = None
        self.count = 0
        self.head = GENESIS_DIGEST
        self.last: Optional[Tuple[datetime, Fraction]] = None
        self.frames: Dict[int, Mapping[str, Any]] = {}

    def problems(self, rec: Mapping[str, Any]) -> List[str]:
        """Assumes record_violations(rec) is empty."""
        chk = _Check()
        if rec["seq"] != self.count + 1:
            chk.fail("SEQ_ORDER", f"seq {rec['seq']} where {self.count + 1} was expected")
        if rec["prev"] != self.head:
            code = "CHAIN_RESTART" if rec["prev"] == GENESIS_DIGEST else "CHAIN_BROKEN"
            chk.fail(code, f"prev {rec['prev']} is not the digest of the line before ({self.head})")
        if self.run_id is not None and rec["run_id"] != self.run_id:
            chk.fail("RUN_ID_CHANGED", f"run_id {rec['run_id']!r} in a {self.run_id!r} run")
        if self.last is not None and _instant(rec["recorded_at"]) < self.last:
            chk.fail("TIME_ORDER", "recorded_at is earlier than the record before it")
        if rec["document_type"] == ACTION:
            trig = rec["trigger"]
            frame = self.frames.get(trig["frame_seq"])
            metric = frame["metrics"].get(trig["metric"]) if frame else None
            if frame is None:
                chk.fail("TRIGGER_UNKNOWN_FRAME", f"no frame with seq {trig['frame_seq']} earlier in this run")
            elif metric is None:
                chk.fail("TRIGGER_UNKNOWN_METRIC", f"frame {trig['frame_seq']} has no metric {trig['metric']!r}")
            elif (magnitude(metric), metric["unit"]) != (magnitude(trig["observed"]), trig["observed"]["unit"]):
                chk.fail("TRIGGER_MISMATCH", f"observed differs from frame {trig['frame_seq']}'s {trig['metric']}")
        return chk.violations

    def accept(self, rec: Optional[Mapping[str, Any]], digest: str) -> None:
        """Moves the head on; a record that failed its checks advances it without adding context."""
        self.count += 1
        self.head = digest
        if rec is None:
            return
        if self.run_id is None:
            self.run_id = rec["run_id"]
        self.last = _instant(rec["recorded_at"])
        if rec["document_type"] == FRAME:
            self.frames[rec["seq"]] = rec


@dataclass(frozen=True)
class RunSummary:
    run_id: Optional[str]
    records: int
    head: str
    violations: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations


def _raw(line: bytes | str) -> bytes:
    raw = line.encode("utf-8") if isinstance(line, str) else bytes(line)
    return raw[:-1] if raw.endswith(b"\n") else raw


def verify_run(lines: Iterable[bytes | str]) -> RunSummary:
    """Checks a whole run, one line per record; every problem is reported as "line N: CODE: message".

    Pass the file's lines without newlines (data.splitlines()) or iterate the file in binary mode.
    """
    chain = _Chain()
    violations: List[str] = []
    for number, line in enumerate(lines, 1):
        raw = _raw(line)
        problems: List[str] = []
        record = None
        try:
            record = strict_parse_json(raw)
            if canonicalize_json(record) != raw:
                problems.append("NOT_CANONICAL: the line is not the OSIRIS-CANONICAL-JSON-V1 form of its record")
        except (SchemaValidationError, ValueError) as exc:
            problems.append(f"NOT_CANONICAL_JSON: {exc}")
        sound = False
        if not problems:
            problems = record_violations(record)
            sound = not problems
            problems = problems or chain.problems(record)
        violations.extend(f"line {number}: {p}" for p in problems)
        chain.accept(record if sound else None, canonical_sha256(raw))
    return RunSummary(chain.run_id, chain.count, chain.head, violations)


class TelemetryRun:
    """Writes one run. frame() and action() return the canonical line to append (no newline)."""

    def __init__(self, run_id: str, source: Mapping[str, Any], evidence_class: str) -> None:
        self.run_id = run_id
        self.source = dict(source)
        self.evidence_class = evidence_class
        self._chain = _Chain()

    def frame(self, recorded_at: str, window: Mapping[str, Any], metrics: Mapping[str, Any]) -> bytes:
        return self._append({
            "document_type": FRAME, "recorded_at": recorded_at, "source": self.source,
            "evidence_class": self.evidence_class, "window": dict(window), "metrics": dict(metrics),
        })

    def action(self, recorded_at: str, action_type: str, parameter: Mapping[str, Any],
               old_value: Mapping[str, Any], new_value: Mapping[str, Any], applied: bool,
               trigger: Mapping[str, Any]) -> bytes:
        return self._append({
            "document_type": ACTION, "recorded_at": recorded_at, "action_type": action_type,
            "parameter": dict(parameter), "old_value": old_value, "new_value": new_value,
            "applied": applied, "trigger": dict(trigger),
        })

    def summary(self) -> RunSummary:
        return RunSummary(self._chain.run_id, self._chain.count, self._chain.head)

    def _append(self, body: Dict[str, Any]) -> bytes:
        record = {"schema_version": SCHEMA_VERSION, "run_id": self.run_id,
                  "seq": self._chain.count + 1, "prev": self._chain.head, **body}
        problems = record_violations(record) or self._chain.problems(record)
        if problems:
            raise TelemetryValidationError(problems)
        line = canonicalize_json(record)
        self._chain.accept(record, canonical_sha256(line))
        return line


def seal_payload(summary: RunSummary) -> bytes:
    """The bytes an enrolled node key signs (signing.sign_bytes) to seal a verified run."""
    if not summary.ok or summary.records == 0:
        raise TelemetryValidationError(summary.violations or ["EMPTY_RUN: there is nothing to seal"])
    return canonicalize_json({
        "schema_version": SCHEMA_VERSION, "document_type": SEAL, "run_id": summary.run_id,
        "records": summary.records, "head": summary.head,
    })


# --------------------------------------------------------------------------------------------
# Drift
# --------------------------------------------------------------------------------------------
#
# A drift check compares a statistic of the observed series with the same statistic of replicas
# drawn from a model that has no drift: posterior predictive replicates, kept in the observed
# order and conditions. The caller draws the replicas and chooses every threshold (alpha, CUSUM
# allowance and limit) before seeing the data; nothing here has a default threshold.
#
# dispersion is the heterogeneity check: it grows with any extra job-to-job noise. The time-order
# checks (lag1_autocorrelation, trend_r2, cusum_peak, session_eta2) do not change when the series
# is scaled, so extra noise without time structure does not move them; only ordering does.
# All arithmetic is exact: values are ints or Fractions, never floats.

Number = Union[int, Fraction]
DRIFT_CHECKS = ("dispersion", "lag1_autocorrelation", "trend_r2", "cusum_peak", "session_eta2")
_EPOCH = datetime(1970, 1, 1)


def _exact(values: Iterable[Number], minimum: int, what: str = "values") -> List[Fraction]:
    out = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, Fraction)):
            raise TypeError(f"drift statistics take ints and Fractions, not {type(v).__name__}")
        out.append(Fraction(v))
    if len(out) < minimum:
        raise ValueError(f"need at least {minimum} {what}, got {len(out)}")
    return out


def _centered(xs: List[Fraction]) -> Tuple[List[Fraction], Fraction]:
    """Deviations from the mean and their sum of squares."""
    mean = sum(xs, Fraction(0)) / len(xs)
    dev = [x - mean for x in xs]
    return dev, sum((d * d for d in dev), Fraction(0))


def _paired(times: Sequence[Number], values: Sequence[Number]) -> Tuple[List[Fraction], List[Fraction]]:
    ts, xs = _exact(times, 3, "times"), _exact(values, 3)
    if len(ts) != len(xs):
        raise ValueError(f"{len(ts)} times for {len(xs)} values")
    return ts, xs


def dispersion(values: Sequence[Number]) -> Fraction:
    """Sample variance (n - 1 denominator)."""
    xs = _exact(values, 2)
    return _centered(xs)[1] / (len(xs) - 1)


def lag1_autocorrelation(values: Sequence[Number]) -> Fraction:
    """sum(d[t] * d[t+1]) / sum(d[t]**2), d the deviations from the mean; 0 for a constant series."""
    dev, ss = _centered(_exact(values, 3))
    if ss == 0:
        return Fraction(0)
    return sum((a * b for a, b in zip(dev, dev[1:])), Fraction(0)) / ss


def trend_slope(times: Sequence[Number], values: Sequence[Number]) -> Fraction:
    """Least-squares slope of value on time, in value units per time unit."""
    ts, xs = _paired(times, values)
    dt, stt = _centered(ts)
    if stt == 0:
        raise ValueError("every time is the same, so there is no trend to fit")
    return sum((a * b for a, b in zip(dt, _centered(xs)[0])), Fraction(0)) / stt


def trend_r2(times: Sequence[Number], values: Sequence[Number]) -> Fraction:
    """Squared correlation of value with time (either direction); 0 for a constant series."""
    ts, xs = _paired(times, values)
    (dt, stt), (dx, sxx) = _centered(ts), _centered(xs)
    if stt == 0:
        raise ValueError("every time is the same, so there is no trend to fit")
    if sxx == 0:
        return Fraction(0)
    sxy = sum((a * b for a, b in zip(dt, dx)), Fraction(0))
    return sxy * sxy / (stt * sxx)


def cusum_peak(values: Sequence[Number]) -> Fraction:
    """max S[k]**2 / sum(d**2), S[k] the running sum of deviations from the mean.

    The squared, scale-free CUSUM change-point statistic: small when the level never shifts, at
    most n / 4, which a clean step halfway reaches. 0 for a constant series.
    """
    dev, ss = _centered(_exact(values, 2))
    if ss == 0:
        return Fraction(0)
    peak, running = Fraction(0), Fraction(0)
    for d in dev:
        running += d
        peak = max(peak, running * running)
    return peak / ss


def session_eta2(values: Sequence[Number], sessions: Sequence[Hashable]) -> Fraction:
    """Share of the variation that lies between sessions (one-way ANOVA eta squared).

    sessions labels each value, e.g. with the backend calibration it ran under. 0 for a constant
    series; 1 when every session is constant at its own level.
    """
    xs = _exact(values, 2)
    if len(sessions) != len(xs):
        raise ValueError(f"{len(sessions)} session labels for {len(xs)} values")
    groups: Dict[Hashable, List[Fraction]] = {}
    for label, x in zip(sessions, xs):
        groups.setdefault(label, []).append(x)
    if len(groups) < 2:
        raise ValueError("needs at least two sessions")
    total = _centered(xs)[1]
    if total == 0:
        return Fraction(0)
    within = sum((_centered(g)[1] for g in groups.values()), Fraction(0))
    return (total - within) / total


@dataclass(frozen=True)
class Cusum:
    upper: List[Fraction]
    lower: List[Fraction]
    alarm: Optional[int]          # index of the first value at which either sum passed the limit


def cusum(values: Sequence[Number], target: Number, allowance: Number, limit: Number) -> Cusum:
    """Two-sided tabular CUSUM (Page, 1954) in the values' own units, for monitoring.

    upper[k] = max(0, upper[k-1] + x[k] - target - allowance)
    lower[k] = max(0, lower[k-1] + target - x[k] - allowance)
    alarm is the first k where either exceeds limit. target, allowance and limit are the caller's;
    how often a limit alarms on a series without drift depends on the series' scale and length.
    """
    xs = _exact(values, 1)
    target, allowance, limit = _exact((target, allowance, limit), 3, "parameters")
    if allowance < 0 or limit <= 0:
        raise ValueError("allowance must be >= 0 and limit > 0")
    upper, lower, alarm = [], [], None
    u = l = Fraction(0)
    for k, x in enumerate(xs):
        u = max(Fraction(0), u + x - target - allowance)
        l = max(Fraction(0), l + target - x - allowance)
        upper.append(u)
        lower.append(l)
        if alarm is None and (u > limit or l > limit):
            alarm = k
    return Cusum(upper, lower, alarm)


def predictive_p_value(observed: Number, replicated: Sequence[Number], tail: str = "upper") -> Fraction:
    """(1 + replicas at least as extreme as observed) / (1 + replicas).

    Never 0: with S replicas the smallest p is 1 / (S + 1). Ties count as at least as extreme.
    """
    obs = _exact((observed,), 1, "observed")[0]
    reps = _exact(replicated, 1, "replicas")
    if tail == "upper":
        extreme = sum(1 for r in reps if r >= obs)
    elif tail == "lower":
        extreme = sum(1 for r in reps if r <= obs)
    else:
        raise ValueError(f"tail must be 'upper' or 'lower', got {tail!r}")
    return Fraction(1 + extreme, 1 + len(reps))


def drift_p_values(times: Sequence[Number], values: Sequence[Number], replicates: Sequence[Sequence[Number]],
                   sessions: Optional[Sequence[Hashable]] = None) -> Dict[str, Fraction]:
    """Upper-tail predictive p-value of every check in DRIFT_CHECKS for one series.

    replicates are series drawn from the no-drift model, each as long as values and in the same
    order. session_eta2 is included only when sessions name at least two sessions.
    """
    if not replicates or any(len(r) != len(values) for r in replicates):
        raise ValueError("every replicate must be a series as long as the observed one")
    checks = {
        "dispersion": dispersion,
        "lag1_autocorrelation": lag1_autocorrelation,
        "trend_r2": lambda xs: trend_r2(times, xs),
        "cusum_peak": cusum_peak,
    }
    if sessions is not None and len(set(sessions)) >= 2:
        checks["session_eta2"] = lambda xs: session_eta2(xs, sessions)
    return {name: predictive_p_value(stat(values), [stat(r) for r in replicates])
            for name, stat in checks.items()}


def _seconds(ts: str) -> Fraction:
    whole, fraction = _instant(ts)
    return (whole - _EPOCH) // timedelta(seconds=1) + fraction


def metric_series(lines: Iterable[bytes | str], metric: str) -> Tuple[List[Fraction], List[Fraction]]:
    """(times, values) of one metric across a verified run's frames, in chain order.

    A time is the frame's window midpoint in seconds after the first such frame's midpoint.
    Raises TelemetryValidationError if the run does not verify or the metric changes unit.
    """
    lines = list(lines)
    summary = verify_run(lines)
    if not summary.ok:
        raise TelemetryValidationError(summary.violations)
    times: List[Fraction] = []
    values: List[Fraction] = []
    unit = None
    for line in lines:
        rec = strict_parse_json(_raw(line))
        q = rec.get("metrics", {}).get(metric) if rec["document_type"] == FRAME else None
        if q is None:
            continue
        if unit is not None and q["unit"] != unit:
            raise TelemetryValidationError([f"UNIT_MISMATCH: {metric} is in {q['unit']!r} at seq {rec['seq']}, "
                                            f"{unit!r} before"])
        unit = q["unit"]
        times.append((_seconds(rec["window"]["start"]) + _seconds(rec["window"]["end"])) / 2)
        values.append(magnitude(q))
    return [t - times[0] for t in times], values
