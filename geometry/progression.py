from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class ProgressionDecision:
    action: str           # "stay", "advance", "review"
    from_topic: str
    to_topic: Optional[str]
    reason: str


class ProgressionEngine:
    """
    Decides when a student should advance to the next topic
    based on crystallization count and streak data.
    """
    ADVANCE_THRESHOLD = 3   # crystals needed to advance
    REVIEW_THRESHOLD = 5    # wrong answers before suggesting review

    def __init__(self, domain_model=None):
        self._domain = domain_model

    def evaluate(
        self,
        student_id: str,
        current_topic: str,
        domain: str,
        crystal_count: int,
        recent_accuracy: float,
        progression: Optional[List[str]] = None,
    ) -> ProgressionDecision:
        if progression is None:
            progression = []

        if crystal_count >= self.ADVANCE_THRESHOLD:
            try:
                idx = progression.index(current_topic)
                if idx + 1 < len(progression):
                    next_topic = progression[idx + 1]
                    return ProgressionDecision(
                        action="advance",
                        from_topic=current_topic,
                        to_topic=next_topic,
                        reason=f"Crystallized {crystal_count} times",
                    )
            except ValueError:
                pass

        if recent_accuracy < 0.3:
            try:
                idx = progression.index(current_topic)
                if idx > 0:
                    prev_topic = progression[idx - 1]
                    return ProgressionDecision(
                        action="review",
                        from_topic=current_topic,
                        to_topic=prev_topic,
                        reason=f"Accuracy {recent_accuracy:.0%} below threshold",
                    )
            except ValueError:
                pass

        return ProgressionDecision(
            action="stay",
            from_topic=current_topic,
            to_topic=None,
            reason="Continuing current topic",
        )
