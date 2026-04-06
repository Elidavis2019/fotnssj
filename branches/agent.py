from typing import Dict, List


class StudentAgent:
    """
    Lightweight per-student context agent.
    Tracks recent answer history to provide contextual question generation.
    """
    MAX_HISTORY = 20

    def __init__(self, student_id: str, topic: str, domain: str):
        self.student_id = student_id
        self.topic = topic
        self.domain = domain
        self._history: List[Dict] = []

    def record(self, question: str, answer: str, correct: bool):
        self._history.append({
            "question": question,
            "answer": answer,
            "correct": correct,
        })
        if len(self._history) > self.MAX_HISTORY:
            self._history = self._history[-self.MAX_HISTORY:]

    def get_context(self) -> str:
        if not self._history:
            return "No previous answers recorded."
        lines = []
        for h in self._history[-10:]:
            mark = "correct" if h["correct"] else "wrong"
            lines.append(f"Q: {h['question']} → {h['answer']} ({mark})")
        return "\n".join(lines)
