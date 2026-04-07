import threading
from typing import Dict, List, Optional

from branches.agent import StudentAgent


class BranchSystem:
    """
    Manages per-student agents for contextual question generation.
    """

    def __init__(self):
        self._agents: Dict[str, StudentAgent] = {}
        self._lock = threading.Lock()

    def fork(self, student_id: str, topic: str = "", domain: str = "") -> StudentAgent:
        with self._lock:
            existing = self._agents.get(student_id)
            if existing:
                existing.is_dormant = False
                if topic:
                    existing.current_topic = topic
                if domain:
                    existing.current_domain = domain
                return existing
            agent = StudentAgent(student_id, topic, domain)
            self._agents[student_id] = agent
            return agent

    def switch(self, student_id: str, topic: str, domain: str):
        agent = self.get(student_id)
        if agent:
            agent.current_topic = topic
            agent.current_domain = domain
            agent.add_step(f"Topic switch to {topic}", f"Switched domain={domain}")

    def commit(self, student_id: str, topic: str, question: str,
               answer: str, bridge: str, streak: int):
        agent = self.get(student_id)
        if agent:
            agent.add_step(
                f"Crystallized {topic}: {question} = {answer}",
                f"Crystallized streak={streak}, bridge={bridge}",
            )

    def abandon(self, student_id: str):
        agent = self.get(student_id)
        if agent:
            agent.is_dormant = True

    def get_agent(self, student_id: str) -> Optional[StudentAgent]:
        return self._agents.get(student_id)

    def get(self, student_id: str) -> Optional[StudentAgent]:
        return self.get_agent(student_id)

    def build_prompt(self, student_id: str, topic: str, domain: str,
                     principle: str) -> Optional[str]:
        agent = self.get(student_id)
        if not agent:
            return None
        return (
            f"You are tutoring a student. Learning history:\n\n"
            f"{agent.get_context()}\n\n"
            f"Generate ONE question for topic '{topic.replace('_', ' ')}' "
            f"in domain '{domain}' (principle: {principle}). "
            f"Match difficulty to their recent trajectory. "
            f"Respond ONLY with JSON: "
            f'{{\"question\": ..., \"correct_answer\": ..., '
            f'\"explanation\": ..., \"bridge\": ...}}'
        )

    def all_snapshots(self) -> List[Dict]:
        with self._lock:
            return [agent.snapshot() for agent in self._agents.values()]
