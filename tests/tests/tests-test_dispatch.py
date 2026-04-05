tests/test_dispatch.py

"""
Tests for OllamaDispatcher — mocks the HTTP call so no Ollama needed.
"""
import sys
import os
import time
import threading
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dispatch.ollama import OllamaDispatcher, Priority


def _make_dispatcher(model="test-model"):
    return OllamaDispatcher(
        base_url="http://localhost:11434",
        model=model,
        num_ctx=512,
    )


def _mock_ollama_response(text="4"):
    """Returns a mock that makes urlopen return a fake Ollama response."""
    import json
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"response": text}).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    return mock_response


# ── Priority ordering ─────────────────────────────────────────────────

def test_priority_constants_ordered():
    assert Priority.COLLAPSE   < Priority.CACHE_LOW
    assert Priority.CACHE_LOW  < Priority.NORMAL
    assert Priority.NORMAL     < Priority.PREFETCH
    assert Priority.PREFETCH   < Priority.BACKGROUND


# ── Submit and callback ───────────────────────────────────────────────

def test_submit_calls_callback_with_result():
    d = _make_dispatcher()
    results = []
    event   = threading.Event()

    with patch("urllib.request.urlopen", return_value=_mock_ollama_response("42")):
        d.submit(
            student_id="alice",
            prompt="What is 6 x 7?",
            callback=lambda r: (results.append(r), event.set()),
            priority=Priority.NORMAL,
            timeout=5.0,
        )
        event.wait(timeout=10)

    assert results == ["42"]


def test_submit_returns_request_id():
    d   = _make_dispatcher()
    rid = d.submit("alice", "prompt", lambda r: None)
    assert isinstance(rid, str)
    assert len(rid) > 0


def test_timeout_calls_callback_with_none():
    d = _make_dispatcher()
    results = []
    event   = threading.Event()

    def slow_urlopen(*args, **kwargs):
        time.sleep(10)
        return _mock_ollama_response()

    with patch("urllib.request.urlopen", side_effect=slow_urlopen):
        d.submit(
            student_id="bob",
            prompt="slow prompt",
            callback=lambda r: (results.append(r), event.set()),
            priority=Priority.NORMAL,
            timeout=0.01,   # expire immediately
        )
        event.wait(timeout=5)

    assert results == [None]


def test_drop_low_priority_when_full():
    d = _make_dispatcher()
    # Fill the queue above MAX_DEPTH with high-priority items (won't be dropped)
    dropped = []

    # Submit one PREFETCH request when queue is at capacity
    # by blocking the worker temporarily
    block = threading.Event()

    def blocking_urlopen(*args, **kwargs):
        block.wait(timeout=2)
        return _mock_ollama_response()

    with patch("urllib.request.urlopen", side_effect=blocking_urlopen):
        # Fill queue
        for i in range(d.MAX_DEPTH):
            d.submit(f"student_{i}", "prompt", lambda r: None, Priority.NORMAL)

        # This PREFETCH should be dropped
        d.submit(
            "overflow_student", "prompt",
            lambda r: dropped.append(r),
            Priority.PREFETCH,
        )
        block.set()

    # dropped list gets None synchronously when dropped
    time.sleep(0.1)
    assert dropped == [None]


def test_cancel_marks_request_cancelled():
    d     = _make_dispatcher()
    block = threading.Event()
    results = []

    def blocking_urlopen(*args, **kwargs):
        block.wait(timeout=2)
        return _mock_ollama_response("cancelled_result")

    with patch("urllib.request.urlopen", side_effect=blocking_urlopen):
        d.submit("carol", "prompt",
                 lambda r: results.append(r),
                 Priority.NORMAL, timeout=30.0)
        d.cancel("carol")
        block.set()
        time.sleep(0.2)

    # Cancelled request should not call callback
    assert results == []


def test_metrics_keys():
    d = _make_dispatcher()
    m = d.metrics
    for key in ("queue_depth", "dispatched", "dropped", "timeouts", "pending_students"):
        assert key in m


def test_dedup_cancels_old_request_for_same_student():
    d     = _make_dispatcher()
    block = threading.Event()
    calls = []

    def blocking_urlopen(*args, **kwargs):
        block.wait(timeout=2)
        return _mock_ollama_response("result")

    with patch("urllib.request.urlopen", side_effect=blocking_urlopen):
        rid1 = d.submit("dave", "first",  lambda r: calls.append(("first", r)))
        rid2 = d.submit("dave", "second", lambda r: calls.append(("second", r)))
        assert rid1 != rid2
        block.set()
        time.sleep(0.3)

    # Only second request should fire (first was cancelled)
    tags = [c[0] for c in calls]
    assert "first" not in tags
    assert "second" in tags