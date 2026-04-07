"""
Tests for DifferentialRenderer — no network needed.
"""
import sys
import os
import json
import base64
import zlib
import time
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sync.differential import DifferentialRenderer, StateDiff, _state_hash


# ── StateDiff wire encoding ───────────────────────────────────────────

def _make_diff(**kwargs):
    defaults = dict(
        student_id="alice",
        from_hash="abc123",
        to_hash="def456",
        position_delta={"alpha": 0.1, "cave_depth": 0.05, "L_net": 0.2},
        tilt_applied={"alpha_delta": 0.1, "cave_delta": 0.05, "L_net_delta": 0.2},
        new_crystals=[],
        streak_delta={"addition_basic": 2},
        event_type="correct",
    )
    defaults.update(kwargs)
    return StateDiff(**defaults)


def test_state_diff_roundtrip():
    diff  = _make_diff()
    wire  = diff.to_wire()
    back  = StateDiff.from_wire(wire)
    assert back.student_id     == diff.student_id
    assert back.position_delta == diff.position_delta
    assert back.event_type     == diff.event_type
    assert back.streak_delta   == diff.streak_delta


def test_wire_is_base64_compressed():
    diff = _make_diff()
    wire = diff.to_wire()
    # Should be decodable base64 → decompressible zlib
    raw = base64.b64decode(wire)
    decompressed = zlib.decompress(raw)
    d = json.loads(decompressed)
    assert d["sid"] == "alice"


def test_state_hash_deterministic():
    pos      = {"alpha": 1.0, "cave_depth": 0.5, "L_net": 0.5}
    streaks  = {"addition_basic": 2}
    cids     = ["id1", "id2"]
    h1 = _state_hash(pos, streaks, cids)
    h2 = _state_hash(pos, streaks, cids)
    assert h1 == h2


def test_state_hash_changes_on_position_change():
    pos1    = {"alpha": 1.0, "cave_depth": 0.5, "L_net": 0.5}
    pos2    = {"alpha": 1.1, "cave_depth": 0.5, "L_net": 0.5}
    streaks = {}
    cids    = []
    assert _state_hash(pos1, streaks, cids) != _state_hash(pos2, streaks, cids)


# ── DifferentialRenderer ──────────────────────────────────────────────

def test_renderer_no_diff_on_same_state():
    r = DifferentialRenderer(endpoint=None)
    pos     = {"alpha": 1.0, "cave_depth": 0.5, "L_net": 0.5}
    tilt    = {"alpha_delta": 0.0, "cave_delta": 0.0, "L_net_delta": 0.0}
    streaks = {}
    cids    = []

    r.record("alice", pos, tilt, streaks, cids, [], "correct")
    r.record("alice", pos, tilt, streaks, cids, [], "correct")  # same state

    with r._lock:
        assert len(r._queue) == 1   # only first record, second was no-op


def test_renderer_diff_on_state_change():
    r = DifferentialRenderer(endpoint=None)
    pos1 = {"alpha": 1.0, "cave_depth": 0.5, "L_net": 0.5}
    pos2 = {"alpha": 1.1, "cave_depth": 0.5, "L_net": 0.5}
    tilt = {"alpha_delta": 0.1, "cave_delta": 0.0, "L_net_delta": 0.0}

    r.record("bob", pos1, tilt, {}, [], [], "correct")
    r.record("bob", pos2, tilt, {}, [], [], "correct")

    with r._lock:
        assert len(r._queue) == 2


def test_renderer_position_delta_computed():
    r    = DifferentialRenderer(endpoint=None)
    pos1 = {"alpha": 1.0, "cave_depth": 0.5, "L_net": 0.5}
    pos2 = {"alpha": 1.2, "cave_depth": 0.5, "L_net": 0.5}
    tilt = {"alpha_delta": 0.2, "cave_delta": 0.0, "L_net_delta": 0.0}

    r.record("carol", pos1, tilt, {}, [], [], "correct")
    r.record("carol", pos2, tilt, {}, [], [], "correct")

    with r._lock:
        second_diff = r._queue[1]

    assert abs(second_diff.position_delta["alpha"] - 0.2) < 1e-4


def test_renderer_new_crystals_only_sends_delta():
    r = DifferentialRenderer(endpoint=None)
    pos  = {"alpha": 1.0, "cave_depth": 0.5, "L_net": 0.5}
    tilt = {"alpha_delta": 0.0, "cave_delta": 0.0, "L_net_delta": 0.0}
    c1   = {"id": "crys-1", "topic": "addition_basic"}
    c2   = {"id": "crys-2", "topic": "doubling"}

    r.record("dave", pos, tilt, {}, ["crys-1"], [c1], "crystallize")
    pos2 = {"alpha": 1.01, "cave_depth": 0.5, "L_net": 0.5}
    r.record("dave", pos2, tilt, {}, ["crys-1", "crys-2"], [c1, c2], "crystallize")

    with r._lock:
        second = r._queue[1]

    assert len(second.new_crystals) == 1
    assert second.new_crystals[0]["id"] == "crys-2"


def test_renderer_streak_delta_only_changed_topics():
    r = DifferentialRenderer(endpoint=None)
    pos  = {"alpha": 1.0, "cave_depth": 0.5, "L_net": 0.5}
    pos2 = {"alpha": 1.1, "cave_depth": 0.5, "L_net": 0.5}
    tilt = {"alpha_delta": 0.1, "cave_delta": 0.0, "L_net_delta": 0.0}

    r.record("eve", pos,  tilt, {"addition_basic": 1, "phonics": 2}, [], [], "correct")
    r.record("eve", pos2, tilt, {"addition_basic": 2, "phonics": 2}, [], [], "correct")

    with r._lock:
        second = r._queue[1]

    assert "addition_basic" in second.streak_delta
    assert "phonics"        not in second.streak_delta