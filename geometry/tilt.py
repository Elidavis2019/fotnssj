import math
from typing import Dict


def calculate_syncletic_tilt(
    is_correct: bool,
    streak: int,
    depth: int,
    current_position: Dict,
) -> Dict:
    """
    Calculate tilt vector deltas based on answer correctness,
    streak length, and topic depth.
    """
    direction = 1.0 if is_correct else -1.0
    streak_factor = min(streak / 5.0, 1.0)
    depth_factor = 1.0 + (depth * 0.1)

    alpha_delta = direction * 0.3 * depth_factor
    cave_delta = direction * 0.2 * streak_factor
    l_net_delta = direction * 0.1 * (1.0 + streak_factor)

    return {
        "alpha_delta": round(alpha_delta, 6),
        "cave_delta": round(cave_delta, 6),
        "L_net_delta": round(l_net_delta, 6),
    }
