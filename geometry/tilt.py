import math
from typing import Dict


def _bessel_j0(x: float) -> float:
    """Approximation of J0 Bessel function of the first kind."""
    if abs(x) < 1e-12:
        return 1.0
    ax = abs(x)
    if ax < 8.0:
        y = x * x
        ans1 = (57568490574.0 + y * (-13362590354.0 + y * (651619640.7
                + y * (-11214424.18 + y * (77392.33017 + y * (-184.9052456))))))
        ans2 = (57568490411.0 + y * (1029532985.0 + y * (9494680.718
                + y * (59272.64853 + y * (267.8532712 + y * 1.0)))))
        return ans1 / ans2
    else:
        z = 8.0 / ax
        y = z * z
        xx = ax - 0.785398164
        p0 = (1.0 + y * (-0.1098628627e-2 + y * (0.2734510407e-4
              + y * (-0.2073370639e-5 + y * 0.2093887211e-6))))
        q0 = (-0.1562499995e-1 + y * (0.1430488765e-3
              + y * (-0.6911147651e-5 + y * (0.7621095161e-6
              - y * 0.934935152e-7))))
        return math.sqrt(0.636619772 / ax) * (p0 * math.cos(xx) - z * q0 * math.sin(xx))


def calculate_syncletic_tilt(
    response_time: float,
    cave_depth: float,
    streak: int,
    is_correct: bool,
) -> Dict:
    """
    Calculate tilt vector deltas from answer event.

    Parameters
    ----------
    response_time : float  – seconds the student took to answer
    cave_depth    : float  – current cave_depth coordinate
    streak        : int    – consecutive correct answers on this topic
    is_correct    : bool   – whether the answer was correct
    """
    direction = 1.0 if is_correct else -1.0

    # Alpha: direction * scaled response time (clamped)
    clamped_rt = max(0.1, min(response_time, 60.0))
    alpha_delta = round(direction * 0.3 * (1.0 / (1.0 + math.log(clamped_rt))), 4)

    # Cave: sinc-like modulation via Bessel J0
    sinc_val = _bessel_j0(cave_depth * math.pi)
    cave_delta = round(math.copysign(abs(sinc_val) * 0.2, direction * sinc_val), 4)

    # L_net: tanh saturation on streak; -0.5 if incorrect
    if is_correct:
        l_net_delta = round(math.tanh(streak * 0.2), 4)
    else:
        l_net_delta = -0.5

    return {
        "alpha_delta": alpha_delta,
        "cave_delta": cave_delta,
        "L_net_delta": l_net_delta,
    }
