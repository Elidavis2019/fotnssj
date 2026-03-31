scripts/migrate.py

#!/usr/bin/env python3
# ════════════════════════════════════════════════════════════════════════
# Data migration utility
# Handles version upgrades to state files and crystallization format.
#
# Usage:
#   python scripts/migrate.py status
#   python scripts/migrate.py run
#   python scripts/migrate.py run --dry-run
# ════════════════════════════════════════════════════════════════════════
import sys
import os
import json
import time
import shutil
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STATE_ROOT    = Path("/data/state")
SESSION_ROOT  = Path("/data/sessions")
BACKUP_ROOT   = Path("/data/backups/pre-migration")
SCHEMA_VERSION = 3


def _current_version(state_file: Path) -> int:
    try:
        d = json.loads(state_file.read_text())
        return d.get("schema_version", 1)
    except Exception:
        return 0


def _backup_file(path: Path, dry_run: bool) -> Path:
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    dest = BACKUP_ROOT / path.name
    if not dry_run:
        shutil.copy2(path, dest)
    return dest


# ── Migration functions — one per version transition ─────────────────

def migrate_v1_to_v2(data: dict) -> dict:
    """
    v1 → v2: Add schema_version field.
    Add content_hash to crystallizations that lack it.
    """
    import hashlib
    crystals = data.get("crystallizations", [])
    for c in crystals:
        if not c.get("content_hash"):
            content = f"{c.get('question','')}|{c.get('correct_answer','')}|{c.get('explanation','')}"
            c["content_hash"] = hashlib.sha256(content.encode()).hexdigest()[:16]
        if "edit_history" not in c:
            c["edit_history"] = []
    data["schema_version"] = 2
    return data


def migrate_v2_to_v3(data: dict) -> dict:
    """
    v2 → v3: Add position bounds clamping.
    Ensure all positions have valid coordinates.
    Ensure streak tracker has crystallize_after field.
    """
    pos = data.get("position", {})
    for key, default, lo, hi in [
        ("alpha",      1.0, 0.01, 10.0),
        ("cave_depth", 0.5, 0.01, 10.0),
        ("L_net",      0.5, 0.01, 10.0),
    ]:
        v = pos.get(key, default)
        if not isinstance(v, (int, float)) or v != v:  # NaN check
            v = default
        pos[key] = max(lo, min(hi, float(v)))
    data["position"] = pos

    streaks = data.get("streaks", {})
    if "crystallize_after" not in streaks:
        streaks["crystallize_after"] = 3
    data["streaks"] = streaks

    crystals = data.get("crystallizations", [])
    for c in crystals:
        cpos = c.get("position", {})
        for key, default in [("alpha", 1.0), ("cave_depth", 0.5), ("L_net", 0.5)]:
            v = cpos.get(key, default)
            if not isinstance(v, (int, float)) or v != v:
                cpos[key] = default
        c["position"] = cpos

        tilt = c.get("tilt", {})
        for key in ("alpha_delta", "cave_delta", "L_net_delta"):
            v = tilt.get(key, 0.1)
            if not isinstance(v, (int, float)) or v != v or abs(v) > 10:
                tilt[key] = 0.1
        c["tilt"] = tilt

    data["crystallizations"] = crystals
    data["schema_version"] = 3
    return data


MIGRATIONS = [
    (1, 2, migrate_v1_to_v2),
    (2, 3, migrate_v2_to_v3),
]


def apply_migrations(data: dict, dry_run: bool) -> tuple:
    version  = data.get("schema_version", 1)
    applied  = []
    for from_v, to_v, fn in MIGRATIONS:
        if version == from_v:
            data    = fn(data)
            version = to_v
            applied.append(f"v{from_v}→v{to_v}: {fn.__doc__.strip().split(chr(10))[0]}")
    return data, applied


# ── Main commands ─────────────────────────────────────────────────────

def status():
    files = list(STATE_ROOT.glob("*.json"))
    if not files:
        print("No state files found.")
        return

    needs_migration = 0
    print(f"\n{'File':<40} {'Version':<10} {'Status'}")
    print("-" * 65)
    for f in sorted(files):
        v = _current_version(f)
        status = "✓ current" if v >= SCHEMA_VERSION else f"→ needs migration (v{v}→v{SCHEMA_VERSION})"
        if v < SCHEMA_VERSION:
            needs_migration += 1
        print(f"{f.name:<40} v{v:<9} {status}")

    print(f"\n{len(files)} files | {needs_migration} need migration")
    print(f"Target schema version: v{SCHEMA_VERSION}\n")


def run(dry_run: bool = False):
    files = list(STATE_ROOT.glob("*.json"))
    if not files:
        print("No state files found.")
        return

    migrated = 0
    skipped  = 0
    errors   = 0

    for f in sorted(files):
        v = _current_version(f)
        if v >= SCHEMA_VERSION:
            skipped += 1
            continue

        try:
            data     = json.loads(f.read_text())
            new_data, applied = apply_migrations(data, dry_run)

            if applied:
                backup = _backup_file(f, dry_run)
                if not dry_run:
                    f.write_text(json.dumps(new_data, indent=2))
                print(f"{'[DRY]' if dry_run else '[OK]'} {f.name}: "
                      f"{' | '.join(applied)} (backup: {backup.name})")
                migrated += 1
        except Exception as e:
            print(f"[ERROR] {f.name}: {e}")
            errors += 1

    print(f"\nDone: {migrated} migrated, {skipped} already current, {errors} errors")
    if dry_run:
        print("(Dry run — no files were modified)")


if __name__ == "__main__":
    cmd     = sys.argv[1] if len(sys.argv) > 1 else "status"
    dry_run = "--dry-run" in sys.argv

    if cmd == "status":
        status()
    elif cmd == "run":
        run(dry_run=dry_run)
    else:
        print("Usage: python scripts/migrate.py status | run [--dry-run]")