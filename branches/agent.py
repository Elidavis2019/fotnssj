import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Block:
    content: str
    created_at: float = field(default_factory=time.time)


class StudentAgent:
    """
    Per-student context agent for contextual question generation.
    Tracks steps, navigation events, and topic switches.
    """
    MAX_HISTORY = 20

    def __init__(self, student_id: str, topic: str = "", domain: str = ""):
        self.student_id = student_id
        self.current_topic = topic
        self.current_domain = domain
        self.frontier: Optional[Block] = None
        self.history: List[Block] = []
        self.trajectory: List[Dict] = []
        self.is_dormant = False
        self._step_count = 0

    def add_step(self, thought: str, result: str):
        block = Block(content=f"THOUGHT: {thought}\nRESULT: {result}")
        self.frontier = block
        self.history.append(block)
        self._step_count += 1
        if len(self.history) > self.MAX_HISTORY:
            self.history = self.history[-self.MAX_HISTORY:]

    def record_nav(self, position: Dict, tilt: Dict, event: str, topic: str):
        self.trajectory.append({
            "position": position,
            "tilt": tilt,
            "event": event,
            "topic": topic,
            "ts": time.time(),
        })

    def record(self, question: str, answer: str, correct: bool):
        event = "correct" if correct else "incorrect"
        self.add_step(f"Q: {question}", f"A: {answer} ({event})")

    def get_context(self) -> str:
        lines = [f"OBJECTIVE: Help student {self.student_id} master {self.current_topic}"]
        if self.history:
            lines.append("HISTORY:")
            for b in self.history[-10:]:
                lines.append(f"  {b.content}")
        if self.frontier:
            lines.append(f"NOW: {self.frontier.content}")
        return "\n".join(lines)

    def snapshot(self) -> Dict:
        return {
            "student_id": self.student_id,
            "topic": self.current_topic,
            "domain": self.current_domain,
            "step": self._step_count,
            "trajectory_len": len(self.trajectory),
            "is_dormant": self.is_dormant,
        }
