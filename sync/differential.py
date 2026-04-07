import base64
import hashlib
import json
import threading
import time
import urllib.request
import zlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class StateDiff:
    student_id:      str
    from_hash:       str
    to_hash:         str
    position_delta:  Dict
    tilt_applied:    Dict
    new_crystals:    List[Dict]
    streak_delta:    Dict
    event_type:      str
    timestamp:       float = field(default_factory=time.time)

    def to_wire(self) -> str:
        payload = json.dumps({
            "sid": self.student_id, "fh": self.from_hash, "th": self.to_hash,
            "pd": self.position_delta, "tv": self.tilt_applied,
            "nc": self.new_crystals, "sd": self.streak_delta,
            "ev": self.event_type, "ts": self.timestamp,
        }).encode()
        return base64.b64encode(zlib.compress(payload, level=6)).decode()

    @staticmethod
    def from_wire(wire: str) -> "StateDiff":
        d = json.loads(zlib.decompress(base64.b64decode(wire)))
        return StateDiff(
            student_id=d["sid"], from_hash=d["fh"], to_hash=d["th"],
            position_delta=d["pd"], tilt_applied=d["tv"],
            new_crystals=d["nc"], streak_delta=d["sd"],
            event_type=d["ev"], timestamp=d["ts"],
        )


def _state_hash(pos: Dict, streaks: Dict, crystal_ids: list) -> str:
    content = json.dumps(
        {"pos": pos, "str": dict(sorted(streaks.items())),
         "cids": sorted(crystal_ids)}, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


class DifferentialRenderer:
    def __init__(self, endpoint: Optional[str] = None, batch_size: int = 10):
        self._endpoint   = endpoint
        self._batch_size = batch_size
        self._queue:       List[StateDiff] = []
        self._hashes:      Dict[str, str]  = {}
        self._positions:   Dict[str, Dict] = {}
        self._streaks:     Dict[str, Dict] = {}
        self._crystal_ids: Dict[str, set]  = {}
        self._lock = threading.Lock()
        threading.Thread(target=self._flush_loop, daemon=True).start()

    def record(self, student_id: str, position: Dict, tilt: Dict,
               streaks: Dict, crystal_ids: list, crystals: List[Dict],
               event_type: str):
        to_hash   = _state_hash(position, streaks, crystal_ids)
        prev_hash = self._hashes.get(student_id, "")
        if prev_hash == to_hash:
            return

        prev_pos  = self._positions.get(student_id,
                    {"alpha": 1.0, "cave_depth": 0.5, "L_net": 0.5})
        prev_str  = self._streaks.get(student_id, {})
        prev_cids = self._crystal_ids.get(student_id, set())

        pos_delta    = {k: round(position.get(k, 0) - prev_pos.get(k, 0), 6)
                        for k in position}
        streak_delta = {t: v for t, v in streaks.items() if prev_str.get(t) != v}
        new_cids     = set(crystal_ids) - prev_cids
        new_crystals = [c for c in crystals if c.get("id") in new_cids]

        diff = StateDiff(
            student_id=student_id, from_hash=prev_hash, to_hash=to_hash,
            position_delta=pos_delta, tilt_applied=tilt,
            new_crystals=new_crystals, streak_delta=streak_delta,
            event_type=event_type,
        )

        with self._lock:
            self._queue.append(diff)
            self._hashes[student_id]      = to_hash
            self._positions[student_id]   = dict(position)
            self._streaks[student_id]     = dict(streaks)
            self._crystal_ids[student_id] = set(crystal_ids)

        if len(self._queue) >= self._batch_size:
            threading.Thread(target=self._flush, daemon=True).start()

    def _flush_loop(self):
        while True:
            time.sleep(30)
            self._flush()

    def _flush(self):
        with self._lock:
            if not self._queue:
                return
            batch, self._queue = self._queue[:], []
        if not self._endpoint:
            return
        try:
            payload = json.dumps([d.to_wire() for d in batch]).encode()
            req = urllib.request.Request(
                self._endpoint, data=payload,
                headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            print(f"[SYNC] Flush failed: {e}")
            with self._lock:
                self._queue = batch + self._queue