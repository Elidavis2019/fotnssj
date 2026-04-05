tests/test_session_manager.py

"""
Tests for persistent SessionManager.
"""
import sys
import os
import time
import pytest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import fotnssj


@pytest.fixture
def sm(tmp_path):
    return fotnssj.SessionManager(state_root=tmp_path / "state")


def test_get_or_create_returns_default(sm):
    data = sm.get_or_create("alice")
    assert data["current_topic"]  == "addition_basic"
    assert data["current_domain"] == "arithmetic"
    assert data["crystallizations"] == {}


def test_get_or_create_idempotent(sm):
    d1 = sm.get_or_create("bob")
    d2 = sm.get_or_create("bob")
    assert d1 is d2


def test_save_and_get_crystal(sm):
    crystal = fotnssj.Crystallization(
        id="crys-1", student_id="carol", topic="addition_basic",
        question="2+2?", correct_answer="4", explanation="2+2=4",
        times_correct=3,
        position=fotnssj.GeometricPosition.default(),
        tilt=fotnssj.TiltVector(0.1, 0.05, 0.2),
        next_candidates=[], bridge="next?", depth_level=1,
    )
    sm.save_crystal("carol", crystal)
    crystals = sm.get_crystals("carol")
    assert len(crystals) == 1
    assert crystals[0].id == "crys-1"


def test_state_persists_across_instances(tmp_path):
    sm1 = fotnssj.SessionManager(state_root=tmp_path / "state")
    sm1.get_or_create("dave")
    sm1.persist_position(
        "dave",
        fotnssj.GeometricPosition(alpha=2.0, cave_depth=1.0, L_net=1.5)
    )

    sm2 = fotnssj.SessionManager(state_root=tmp_path / "state")
    data = sm2.get_or_create("dave")
    assert abs(data["position"].alpha - 2.0) < 1e-6


def test_crystal_persists_across_instances(tmp_path):
    sm1 = fotnssj.SessionManager(state_root=tmp_path / "state")
    crystal = fotnssj.Crystallization(
        id="crys-persist", student_id="eve", topic="counting",
        question="After 4?", correct_answer="5", explanation="seq",
        times_correct=3,
        position=fotnssj.GeometricPosition.default(),
        tilt=fotnssj.TiltVector(0.8, 0.1, 0.1),
        next_candidates=[], bridge="combine?", depth_level=0,
    )
    sm1.save_crystal("eve", crystal)

    sm2 = fotnssj.SessionManager(state_root=tmp_path / "state")
    crystals = sm2.get_crystals("eve")
    assert any(c.id == "crys-persist" for c in crystals)


def test_all_student_ids_combines_disk_and_memory(tmp_path):
    sm = fotnssj.SessionManager(state_root=tmp_path / "state")
    sm.get_or_create("frank")
    sm.persist_position("frank", fotnssj.GeometricPosition.default())

    sm2 = fotnssj.SessionManager(state_root=tmp_path / "state")
    sm2.get_or_create("grace")   # only in memory

    ids = sm2.all_student_ids()
    assert "frank" in ids
    assert "grace" in ids


def test_streak_persists(tmp_path):
    sm1 = fotnssj.SessionManager(state_root=tmp_path / "state")
    data = sm1.get_or_create("henry")
    data["streak_tracker"]._streaks["addition_basic"] = 2
    sm1._persist("henry")

    sm2 = fotnssj.SessionManager(state_root=tmp_path / "state")
    d2  = sm2.get_or_create("henry")
    assert d2["streak_tracker"].current_streak("addition_basic") == 2