import math
import time
import json
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional

from geometry.bounds import ManifoldBounds, DEFAULT_BOUNDS


class MalformationType(Enum):
    NAN_COORDINATE        = "Coordinate is NaN"
    INF_COORDINATE        = "Coordinate is infinite"
    BELOW_FLOOR           = "Coordinate below minimum bound"
    ABOVE_CEILING         = "Coordinate above maximum bound"
    ZERO_MAGNITUDE_TILT   = "TiltVector has zero magnitude"
    IMPLAUSIBLE_DELTA     = "TiltVector delta exceeds single-step limit"
    POSITION_TELEPORT     = "Position jumped beyond max inter-step distance"
    CORRUPT_RESTORE       = "Deserialized position failed round-trip check"
    TILT_NAN              = "TiltVector component is NaN"
    TILT_INF              = "TiltVector component is infinite"
    SIGN_INCONSISTENCY    = "cave_delta sign inconsistent with sinc direction"


class Severity(Enum):
    WARNING  = "warning"
    ERROR    = "error"
    CRITICAL = "critical"


SEVERITY_MAP = {
    MalformationType.NAN_COORDINATE:      Severity.CRITICAL,
    MalformationType.INF_COORDINATE:      Severity.CRITICAL,
    MalformationType.TILT_NAN:            Severity.CRITICAL,
    MalformationType.TILT_INF:            Severity.CRITICAL,
    MalformationType.CORRUPT_RESTORE:     Severity.CRITICAL,
    MalformationType.BELOW_FLOOR:         Severity.ERROR,
    MalformationType.ABOVE_CEILING:       Severity.ERROR,
    MalformationType.IMPLAUSIBLE_DELTA:   Severity.ERROR,
    MalformationType.POSITION_TELEPORT:   Severity.ERROR,
    MalformationType.ZERO_MAGNITUDE_TILT: Severity.WARNING,
    MalformationType.SIGN_INCONSISTENCY:  Severity.WARNING,
}


@dataclass
class MalformationReport:
    report_id:         str
    student_id:        str
    malformation_type: MalformationType
    severity:          Severity
    detected_at:       float
    detail:            str
    position_snapshot: Optional[Dict] = None
    tilt_snapshot:     Optional[Dict] = None
    previous_position: Optional[Dict] = None
    resolved:          bool = False
    resolution:        str  = ""
    acknowledged_by:   Optional[str]   = None
    acknowledged_at:   Optional[float] = None

    def to_dict(self) -> Dict:
        return {
            "report_id":       self.report_id,
            "student_id":      self.student_id,
            "type":            self.malformation_type.name,
            "type_label":      self.malformation_type.value,
            "severity":        self.severity.value,
            "detected_at":     self.detected_at,
            "detail":          self.detail,
            "position":        self.position_snapshot,
            "tilt":            self.tilt_snapshot,
            "previous":        self.previous_position,
            "resolved":        self.resolved,
            "resolution":      self.resolution,
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": self.acknowledged_at,
        }


def _make_id() -> str:
    return f"GEO-{uuid.uuid4().hex[:10].upper()}"


def validate_position_dict(
    student_id: str,
    pos: Dict,
    previous: Optional[Dict],
    bounds: ManifoldBounds,
    context: str,
    last_good: Optional[Dict],
) -> List[MalformationReport]:
    reports = []
    coord_bounds = bounds.coordinate_bounds()

    for coord, value in pos.items():
        lo, hi = coord_bounds.get(coord, (bounds.alpha_min, bounds.alpha_max))

        if isinstance(value, float) and math.isnan(value):
            reports.append(MalformationReport(
                report_id=_make_id(), student_id=student_id,
                malformation_type=MalformationType.NAN_COORDINATE,
                severity=Severity.CRITICAL,
                detected_at=time.time(),
                detail=f"{coord}=NaN [{context}]",
                position_snapshot=pos, previous_position=last_good,
            ))
        elif isinstance(value, float) and math.isinf(value):
            reports.append(MalformationReport(
                report_id=_make_id(), student_id=student_id,
                malformation_type=MalformationType.INF_COORDINATE,
                severity=Severity.CRITICAL,
                detected_at=time.time(),
                detail=f"{coord}=Inf [{context}]",
                position_snapshot=pos, previous_position=last_good,
            ))
        else:
            if value < lo:
                reports.append(MalformationReport(
                    report_id=_make_id(), student_id=student_id,
                    malformation_type=MalformationType.BELOW_FLOOR,
                    severity=Severity.ERROR,
                    detected_at=time.time(),
                    detail=f"{coord}={value:.6f} < floor {lo} [{context}]",
                    position_snapshot=pos, previous_position=last_good,
                ))
            if value > hi:
                reports.append(MalformationReport(
                    report_id=_make_id(), student_id=student_id,
                    malformation_type=MalformationType.ABOVE_CEILING,
                    severity=Severity.ERROR,
                    detected_at=time.time(),
                    detail=f"{coord}={value:.6f} > ceiling {hi} [{context}]",
                    position_snapshot=pos, previous_position=last_good,
                ))

    if previous and not any(r.severity == Severity.CRITICAL for r in reports):
        try:
            dist = math.sqrt(sum(
                (pos.get(k, 0) - previous.get(k, 0)) ** 2
                for k in ("alpha", "cave_depth", "L_net")
            ))
            if dist > bounds.max_teleport:
                reports.append(MalformationReport(
                    report_id=_make_id(), student_id=student_id,
                    malformation_type=MalformationType.POSITION_TELEPORT,
                    severity=Severity.ERROR,
                    detected_at=time.time(),
                    detail=f"Euclidean jump {dist:.4f} > max {bounds.max_teleport} [{context}]",
                    position_snapshot=pos, previous_position=previous,
                ))
        except Exception:
            pass

    return reports


def validate_tilt_dict(
    student_id: str,
    tilt: Dict,
    bounds: ManifoldBounds,
    context: str,
) -> List[MalformationReport]:
    reports = []

    for comp, value in tilt.items():
        if isinstance(value, float) and math.isnan(value):
            reports.append(MalformationReport(
                report_id=_make_id(), student_id=student_id,
                malformation_type=MalformationType.TILT_NAN,
                severity=Severity.CRITICAL,
                detected_at=time.time(),
                detail=f"TiltVector.{comp}=NaN [{context}]",
                tilt_snapshot=tilt,
            ))
        elif isinstance(value, float) and math.isinf(value):
            reports.append(MalformationReport(
                report_id=_make_id(), student_id=student_id,
                malformation_type=MalformationType.TILT_INF,
                severity=Severity.CRITICAL,
                detected_at=time.time(),
                detail=f"TiltVector.{comp}=Inf [{context}]",
                tilt_snapshot=tilt,
            ))
        elif abs(value) > bounds.max_delta:
            reports.append(MalformationReport(
                report_id=_make_id(), student_id=student_id,
                malformation_type=MalformationType.IMPLAUSIBLE_DELTA,
                severity=Severity.ERROR,
                detected_at=time.time(),
                detail=f"TiltVector.{comp}={value:.4f} > max_delta {bounds.max_delta} [{context}]",
                tilt_snapshot=tilt,
            ))

    if not any(r.severity == Severity.CRITICAL for r in reports):
        try:
            mag = math.sqrt(sum(v**2 for v in tilt.values()))
            if mag < bounds.min_tilt_mag:
                reports.append(MalformationReport(
                    report_id=_make_id(), student_id=student_id,
                    malformation_type=MalformationType.ZERO_MAGNITUDE_TILT,
                    severity=Severity.WARNING,
                    detected_at=time.time(),
                    detail=f"Tilt magnitude={mag:.2e} ≈ zero [{context}]",
                    tilt_snapshot=tilt,
                ))
            elif mag > bounds.max_tilt_mag:
                reports.append(MalformationReport(
                    report_id=_make_id(), student_id=student_id,
                    malformation_type=MalformationType.IMPLAUSIBLE_DELTA,
                    severity=Severity.ERROR,
                    detected_at=time.time(),
                    detail=f"Tilt magnitude={mag:.4f} > max {bounds.max_tilt_mag} [{context}]",
                    tilt_snapshot=tilt,
                ))
        except Exception:
            pass

    return reports


def has_blocking(reports: List[MalformationReport]) -> bool:
    return any(r.severity in (Severity.ERROR, Severity.CRITICAL) for r in reports)


class GeometryManifest:
    def __init__(
        self,
        bounds: ManifoldBounds = None,
        alert_callback: Optional[Callable[[MalformationReport], None]] = None,
        persist_path: str = "/data/geometry/reports.json",
    ):
        self._bounds    = bounds or DEFAULT_BOUNDS
        self._alert_cb  = alert_callback
        self._path      = Path(persist_path)
        self._reports:  List[MalformationReport] = []
        self._last_good: Dict[str, Dict] = {}
        self._lock      = threading.Lock()
        self._load()

    def check_position(
        self, student_id: str, pos_dict: Dict,
        previous_dict: Optional[Dict] = None,
        context: str = "",
    ) -> tuple:
        reports = validate_position_dict(
            student_id, pos_dict, previous_dict,
            self._bounds, context,
            self._last_good.get(student_id),
        )
        self._ingest(reports)
        if not has_blocking(reports):
            self._last_good[student_id] = pos_dict
            return True, pos_dict, reports
        return False, self._safe_position(student_id), reports

    def check_tilt(
        self, student_id: str, tilt_dict: Dict, context: str = ""
    ) -> tuple:
        reports = validate_tilt_dict(
            student_id, tilt_dict, self._bounds, context
        )
        self._ingest(reports)
        if not has_blocking(reports):
            return True, tilt_dict, reports
        return False, {"alpha_delta": 0.0, "cave_delta": 0.0, "L_net_delta": 0.0}, reports

    def check_crystal(
        self, student_id: str, pos_dict: Dict, tilt_dict: Dict
    ) -> tuple:
        pos_ok,  _, pr = self.check_position(student_id, pos_dict, context="crystal:pos")
        tilt_ok, _, tr = self.check_tilt(student_id, tilt_dict, context="crystal:tilt")
        return (pos_ok and tilt_ok), (pr + tr)

    def acknowledge(self, report_id: str, admin: str) -> bool:
        with self._lock:
            for r in self._reports:
                if r.report_id == report_id and not r.resolved:
                    r.resolved        = True
                    r.acknowledged_by = admin
                    r.acknowledged_at = time.time()
                    r.resolution      = f"Acknowledged by {admin}"
                    self._save()
                    return True
        return False

    def unresolved(self, severity=None) -> List[Dict]:
        with self._lock:
            out = [r for r in self._reports if not r.resolved]
            if severity:
                out = [r for r in out if r.severity == severity]
            return [r.to_dict() for r in sorted(out, key=lambda x: x.detected_at, reverse=True)]

    def summary(self) -> Dict:
        with self._lock:
            u = [r for r in self._reports if not r.resolved]
            return {
                "unresolved":          len(u),
                "critical_unresolved": sum(1 for r in u if r.severity == Severity.CRITICAL),
                "error_unresolved":    sum(1 for r in u if r.severity == Severity.ERROR),
                "warning_unresolved":  sum(1 for r in u if r.severity == Severity.WARNING),
                "affected_students":   list({r.student_id for r in u}),
            }

    def all_reports(self) -> List[Dict]:
        with self._lock:
            return [r.to_dict() for r in self._reports]

    def _safe_position(self, student_id: str) -> Dict:
        prev = self._last_good.get(student_id)
        if prev:
            return prev
        return {"alpha": 1.0, "cave_depth": 0.5, "L_net": 0.5}

    def _ingest(self, reports: List[MalformationReport]):
        with self._lock:
            self._reports.extend(reports)
            if len(self._reports) > 1000:
                self._reports = self._reports[-1000:]
        for r in reports:
            sev = r.severity.value.upper()
            print(f"[GEOMETRY][{sev}] {r.student_id}: {r.malformation_type.name} — {r.detail}")
            if r.severity in (Severity.ERROR, Severity.CRITICAL) and self._alert_cb:
                threading.Thread(target=self._alert_cb, args=(r,), daemon=True).start()
        if reports:
            self._save()

    def _save(self):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data = [r.to_dict() for r in self._reports[-500:]]
            self._path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            print(f"[GEOMETRY] Persist failed: {e}")

    def _load(self):
        if not self._path.exists():
            return
        try:
            for d in json.loads(self._path.read_text()):
                r = MalformationReport(
                    report_id=d["report_id"],
                    student_id=d["student_id"],
                    malformation_type=MalformationType[d["type"]],
                    severity=Severity(d["severity"]),
                    detected_at=d["detected_at"],
                    detail=d["detail"],
                    position_snapshot=d.get("position"),
                    tilt_snapshot=d.get("tilt"),
                    previous_position=d.get("previous"),
                    resolved=d.get("resolved", False),
                    resolution=d.get("resolution", ""),
                    acknowledged_by=d.get("acknowledged_by"),
                    acknowledged_at=d.get("acknowledged_at"),
                )
                self._reports.append(r)
        except Exception as e:
            print(f"[GEOMETRY] Load failed: {e}")