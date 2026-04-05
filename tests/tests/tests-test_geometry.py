tests/test_geometry.py

import math
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from geometry.bounds   import ManifoldBounds, DEFAULT_BOUNDS
from geometry.tilt     import calculate_syncletic_tilt, _bessel_j0
from geometry.manifest import (
    GeometryManifest,
    MalformationType,
    Severity,
    validate_position_dict,
    validate_tilt_dict,
    has_blocking,
)


BOUNDS = ManifoldBounds()


# ── Bessel approximation ──────────────────────────────────────────────

def test_bessel_j0_at_zero():
    assert abs(_bessel_j0(0.0) - 1.0) < 1e-5


def test_bessel_j0_first_zero():
    # J0 first zero near x=2.4048
    val = _bessel_j0(2.4048)
    assert abs(val) < 0.01


def test_bessel_j0_finite_large_x():
    for x in [10.0, 50.0, 100.0]:
        assert math.isfinite(_bessel_j0(x))


# ── Tilt engine ───────────────────────────────────────────────────────

def test_tilt_correct_returns_finite():
    r = calculate_syncletic_tilt(1.0, 5.0, 2, True)
    for k, v in r.items():
        assert math.isfinite(v), f"{k}={v} not finite"


def test_tilt_incorrect_negative_alpha():
    r = calculate_syncletic_tilt(1.0, 5.0, 0, False)
    assert r["alpha_delta"] < 0


def test_tilt_extreme_response_time_clamped():
    r1 = calculate_syncletic_tilt(1.0, 0.001, 1, True)
    r2 = calculate_syncletic_tilt(1.0, 9999.0, 1, True)
    for k in r1:
        assert math.isfinite(r1[k])
        assert math.isfinite(r2[k])


def test_tilt_l_net_saturates_via_tanh():
    low  = calculate_syncletic_tilt(1.0, 5.0, 1,  True)["L_net_delta"]
    high = calculate_syncletic_tilt(1.0, 5.0, 50, True)["L_net_delta"]
    assert high < 1.01
    assert high >= low


def test_tilt_l_net_zero_streak():
    r = calculate_syncletic_tilt(1.0, 5.0, 0, True)
    assert r["L_net_delta"] == round(math.tanh(0.0), 4)


def test_tilt_cave_delta_sign_preserved():
    # cave_delta sign comes from sinc_val via copysign
    r = calculate_syncletic_tilt(1.0, 0.5, 1, True)
    assert math.isfinite(r["cave_delta"])


def test_tilt_incorrect_l_net_negative():
    r = calculate_syncletic_tilt(1.0, 5.0, 3, False)
    assert r["L_net_delta"] == -0.5


# ── Position validation ───────────────────────────────────────────────

def test_valid_position_no_reports():
    pos = {"alpha": 1.0, "cave_depth": 0.5, "L_net": 0.5}
    reports = validate_position_dict("s1", pos, None, BOUNDS, "test", None)
    assert reports == []


def test_nan_alpha_critical():
    pos = {"alpha": float("nan"), "cave_depth": 0.5, "L_net": 0.5}
    reports = validate_position_dict("s1", pos, None, BOUNDS, "test", None)
    assert any(r.malformation_type == MalformationType.NAN_COORDINATE for r in reports)
    assert any(r.severity == Severity.CRITICAL for r in reports)


def test_inf_coordinate_critical():
    pos = {"alpha": float("inf"), "cave_depth": 0.5, "L_net": 0.5}
    reports = validate_position_dict("s1", pos, None, BOUNDS, "test", None)
    assert any(r.severity == Severity.CRITICAL for r in reports)


def test_below_floor_error():
    pos = {"alpha": 0.001, "cave_depth": 0.5, "L_net": 0.5}
    reports = validate_position_dict("s1", pos, None, BOUNDS, "test", None)
    assert any(r.malformation_type == MalformationType.BELOW_FLOOR for r in reports)
    assert any(r.severity == Severity.ERROR for r in reports)


def test_above_ceiling_error():
    pos = {"alpha": 99.0, "cave_depth": 0.5, "L_net": 0.5}
    reports = validate_position_dict("s1", pos, None, BOUNDS, "test", None)
    assert any(r.malformation_type == MalformationType.ABOVE_CEILING for r in reports)


def test_teleport_detected():
    prev = {"alpha": 1.0, "cave_depth": 0.5, "L_net": 0.5}
    pos  = {"alpha": 9.9, "cave_depth": 9.9, "L_net": 9.9}
    reports = validate_position_dict("s1", pos, prev, BOUNDS, "test", None)
    assert any(r.malformation_type == MalformationType.POSITION_TELEPORT for r in reports)


# ── Tilt validation ───────────────────────────────────────────────────

def test_valid_tilt_no_reports():
    tilt = {"alpha_delta": 0.1, "cave_delta": 0.05, "L_net_delta": 0.2}
    reports = validate_tilt_dict("s1", tilt, BOUNDS, "test")
    assert reports == []


def test_tilt_nan_critical():
    tilt = {"alpha_delta": float("nan"), "cave_delta": 0.0, "L_net_delta": 0.0}
    reports = validate_tilt_dict("s1", tilt, BOUNDS, "test")
    assert any(r.severity == Severity.CRITICAL for r in reports)


def test_tilt_exceeds_max_delta_error():
    tilt = {"alpha_delta": 5.0, "cave_delta": 0.0, "L_net_delta": 0.0}
    reports = validate_tilt_dict("s1", tilt, BOUNDS, "test")
    assert any(r.malformation_type == MalformationType.IMPLAUSIBLE_DELTA for r in reports)


def test_zero_magnitude_tilt_warning():
    tilt = {"alpha_delta": 0.0, "cave_delta": 0.0, "L_net_delta": 0.0}
    reports = validate_tilt_dict("s1", tilt, BOUNDS, "test")
    assert any(r.malformation_type == MalformationType.ZERO_MAGNITUDE_TILT for r in reports)
    assert any(r.severity == Severity.WARNING for r in reports)


# ── has_blocking helper ───────────────────────────────────────────────

def test_has_blocking_true_on_error(manifest, tmp_path):
    bad = {"alpha": float("nan"), "cave_depth": 0.5, "L_net": 0.5}
    _, _, reports = manifest.check_position("s1", bad, context="test")
    assert has_blocking(reports)


def test_has_blocking_false_on_warning(manifest):
    tilt = {"alpha_delta": 0.0, "cave_delta": 0.0, "L_net_delta": 0.0}
    _, _, reports = manifest.check_tilt("s1", tilt, context="test")
    blocking = has_blocking(reports)
    assert not blocking


# ── GeometryManifest stateful ─────────────────────────────────────────

def test_manifest_returns_last_good_on_bad(manifest):
    good = {"alpha": 1.0, "cave_depth": 0.5, "L_net": 0.5}
    manifest.check_position("s2", good, context="setup")
    bad = {"alpha": float("nan"), "cave_depth": 0.5, "L_net": 0.5}
    ok, safe, _ = manifest.check_position("s2", bad, context="bad")
    assert not ok
    assert safe == good


def test_manifest_accumulates_unresolved(manifest):
    bad = {"alpha": float("nan"), "cave_depth": 0.5, "L_net": 0.5}
    manifest.check_position("s3", bad, context="t1")
    manifest.check_position("s3", bad, context="t2")
    assert manifest.summary()["unresolved"] >= 2


def test_manifest_acknowledge_resolves(manifest):
    bad = {"alpha": float("nan"), "cave_depth": 0.5, "L_net": 0.5}
    _, _, reports = manifest.check_position("s4", bad, context="ack")
    assert reports
    rid = reports[0].report_id
    assert manifest.acknowledge(rid, "admin") is True
    ids = [r["report_id"] for r in manifest.unresolved()]
    assert rid not in ids


def test_manifest_persists_and_reloads(tmp_path):
    from geometry.manifest import GeometryManifest
    path = str(tmp_path / "geo.json")
    m1 = GeometryManifest(persist_path=path)
    bad = {"alpha": float("nan"), "cave_depth": 0.5, "L_net": 0.5}
    m1.check_position("s5", bad, context="persist_test")
    count_before = m1.summary()["unresolved"]

    m2 = GeometryManifest(persist_path=path)
    assert m2.summary()["unresolved"] == count_before