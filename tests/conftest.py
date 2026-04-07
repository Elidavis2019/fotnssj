import os
import sys
import tempfile
import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Point all data paths to temp dirs for tests
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("ADMIN_USER", "admin")
os.environ.setdefault("ADMIN_PASS", "testpass123")
os.environ.setdefault("LLM_BASE_URL", "http://localhost:11434")
os.environ.setdefault("LLM_MODEL", "qwen3:1.5b")


@pytest.fixture
def tmp_data(tmp_path):
    """Provides isolated temp directories for each test."""
    dirs = {
        "state":       tmp_path / "state",
        "sessions":    tmp_path / "sessions",
        "checkpoints": tmp_path / "checkpoints",
        "auth":        tmp_path / "auth",
        "geometry":    tmp_path / "geometry",
        "stations":    tmp_path / "stations",
    }
    for d in dirs.values():
        d.mkdir(parents=True)
    return dirs


@pytest.fixture
def manifest(tmp_path):
    from geometry.manifest import GeometryManifest
    from geometry.bounds import ManifoldBounds
    return GeometryManifest(
        bounds=ManifoldBounds(),
        alert_callback=None,
        persist_path=str(tmp_path / "reports.json"),
    )


@pytest.fixture
def flask_client(tmp_data):
    """Full Flask test client with isolated data dirs."""
    # Patch all path constants before importing app
    import geometry.manifest as gm
    import branches.system   as bs
    from pathlib import Path

    # Override data roots via env so fotnssj.py picks them up
    os.environ["_TEST_STATE_ROOT"]    = str(tmp_data["state"])
    os.environ["_TEST_SESSION_ROOT"]  = str(tmp_data["sessions"])
    os.environ["_TEST_STATION_PATH"]  = str(tmp_data["stations"] / "stations.json")
    os.environ["_TEST_AUTH_PATH"]     = str(tmp_data["auth"])
    os.environ["_TEST_GEO_PATH"]      = str(tmp_data["geometry"] / "reports.json")

    # Import after env is set
    import importlib
    import fotnssj
    importlib.reload(fotnssj)

    fotnssj.app.config["TESTING"] = True
    fotnssj.app.config["WTF_CSRF_ENABLED"] = False

    with fotnssj.app.test_client() as client:
        yield client