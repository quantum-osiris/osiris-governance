"""Drift checks on OSIRIS-TELEMETRY-V1 series: exact statistics and predictive p-values.

Hand-computed series only. Nothing here represents a real experiment.
"""

from fractions import Fraction as F

import pytest

from osiris_governance import telemetry
from osiris_governance.errors import TelemetryValidationError
from osiris_governance.telemetry import TelemetryRun, quantity

HARDWARE = {"kind": "HARDWARE", "node": "test_node", "generator": "test-probe 0.0"}


FIVE_MINUTES_APART = (("2026-10-27T14:00:00Z", "2026-10-27T14:00:02Z"),
                      ("2026-10-27T14:05:00Z", "2026-10-27T14:05:02Z"),
                      ("2026-10-27T14:10:00Z", "2026-10-27T14:10:02Z"))


def run_lines(values, windows=FIVE_MINUTES_APART):
    """A verified run with one frame per value, recorded as each window ends."""
    run = TelemetryRun("drift-test-1", HARDWARE, "MEASURED")
    return [run.frame(end, {"start": start, "end": end, "samples": 4000}, {"error_count": quantity(value, 0, "1")})
            for (start, end), value in zip(windows, values)]


# -- statistics -------------------------------------------------------------------

def test_dispersion_is_the_sample_variance():
    assert telemetry.dispersion([1, 2, 3, 4]) == F(5, 3)
    assert telemetry.dispersion([7, 7]) == 0


def test_lag1_autocorrelation_by_hand():
    assert telemetry.lag1_autocorrelation([1, 2, 3, 4]) == F(1, 4)
    assert telemetry.lag1_autocorrelation([1, -1, 1, -1]) == F(-3, 4)
    assert telemetry.lag1_autocorrelation([5, 5, 5]) == 0


def test_time_order_checks_ignore_scale_and_offset():
    xs, ts = [3, 1, 4, 1, 5, 9, 2, 6], list(range(8))
    moved = [7 * x + 11 for x in xs]
    assert telemetry.lag1_autocorrelation(moved) == telemetry.lag1_autocorrelation(xs)
    assert telemetry.trend_r2(ts, moved) == telemetry.trend_r2(ts, xs)
    assert telemetry.cusum_peak(moved) == telemetry.cusum_peak(xs)
    assert telemetry.session_eta2(moved, "aaaabbbb") == telemetry.session_eta2(xs, "aaaabbbb")
    assert telemetry.dispersion(moved) == 49 * telemetry.dispersion(xs)


def test_trend_slope_and_r2():
    assert telemetry.trend_slope([0, 1, 2, 3], [1, 3, 5, 7]) == 2
    assert telemetry.trend_r2([0, 1, 2, 3], [1, 3, 5, 7]) == 1
    assert telemetry.trend_r2([0, 1, 2, 3], [7, 5, 3, 1]) == 1          # either direction
    # times 0..3, values 1, 3, 2, 4: sxy = 4, stt = 5, sxx = 5
    assert telemetry.trend_slope([0, 1, 2, 3], [1, 3, 2, 4]) == F(4, 5)
    assert telemetry.trend_r2([0, 1, 2, 3], [1, 3, 2, 4]) == F(16, 25)
    assert telemetry.trend_r2([0, 1, 2], [4, 4, 4]) == 0
    with pytest.raises(ValueError, match="every time is the same"):
        telemetry.trend_r2([2, 2, 2], [1, 2, 3])
    with pytest.raises(ValueError, match="3 times for 4 values"):
        telemetry.trend_slope([0, 1, 2], [1, 2, 3, 4])


def test_cusum_peak_by_hand():
    assert telemetry.cusum_peak([0, 0, 1, 1]) == 1                      # n / 4: a clean step halfway
    assert telemetry.cusum_peak([0] * 10 + [1] * 10) == 5
    # 0, 1, 0, 1: deviations -1/2, 1/2, -1/2, 1/2; running sums -1/2, 0, -1/2, 0
    assert telemetry.cusum_peak([0, 1, 0, 1]) == F(1, 4)
    assert telemetry.cusum_peak([3, 3, 3]) == 0


def test_session_eta2_by_hand():
    assert telemetry.session_eta2([1, 1, 3, 3], ["a", "a", "b", "b"]) == 1
    # sessions a: 1, 3 and b: 2, 4. total SS 5, within SS 2 + 2
    assert telemetry.session_eta2([1, 3, 2, 4], ["a", "a", "b", "b"]) == F(1, 5)
    assert telemetry.session_eta2([2, 2, 2, 2], "aabb") == 0
    with pytest.raises(ValueError, match="at least two sessions"):
        telemetry.session_eta2([1, 2, 3], "aaa")
    with pytest.raises(ValueError, match="3 session labels for 4 values"):
        telemetry.session_eta2([1, 2, 3, 4], "aab")


def test_statistics_take_exact_numbers_only():
    with pytest.raises(TypeError, match="not float"):
        telemetry.lag1_autocorrelation([0.1, 0.2, 0.3])
    with pytest.raises(TypeError, match="not bool"):
        telemetry.dispersion([True, False])
    with pytest.raises(ValueError, match="at least 3 values"):
        telemetry.lag1_autocorrelation([1, 2])


# -- tabular CUSUM ----------------------------------------------------------------

def test_cusum_alarms_when_a_sum_passes_the_limit():
    result = telemetry.cusum([0, 0, 2, 2, 2], target=0, allowance=F(1, 2), limit=2)
    assert result.upper == [0, 0, F(3, 2), 3, F(9, 2)]
    assert result.lower == [0] * 5
    assert result.alarm == 3


def test_cusum_watches_both_directions_and_may_not_alarm():
    down = telemetry.cusum([0, -2, -2], target=0, allowance=F(1, 2), limit=2)
    assert down.lower == [0, F(3, 2), 3] and down.alarm == 2
    quiet = telemetry.cusum([0, 1, -1, 1], target=0, allowance=1, limit=2)
    assert quiet.alarm is None
    assert telemetry.cusum([0, 0, 2], target=0, allowance=0, limit=2).alarm is None   # 2 is not past 2


def test_cusum_parameters_are_checked():
    with pytest.raises(ValueError, match="allowance must be >= 0"):
        telemetry.cusum([1, 2], target=0, allowance=-1, limit=2)
    with pytest.raises(ValueError, match="limit > 0"):
        telemetry.cusum([1, 2], target=0, allowance=0, limit=0)
    with pytest.raises(TypeError, match="not float"):
        telemetry.cusum([1, 2], target=0, allowance=0, limit=27.0)


# -- predictive p-values ----------------------------------------------------------

def test_predictive_p_value_counts_ties_as_extreme():
    assert telemetry.predictive_p_value(5, [1, 5, 6, 2]) == F(3, 5)
    assert telemetry.predictive_p_value(5, [1, 5, 6, 2], tail="lower") == F(4, 5)
    assert telemetry.predictive_p_value(100, [1, 2, 3]) == F(1, 4)      # never 0
    with pytest.raises(ValueError, match="tail must be"):
        telemetry.predictive_p_value(1, [1], tail="both")
    with pytest.raises(ValueError, match="at least 1 replicas"):
        telemetry.predictive_p_value(1, [])


def test_drift_p_values_flag_a_trend_the_replicas_lack():
    times = list(range(8))
    trending = [10, 11, 12, 13, 14, 15, 16, 17]
    flat = [[10, 17, 12, 15, 11, 16, 13, 14], [14, 10, 16, 11, 17, 12, 15, 13], [13, 16, 10, 15, 12, 17, 11, 14]]
    p = telemetry.drift_p_values(times, trending, flat)
    assert set(p) == {"dispersion", "lag1_autocorrelation", "trend_r2", "cusum_peak"}
    assert p["trend_r2"] == p["lag1_autocorrelation"] == p["cusum_peak"] == F(1, 4)
    assert p["dispersion"] == 1                                         # same values, so same variance


def test_drift_p_values_add_sessions_only_when_there_are_two():
    times, xs, reps = [0, 1, 2, 3], [1, 1, 3, 3], [[1, 3, 1, 3], [3, 1, 3, 1]]
    assert "session_eta2" not in telemetry.drift_p_values(times, xs, reps, sessions="aaaa")
    p = telemetry.drift_p_values(times, xs, reps, sessions="aabb")
    assert p["session_eta2"] == F(1, 3)
    with pytest.raises(ValueError, match="as long as the observed one"):
        telemetry.drift_p_values(times, xs, [[1, 2, 3]])
    with pytest.raises(ValueError, match="as long as the observed one"):
        telemetry.drift_p_values(times, xs, [])


# -- series from a run ------------------------------------------------------------

def test_metric_series_reads_window_midpoints_from_a_verified_run():
    times, values = telemetry.metric_series(run_lines([87, 91, 80]), "error_count")
    assert times == [0, 300, 600]
    assert values == [87, 91, 80]
    assert telemetry.metric_series(run_lines([87, 91, 80]), "absent") == ([], [])


def test_metric_series_keeps_subsecond_precision():
    lines = run_lines([1, 2], windows=(("2026-10-27T14:00:00.25Z", "2026-10-27T14:00:00.75Z"),
                                       ("2026-10-27T14:00:01.5Z", "2026-10-27T14:00:02Z")))
    times, _ = telemetry.metric_series(lines, "error_count")
    assert times == [0, F(5, 4)]


def test_metric_series_times_are_midpoints_not_starts():
    lines = run_lines([1, 2], windows=(("2026-10-27T14:00:00Z", "2026-10-27T14:00:02Z"),
                                       ("2026-10-27T14:05:00Z", "2026-10-27T14:05:10Z")))
    assert telemetry.metric_series(lines, "error_count")[0] == [0, 304]


def test_metric_series_refuses_an_unverified_run():
    lines = run_lines([87, 91, 80])
    tampered = lines[:1] + [lines[1].replace(b'"value":91', b'"value":19')] + lines[2:]
    with pytest.raises(TelemetryValidationError) as err:
        telemetry.metric_series(tampered, "error_count")
    assert any("CHAIN_BROKEN" in v for v in err.value.violations)


def test_metric_series_refuses_a_unit_change():
    run = TelemetryRun("drift-test-2", HARDWARE, "MEASURED")
    win = {"start": "2026-10-27T14:00:00Z", "end": "2026-10-27T14:00:02Z", "samples": 1}
    lines = [run.frame("2026-10-27T14:00:02Z", win, {"t1": quantity(80, 0, "us")}),
             run.frame("2026-10-27T14:00:03Z", win, {"t1": quantity(80000, 0, "ns")})]
    with pytest.raises(TelemetryValidationError, match="UNIT_MISMATCH"):
        telemetry.metric_series(lines, "t1")
