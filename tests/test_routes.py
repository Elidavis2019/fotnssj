"""
Flask route integration tests — no Ollama needed.
Dispatcher callbacks are stubbed.
"""
import sys
import os
import json
import time
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _setup_app(tmp_path):
    """Import fotnssj and override all data paths to tmp_path."""
    # Patch Path constants before module-level code runs
    import fotnssj

    fotnssj.session_manager   = fotnssj.SessionManager(
        state_root=tmp_path / "state"
    )
    fotnssj.raw_session_store = fotnssj.RawSessionStore(
        root=tmp_path / "sessions"
    )
    fotnssj.station_registry  = fotnssj.StationRegistry(
        path=tmp_path / "stations" / "stations.json"
    )
    fotnssj.teacher_auth      = fotnssj.TeacherAuth()
    fotnssj.teacher_auth.PATH = tmp_path / "auth" / "teachers.json"
    fotnssj.teacher_auth.PATH.parent.mkdir(parents=True, exist_ok=True)
    fotnssj.teacher_auth._accounts = {}
    fotnssj.teacher_auth._sessions = {}

    fotnssj.admin_auth        = fotnssj.AdminAuth()
    fotnssj.admin_auth.PATH   = tmp_path / "auth" / "admin.json"
    fotnssj.admin_auth.PATH.parent.mkdir(parents=True, exist_ok=True)
    fotnssj.admin_auth._account = None
    fotnssj.admin_auth._session = None
    fotnssj.admin_auth.setup("admin", "testpass123")

    fotnssj.geometry_manifest = fotnssj.GeometryManifest(
        persist_path=str(tmp_path / "geometry" / "reports.json")
    )
    (tmp_path / "geometry").mkdir(parents=True, exist_ok=True)

    fotnssj.app.config["TESTING"]         = True
    fotnssj.app.config["SECRET_KEY"]      = "test-key"
    fotnssj.app.config["WTF_CSRF_ENABLED"] = False

    return fotnssj.app


@pytest.fixture
def client(tmp_path):
    app = _setup_app(tmp_path)
    with app.test_client() as c:
        with app.app_context():
            yield c


# ── Health ────────────────────────────────────────────────────────────

def test_health_returns_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["status"] == "ok"
    assert "dispatcher" in data
    assert "geometry"   in data


# ── Student routes ────────────────────────────────────────────────────

def test_index_redirects_to_student(client):
    r = client.get("/")
    assert r.status_code == 302
    assert "/student/" in r.headers["Location"]


def test_student_dashboard_renders(client):
    r = client.get("/")
    loc = r.headers["Location"]
    r2  = client.get(loc)
    assert r2.status_code == 200
    assert b"Challenge" in r2.data


def test_student_dashboard_named(client):
    r = client.get("/student/test_alice")
    assert r.status_code == 200
    assert b"Challenge" in r2.data if (r2 := r) else True


def test_submit_correct_answer(client, tmp_path):
    import fotnssj

    # Set up a known question for the student
    client.get("/student/test_bob")
    data = fotnssj.session_manager.get_or_create("test_bob")

    # Inject a known question
    gq = fotnssj.GeneratedQuestion(
        topic="addition_basic", domain="arithmetic",
        question="What is 2 + 2?", correct_answer="4",
        explanation="2+2=4", bridge="next?", source="test",
    )
    data["current_question"] = gq

    with client.session_transaction() as sess:
        sess["student_id"] = "test_bob"

    r = client.post("/submit", data={
        "answer":     "4",
        "start_time": str(time.time() - 3),
    })
    assert r.status_code == 302
    assert "message" in r.headers["Location"]


def test_submit_incorrect_answer(client):
    import fotnssj

    client.get("/student/test_carol")
    data = fotnssj.session_manager.get_or_create("test_carol")
    gq   = fotnssj.GeneratedQuestion(
        topic="addition_basic", domain="arithmetic",
        question="What is 3 + 3?", correct_answer="6",
        explanation="3+3=6", bridge="next?", source="test",
    )
    data["current_question"] = gq

    with client.session_transaction() as sess:
        sess["student_id"] = "test_carol"

    r = client.post("/submit", data={
        "answer":     "5",
        "start_time": str(time.time() - 2),
    })
    assert r.status_code == 302


def test_crystallization_after_streak(client):
    import fotnssj

    sid = "test_streak_student"
    client.get(f"/student/{sid}")
    data    = fotnssj.session_manager.get_or_create(sid)
    tracker = data["streak_tracker"]
    # Prime streak to one below threshold
    tracker._streaks["addition_basic"] = tracker.CRYSTALLIZE_AFTER - 1

    gq = fotnssj.GeneratedQuestion(
        topic="addition_basic", domain="arithmetic",
        question="What is 1 + 1?", correct_answer="2",
        explanation="1+1=2", bridge="next?", source="test",
    )
    data["current_question"] = gq

    with client.session_transaction() as sess:
        sess["student_id"] = sid

    client.post("/submit", data={
        "answer":     "2",
        "start_time": str(time.time() - 1),
    })

    crystals = fotnssj.session_manager.get_crystals(sid)
    assert len(crystals) >= 1


# ── Admin routes ──────────────────────────────────────────────────────

def test_admin_login_redirects_without_credentials(client):
    r = client.get("/admin")
    assert r.status_code == 302
    assert "login" in r.headers["Location"]


def test_admin_login_success(client):
    r = client.post("/admin/login", data={
        "username": "admin",
        "password": "testpass123",
    })
    assert r.status_code == 302
    loc = r.headers["Location"]
    assert "login" not in loc


def test_admin_dashboard_after_login(client):
    client.post("/admin/login", data={
        "username": "admin", "password": "testpass123"
    })
    r = client.get("/admin")
    assert r.status_code == 200
    assert b"FOTNSSJ Admin" in r.data


def test_admin_geometry_page(client):
    client.post("/admin/login", data={
        "username": "admin", "password": "testpass123"
    })
    r = client.get("/admin/geometry")
    assert r.status_code == 200
    assert b"Geometry Manifest" in r.data


def test_admin_export_csv(client):
    client.post("/admin/login", data={
        "username": "admin", "password": "testpass123"
    })
    r = client.get("/admin/export/all")
    assert r.status_code == 200
    assert b"Date" in r.data


def test_admin_geometry_export_json(client):
    client.post("/admin/login", data={
        "username": "admin", "password": "testpass123"
    })
    r = client.get("/admin/geometry/export")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert isinstance(data, list)


# ── Station routes ────────────────────────────────────────────────────

def test_station_not_found(client):
    r = client.get("/station/nonexistent-station-id")
    assert r.status_code == 404


def test_station_seeded_station_renders(client):
    import fotnssj
    stations = fotnssj.station_registry.all_active()
    assert stations, "No seeded stations"
    sid = stations[0].id
    r   = client.get(f"/station/{sid}")
    assert r.status_code == 200
    assert b"Submit" in r.data


def test_station_answer_correct(client):
    import fotnssj
    stations   = fotnssj.station_registry.all_active()
    station    = stations[0]
    student_id = "station_tester"

    # Inject known question
    key = (student_id, station.id)
    gq  = fotnssj.GeneratedQuestion(
        topic=station.topic, domain=station.domain,
        question="Test Q?", correct_answer="yes",
        explanation="yes.", bridge="next?", source="test",
    )
    fotnssj._station_qs[key] = (gq, time.time())

    with client.session_transaction() as sess:
        sess["student_id"] = student_id

    r = client.post(f"/station/{station.id}/answer", data={
        "answer":     "yes",
        "start_time": str(time.time() - 2),
    })
    assert r.status_code == 302