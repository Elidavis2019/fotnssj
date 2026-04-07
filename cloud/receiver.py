# ════════════════════════════════════════════════════════════════════════
# FOTNSSJ Cloud Trajectory Receiver
#
# Deploy standalone:
#   pip install flask
#   python cloud/receiver.py
#
# Docker:
#   docker build -f cloud/Dockerfile.receiver -t fotnssj-receiver .
#   docker run -p 8080:8080 -v receiver_data:/data fotnssj-receiver
# ════════════════════════════════════════════════════════════════════════
import base64
import json
import os
import sqlite3
import time
import zlib
from contextlib import contextmanager
from pathlib import Path

from flask import Flask, jsonify, request

app  = Flask(__name__)
_DB  = os.environ.get("RECEIVER_DB", "/data/receiver/trajectories.db")


# ── Database setup ────────────────────────────────────────────────────

def _init_db():
    Path(_DB).parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS trajectory_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id  TEXT    NOT NULL,
                event_type  TEXT    NOT NULL,
                from_hash   TEXT,
                to_hash     TEXT,
                alpha       REAL,
                cave_depth  REAL,
                l_net       REAL,
                alpha_delta REAL,
                cave_delta  REAL,
                l_net_delta REAL,
                timestamp   REAL    NOT NULL,
                raw_wire    TEXT
            );

            CREATE TABLE IF NOT EXISTS crystal_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id  TEXT    NOT NULL,
                topic       TEXT    NOT NULL,
                crystal_id  TEXT,
                question    TEXT,
                answer      TEXT,
                timestamp   REAL    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS student_positions (
                student_id  TEXT PRIMARY KEY,
                alpha       REAL,
                cave_depth  REAL,
                l_net       REAL,
                updated_at  REAL
            );

            CREATE INDEX IF NOT EXISTS idx_traj_student
                ON trajectory_events(student_id);
            CREATE INDEX IF NOT EXISTS idx_traj_event
                ON trajectory_events(event_type);
            CREATE INDEX IF NOT EXISTS idx_crystal_topic
                ON crystal_events(topic);
        """)


@contextmanager
def _conn():
    conn = sqlite3.connect(_DB)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ── Ingestion ─────────────────────────────────────────────────────────

def _ingest_diff(wire: str):
    raw = zlib.decompress(base64.b64decode(wire))
    d   = json.loads(raw)

    sid      = d["sid"]
    event    = d["ev"]
    ts       = d["ts"]
    pd       = d.get("pd", {})
    tv       = d.get("tv", {})
    crystals = d.get("nc", [])

    with _conn() as conn:
        # Upsert current position (accumulate deltas)
        row = conn.execute(
            "SELECT alpha, cave_depth, l_net FROM student_positions WHERE student_id = ?",
            (sid,)
        ).fetchone()

        prev_alpha = row["alpha"]      if row else 1.0
        prev_cave  = row["cave_depth"] if row else 0.5
        prev_l     = row["l_net"]      if row else 0.5

        new_alpha = round(prev_alpha + pd.get("alpha",      0.0), 6)
        new_cave  = round(prev_cave  + pd.get("cave_depth", 0.0), 6)
        new_l     = round(prev_l     + pd.get("L_net",      0.0), 6)

        conn.execute("""
            INSERT INTO student_positions (student_id, alpha, cave_depth, l_net, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(student_id) DO UPDATE SET
                alpha=excluded.alpha,
                cave_depth=excluded.cave_depth,
                l_net=excluded.l_net,
                updated_at=excluded.updated_at
        """, (sid, new_alpha, new_cave, new_l, ts))

        # Insert trajectory event
        conn.execute("""
            INSERT INTO trajectory_events
                (student_id, event_type, from_hash, to_hash,
                 alpha, cave_depth, l_net,
                 alpha_delta, cave_delta, l_net_delta,
                 timestamp, raw_wire)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sid, event,
            d.get("fh"), d.get("th"),
            new_alpha, new_cave, new_l,
            tv.get("alpha_delta"), tv.get("cave_delta"), tv.get("L_net_delta"),
            ts, wire,
        ))

        # Insert crystal events
        for crystal in crystals:
            conn.execute("""
                INSERT INTO crystal_events
                    (student_id, topic, crystal_id, question, answer, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                sid,
                crystal.get("topic", "unknown"),
                crystal.get("id"),
                crystal.get("question"),
                crystal.get("correct_answer"),
                ts,
            ))


# ── Routes ────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    try:
        with _conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) as c FROM trajectory_events"
            ).fetchone()["c"]
        return jsonify({"status": "ok", "events": count, "time": time.time()})
    except Exception as e:
        return jsonify({"status": "error", "detail": str(e)}), 500


@app.route("/sync", methods=["POST"])
def receive():
    batch = request.json or []
    ok    = 0
    errors = []
    for wire in batch:
        try:
            _ingest_diff(wire)
            ok += 1
        except Exception as e:
            errors.append(str(e))
    return jsonify({"received": ok, "errors": errors})


@app.route("/graph/positions")
def positions():
    with _conn() as conn:
        rows = conn.execute(
            "SELECT student_id, alpha, cave_depth, l_net, updated_at "
            "FROM student_positions ORDER BY updated_at DESC"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/graph/trajectory/<student_id>")
def trajectory(student_id: str):
    limit = min(int(request.args.get("limit", 100)), 1000)
    with _conn() as conn:
        pos  = conn.execute(
            "SELECT alpha, cave_depth, l_net FROM student_positions WHERE student_id = ?",
            (student_id,)
        ).fetchone()
        rows = conn.execute(
            """SELECT event_type, alpha, cave_depth, l_net,
                      alpha_delta, cave_delta, l_net_delta, timestamp
               FROM trajectory_events
               WHERE student_id = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (student_id, limit)
        ).fetchall()
    return jsonify({
        "student_id":      student_id,
        "current_position": dict(pos) if pos else None,
        "points":          len(rows),
        "trajectory":      [dict(r) for r in rows],
    })


@app.route("/graph/crystals/<topic>")
def crystals_by_topic(topic: str):
    with _conn() as conn:
        rows = conn.execute(
            """SELECT student_id, crystal_id, question, answer, timestamp
               FROM crystal_events WHERE topic = ?
               ORDER BY timestamp DESC LIMIT 200""",
            (topic,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/graph/struggles")
def struggles():
    with _conn() as conn:
        rows = conn.execute(
            """SELECT student_id, COUNT(*) as wrong_count
               FROM trajectory_events
               WHERE event_type = 'incorrect'
               GROUP BY student_id
               ORDER BY wrong_count DESC""",
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/graph/summary")
def summary():
    with _conn() as conn:
        students = conn.execute(
            "SELECT COUNT(DISTINCT student_id) as c FROM trajectory_events"
        ).fetchone()["c"]
        events = conn.execute(
            "SELECT COUNT(*) as c FROM trajectory_events"
        ).fetchone()["c"]
        crystals = conn.execute(
            "SELECT COUNT(*) as c FROM crystal_events"
        ).fetchone()["c"]
        correct = conn.execute(
            "SELECT COUNT(*) as c FROM trajectory_events WHERE event_type = 'correct'"
        ).fetchone()["c"]
        incorrect = conn.execute(
            "SELECT COUNT(*) as c FROM trajectory_events WHERE event_type = 'incorrect'"
        ).fetchone()["c"]
    return jsonify({
        "students":     students,
        "total_events": events,
        "correct":      correct,
        "incorrect":    incorrect,
        "accuracy":     round(correct / max(correct + incorrect, 1) * 100, 1),
        "crystals":     crystals,
    })


@app.route("/graph/heatmap")
def heatmap():
    """
    Returns a grid of (alpha_bucket, cave_bucket) → event_count
    for visualizing where on the manifold students spend most time.
    Bucket size = 1.0 unit.
    """
    with _conn() as conn:
        rows = conn.execute(
            """SELECT CAST(alpha AS INT)      as ab,
                      CAST(cave_depth AS INT) as cb,
                      COUNT(*)                as count
               FROM trajectory_events
               WHERE alpha IS NOT NULL AND cave_depth IS NOT NULL
               GROUP BY ab, cb"""
        ).fetchall()
    return jsonify([dict(r) for r in rows])


if __name__ == "__main__":
    _init_db()
    print("[RECEIVER] Database initialized")
    print("[RECEIVER] Listening on http://0.0.0.0:8080")
    app.run(host="0.0.0.0", port=8080)