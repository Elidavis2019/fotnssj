from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass
class ManifoldBounds:
    alpha_min: float = 0.01
    alpha_max: float = 10.0
    cave_min: float = 0.01
    cave_max: float = 10.0
    l_net_min: float = 0.01
    l_net_max: float = 10.0
    max_delta: float = 2.0
    max_teleport: float = 5.0
    min_tilt_mag: float = 1e-6
    max_tilt_mag: float = 5.0

    def coordinate_bounds(self) -> Dict[str, Tuple[float, float]]:
        return {
            "alpha": (self.alpha_min, self.alpha_max),
            "cave_depth": (self.cave_min, self.cave_max),
            "L_net": (self.l_net_min, self.l_net_max),
        }


DEFAULT_BOUNDS = ManifoldBounds()
