tests/test_branches.py

import sys
import os
import time
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from branches.agent  import StudentAgent, Block
from branches.system import BranchSystem


# ── StudentAgent ──────────────────────────────────────────────────────

def test_agent_init():
    a = StudentAgent("alice", "addition_basic", "arithmetic")
    assert a.student_id     == "alice"
    assert a.current_topic  == "addition_basic"
    assert a.current_domain == "arithmetic"
    assert a.frontier is None
    assert a.history  == []
    assert not a.is_dormant


def test_agent_add_step_creates_frontier():
    a = StudentAgent("alice", "addition_basic", "arithmetic")
    a.add_step("Tried 2+2", "Got 4")
    assert a.frontier is not None
    assert "THOUGHT" in a.frontier.content
    assert "RESULT" in a.frontier.content


def test_agent_history_rolls():
    a = StudentAgent("alice", "addition_basic", "arithmetic")
    for i in range(StudentAgent.MAX_HISTORY + 3):
        a.add_step(f"step {i}", f"result {i}")
    assert len(a.history) <= StudentAgent.MAX_HISTORY


def test_agent_get_context_has_all_regions():
    a = StudentAgent("alice", "addition_basic", "arithmetic")
    a.add_step("step 1", "result 1")
    ctx = a.get_context()
    assert "OBJECTIVE" in ctx
    assert "NOW"       in ctx


def test_agent_record_nav():
    a = StudentAgent("alice", "addition_basic", "arithmetic")
    pos  = {"alpha": 1.0, "cave_depth": 0.5, "L_net": 0.5}
    tilt = {"alpha_delta": 0.1, "cave_delta": 0.05, "L_net_delta": 0.2}
    a.record_nav(pos, tilt, "correct", "addition_basic")
    assert len(a.trajectory) == 1
    assert a.trajectory[0]["event"] == "correct"


def test_agent_snapshot_keys():
    a = StudentAgent("alice", "addition_basic", "arithmetic")
    s = a.snapshot()
    for key in ("student_id", "topic", "domain", "step",
                "trajectory_len", "is_dormant"):
        assert key in s


# ── BranchSystem ──────────────────────────────────────────────────────

def test_branch_fork_creates_agent():
    bs = BranchSystem()
    agent = bs.fork("bob", "addition_basic", "arithmetic")
    assert agent.student_id == "bob"
    assert bs.get("bob") is agent


def test_branch_fork_reactivates_dormant():
    bs = BranchSystem()
    bs.fork("carol", "addition_basic", "arithmetic")
    bs.abandon("carol")
    assert bs.get("carol").is_dormant
    bs.fork("carol")
    assert not bs.get("carol").is_dormant


def test_branch_switch_updates_topic():
    bs = BranchSystem()
    bs.fork("dave", "addition_basic", "arithmetic")
    bs.switch("dave", "doubling", "arithmetic")
    assert bs.get("dave").current_topic  == "doubling"
    assert bs.get("dave").current_domain == "arithmetic"


def test_branch_switch_records_in_history():
    bs = BranchSystem()
    bs.fork("eve", "addition_basic", "arithmetic")
    bs.switch("eve", "doubling", "arithmetic")
    agent = bs.get("eve")
    assert agent.frontier is not None
    assert "switch" in agent.frontier.content.lower()


def test_branch_commit_adds_step():
    bs = BranchSystem()
    bs.fork("frank", "addition_basic", "arithmetic")
    bs.commit("frank", "addition_basic", "2+2?", "4", "what next?", 1)
    agent = bs.get("frank")
    assert agent.frontier is not None
    assert "Crystallized" in agent.frontier.content


def test_branch_abandon_marks_dormant():
    bs = BranchSystem()
    bs.fork("grace", "addition_basic", "arithmetic")
    bs.abandon("grace")
    assert bs.get("grace").is_dormant


def test_branch_get_returns_none_for_unknown():
    bs = BranchSystem()
    assert bs.get("nobody") is None


def test_branch_build_prompt_without_agent_returns_none():
    bs = BranchSystem()
    result = bs.build_prompt("ghost", "addition_basic", "arithmetic", "principle")
    assert result is None


def test_branch_build_prompt_with_agent_returns_string():
    bs = BranchSystem()
    bs.fork("henry", "addition_basic", "arithmetic")
    prompt = bs.build_prompt("henry", "addition_basic", "arithmetic",
                              "adding a number to itself doubles it")
    assert isinstance(prompt, str)
    assert "addition" in prompt.lower()


def test_branch_all_snapshots_returns_list():
    bs = BranchSystem()
    bs.fork("ida",  "addition_basic", "arithmetic")
    bs.fork("jack", "phonics_basic",  "reading")
    snaps = bs.all_snapshots()
    assert len(snaps) == 2