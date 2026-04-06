import threading
from typing import Dict, Optional

from branches.agent import StudentAgent


class BranchSystem:
    """
    Manages per-student agents for contextual question generation.
    """

    def __init__(self):
        self._agents: Dict[str, StudentAgent] = {}
        self._lock = threading.Lock()

    def fork(self, student_id: str, topic: str, domain: str) -> StudentAgent:
        with self._lock:
            if student_id not in self._agents:
                self._agents[student_id] = StudentAgent(student_id, topic, domain)
            return self._agents[student_id]

    def get_agent(self, student_id: str) -> Optional[StudentAgent]:
        return self._agents.get(student_id)

    def get(self, student_id: str) -> Optional[StudentAgent]:
        return self.get_agent(student_id)
