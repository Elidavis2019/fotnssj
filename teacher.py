# ════════════════════════════════════════════════════════════════════════
# FOTNSSJ Teacher Portal
# Separate Blueprint — mounted at /teacher in fotnssj.py
#
# Features:
#   - Teacher login / logout
#   - View all students (progress overview)
#   - Drill into a student: trajectory, crystals, position
#   - Edit a crystal (question/answer/bridge)
#   - Mark a crystal for reinforcement
#   - Add a custom topic note
#   - View live dispatcher metrics
# ════════════════════════════════════════════════════════════════════════
from flask import (
    Blueprint, render_template_string, request, session,
    redirect, url_for, jsonify, Response,
)
import json
import time

teacher_bp = Blueprint("teacher", __name__, url_prefix="/teacher")


# ── Template ──────────────────────────────────────────────────────────

_LOGIN = """<!DOCTYPE html><html><head>
<style>
body{font-family:system-ui;background:#1e1b4b;color:#e0e7ff;
     display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;}
.box{background:#312e81;padding:2.5rem;border-radius:12px;min-width:320px;}
h2{margin-top:0;color:#a5b4fc;}
input{width:100%;padding:.75rem;margin-bottom:1rem;border:1px solid #4338ca;
      background:#1e1b4b;color:#e0e7ff;border-radius:6px;box-sizing:border-box;}
.btn{background:#6366f1;color:white;width:100%;padding:.75rem;border:none;
     border-radius:6px;cursor:pointer;font-size:1rem;}
.err{color:#f87171;margin-bottom:1rem;}
</style></head><body>
<div class="box">
  <h2>Teacher Portal</h2>
  {% if error %}<p class="err">{{ error }}</p>{% endif %}
  <form method="POST">
    <input name="username" placeholder="Username" autocomplete="username">
    <input type="password" name="password" placeholder="Password"
           autocomplete="current-password">
    <button class="btn">Sign In</button>
  </form>
</div>
</body></html>"""

_BASE = """<!DOCTYPE html><html><head>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
*{box-sizing:border-box;}
body{font-family:system-ui;background:#0f172a;color:#e2e8f0;margin:0;}
nav{background:#1e293b;padding:1rem 2rem;display:flex;
    justify-content:space-between;align-items:center;}
nav a{color:#94a3b8;text-decoration:none;margin-left:1rem;font-size:.9rem;}
nav a:hover{color:#e2e8f0;}
.logo{color:#818cf8;font-weight:bold;font-size:1.1rem;}
main{padding:2rem;}
.card{background:#1e293b;padding:1.5rem;border-radius:8px;margin-bottom:1.5rem;}
.card h2{margin-top:0;color:#94a3b8;font-size:1rem;text-transform:uppercase;
          letter-spacing:.05em;}
table{width:100%;border-collapse:collapse;}
th{text-align:left;color:#64748b;font-size:.8rem;padding:.5rem;
   border-bottom:1px solid #334155;text-transform:uppercase;}
td{padding:.5rem;border-bottom:1px solid #1e293b;font-size:.9rem;}
tr:hover td{background:#263548;}
.badge{display:inline-block;padding:.15rem .5rem;border-radius:4px;
       font-size:.75rem;font-weight:bold;}
.green{background:#166534;color:#bbf7d0;}
.yellow{background:#854d0e;color:#fef08a;}
.red{background:#991b1b;color:#fecaca;}
.blue{background:#1e3a5f;color:#bfdbfe;}
.btn{display:inline-block;padding:.4rem .8rem;border-radius:4px;
     font-size:.85rem;text-decoration:none;border:none;cursor:pointer;}
.btn-primary{background:#4f46e5;color:white;}
.btn-sm{padding:.25rem .6rem;font-size:.8rem;}
.btn-warn{background:#92400e;color:#fef3c7;}
.btn-danger{background:#991b1b;color:white;}
input,textarea,select{background:#0f172a;border:1px solid #334155;
    color:#e2e8f0;padding:.5rem;border-radius:4px;width:100%;margin-bottom:.75rem;}
label{font-size:.85rem;color:#94a3b8;display:block;margin-bottom:.25rem;}
.metric{text-align:center;padding:1rem;}
.metric .val{font-size:2rem;font-weight:bold;color:#818cf8;}
.metric .lbl{font-size:.8rem;color:#64748b;text-transform:uppercase;}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1rem;}
.pos-bar{height:6px;background:#334155;border-radius:3px;margin-top:.25rem;}
.pos-fill{height:6px;border-radius:3px;background:#818cf8;}
code{background:#334155;padding:.1rem .3rem;border-radius:3px;font-size:.8rem;}
</style>
</head><body>
<nav>
  <span class="logo">FOTNSSJ Teacher</span>
  <div>
    <a href="{{ url_for('teacher.dashboard') }}">Dashboard</a>
    <a href="{{ url_for('teacher.metrics_view') }}">Metrics</a>
    <a href="{{ url_for('teacher.logout') }}">Sign Out</a>
  </div>
</nav>
<main>{% block content %}{% endblock %}</main>
</body></html>"""

_DASHBOARD = _BASE.replace("{% block content %}{% endblock %}", """
{% block content %}
<div class="card">
  <h2>Class Overview — {{ date }}</h2>
  <div class="grid">
    <div class="metric"><div class="val">{{ stats.total }}</div>
      <div class="lbl">Students</div></div>
    <div class="metric"><div class="val">{{ stats.active_today }}</div>
      <div class="lbl">Active Today</div></div>
    <div class="metric"><div class="val">{{ stats.accuracy }}%</div>
      <div class="lbl">Avg Accuracy</div></div>
    <div class="metric"><div class="val">{{ stats.crystals }}</div>
      <div class="lbl">Crystals</div></div>
  </div>
</div>
<div class="card">
  <h2>Students</h2>
  <table>
    <tr>
      <th>ID</th><th>Topic</th><th>α</th>
      <th>Crystals</th><th>Attempts</th><th>Accuracy</th><th>Last Seen</th><th></th>
    </tr>
    {% for s in students %}
    <tr>
      <td><code>{{ s.student_id }}</code></td>
      <td>{{ s.topic }}</td>
      <td>
        {{ "%.2f"|format(s.alpha) }}
        <div class="pos-bar">
          <div class="pos-fill" style="width:{{ [s.alpha*10,100]|min }}%"></div>
        </div>
      </td>
      <td>{{ s.crystals }}</td>
      <td>{{ s.attempts }}</td>
      <td>
        {% if s.accuracy >= 80 %}<span class="badge green">{{ s.accuracy }}%</span>
        {% elif s.accuracy >= 50 %}<span class="badge yellow">{{ s.accuracy }}%</span>
        {% else %}<span class="badge red">{{ s.accuracy }}%</span>{% endif %}
      </td>
      <td>{{ s.last_seen }}</td>
      <td>
        <a href="{{ url_for('teacher.student_detail', student_id=s.student_id) }}"
           class="btn btn-primary btn-sm">View</a>
      </td>
    </tr>
    {% endfor %}
  </table>
</div>
{% endblock %}""")

_STUDENT_DETAIL = _BASE.replace("{% block content %}{% endblock %}", """
{% block content %}
<div class="card">
  <h2>Student: <code>{{ student_id }}</code></h2>
  <div class="grid">
    <div class="metric"><div class="val">{{ summary.total_attempts }}</div>
      <div class="lbl">Attempts</div></div>
    <div class="metric"><div class="val">{{ summary.accuracy }}%</div>
      <div class="lbl">Accuracy</div></div>
    <div class="metric"><div class="val">{{ crystals|length }}</div>
      <div class="lbl">Crystals</div></div>
    <div class="metric">
      <div class="val">{{ "%.3f"|format(position.alpha) }}</div>
      <div class="lbl">α (Bandwidth)</div></div>
    <div class="metric">
      <div class="val">{{ "%.3f"|format(position.cave_depth) }}</div>
      <div class="lbl">Cave Depth</div></div>
    <div class="metric">
      <div class="val">{{ "%.3f"|format(position.L_net) }}</div>
      <div class="lbl">L_net</div></div>
  </div>
  <p style="color:#64748b;font-size:.85rem;">
    Current topic: <strong style="color:#e2e8f0;">{{ topic }}</strong> /
    {{ domain }}
  </p>
</div>

<div class="card">
  <h2>Crystallized Knowledge</h2>
  {% for c in crystals %}
  <div style="background:#0f172a;padding:1rem;margin-bottom:1rem;border-radius:6px;
              border-left:3px solid {{ '#818cf8' if not c.needs_reinforcement else '#f59e0b' }};">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;">
      <div>
        {% if c.needs_reinforcement %}
        <span class="badge yellow">Needs Reinforcement</span>
        {% endif %}
        <strong>{{ c.topic.replace('_',' ') }}</strong>
        <span style="color:#64748b;font-size:.8rem;margin-left:.5rem;">
          depth={{ c.depth_level }} refs={{ c.reference_count }}
        </span>
      </div>
      <code style="font-size:.75rem;color:#475569;">{{ c.id[:8] }}</code>
    </div>
    <p style="margin:.5rem 0 .25rem;"><strong>Q:</strong> {{ c.question }}</p>
    <p style="margin:.25rem 0;"><strong>A:</strong> {{ c.correct_answer }}</p>
    <p style="margin:.25rem 0;color:#94a3b8;font-style:italic;">{{ c.bridge }}</p>

    <details style="margin-top:.5rem;">
      <summary style="cursor:pointer;color:#64748b;font-size:.85rem;">Edit crystal</summary>
      <form method="POST"
            action="{{ url_for('teacher.edit_crystal',
                               student_id=student_id, crystal_id=c.id) }}"
            style="margin-top:.75rem;">
        <label>Question</label>
        <input name="question" value="{{ c.question }}">
        <label>Correct Answer</label>
        <input name="correct_answer" value="{{ c.correct_answer }}">
        <label>Bridge (Socratic link)</label>
        <textarea name="bridge" rows="2">{{ c.bridge }}</textarea>
        <label>Explanation</label>
        <textarea name="explanation" rows="2">{{ c.explanation }}</textarea>
        <button class="btn btn-primary btn-sm" type="submit">Save Changes</button>
        <a href="{{ url_for('teacher.flag_reinforcement',
                             student_id=student_id, crystal_id=c.id) }}"
           class="btn btn-warn btn-sm"
           style="margin-left:.5rem;">Flag Reinforcement</a>
      </form>
    </details>
  </div>
  {% endfor %}
  {% if not crystals %}
  <p style="color:#475569;">No crystals yet for this student.</p>
  {% endif %}
</div>

<div class="card">
  <h2>Add Topic Note</h2>
  <form method="POST" action="{{ url_for('teacher.add_note', student_id=student_id) }}">
    <label>Note</label>
    <textarea name="note" rows="3" placeholder="Observation about this student..."></textarea>
    <button class="btn btn-primary btn-sm" type="submit">Add Note</button>
  </form>
  {% if notes %}
  <div style="margin-top:1rem;">
    {% for note in notes %}
    <div style="background:#0f172a;padding:.75rem;margin-bottom:.5rem;
                border-radius:6px;font-size:.85rem;">
      <span style="color:#64748b;">{{ note.ts }}</span> — {{ note.text }}
    </div>
    {% endfor %}
  </div>
  {% endif %}
</div>

<p><a href="{{ url_for('teacher.dashboard') }}" style="color:#818cf8;">
  ← Back to Dashboard</a></p>
{% endblock %}""")

_METRICS = _BASE.replace("{% block content %}{% endblock %}", """
{% block content %}
<div class="card">
  <h2>Live Dispatcher Metrics</h2>
  <div class="grid">
    <div class="metric"><div class="val">{{ m.queue_depth }}</div>
      <div class="lbl">Queue Depth</div></div>
    <div class="metric"><div class="val">{{ m.dispatched }}</div>
      <div class="lbl">Dispatched</div></div>
    <div class="metric"><div class="val">{{ m.dropped }}</div>
      <div class="lbl">Dropped</div></div>
    <div class="metric"><div class="val">{{ m.timeouts }}</div>
      <div class="lbl">Timeouts</div></div>
    <div class="metric"><div class="val">{{ m.pending_students }}</div>
      <div class="lbl">Pending Students</div></div>
  </div>
</div>
<div class="card">
  <h2>Geometry Manifest</h2>
  <div class="grid">
    <div class="metric"><div class="val">{{ geo.unresolved }}</div>
      <div class="lbl">Unresolved</div></div>
    <div class="metric">
      <div class="val" style="color:#f87171;">{{ geo.critical_unresolved }}</div>
      <div class="lbl">Critical</div></div>
    <div class="metric">
      <div class="val" style="color:#fb923c;">{{ geo.error_unresolved }}</div>
      <div class="lbl">Errors</div></div>
    <div class="metric">
      <div class="val" style="color:#facc15;">{{ geo.warning_unresolved }}</div>
      <div class="lbl">Warnings</div></div>
  </div>
  {% if geo.affected_students %}
  <p style="font-size:.85rem;color:#64748b;">
    Affected: {% for s in geo.affected_students %}<code>{{ s }}</code> {% endfor %}
  </p>
  {% endif %}
</div>
<p style="color:#475569;font-size:.8rem;">
  Page auto-reloads every 30s.
  <a href="{{ url_for('teacher.metrics_view') }}" style="color:#818cf8;">Refresh now</a>
</p>
{% endblock %}""")


# ── Auth helpers ──────────────────────────────────────────────────────

def _teacher_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = session.get("teacher_token")
        if not token:
            return redirect(url_for("teacher.login"))
        # teacher_auth is injected at registration time
        if not teacher_bp.teacher_auth.validate_token(token):
            session.pop("teacher_token", None)
            return redirect(url_for("teacher.login"))
        return fn(*args, **kwargs)
    return wrapper


# ── Note store (lightweight, per-student JSONL) ───────────────────────

import threading
from pathlib import Path

_notes_lock = threading.Lock()
_NOTES_ROOT = Path("/data/state/notes")


def _load_notes(student_id: str) -> list:
    path = _NOTES_ROOT / f"{student_id}.jsonl"
    if not path.exists():
        return []
    notes = []
    for line in path.read_text().splitlines():
        try:
            notes.append(json.loads(line))
        except Exception:
            pass
    return list(reversed(notes))


def _save_note(student_id: str, text: str, teacher: str):
    _NOTES_ROOT.mkdir(parents=True, exist_ok=True)
    path = _NOTES_ROOT / f"{student_id}.jsonl"
    entry = {
        "ts":      time.strftime("%Y-%m-%d %H:%M"),
        "text":    text[:500],
        "teacher": teacher,
    }
    with _notes_lock:
        with open(path, "a") as f:
            f.write(json.dumps(entry) + "\n")


# ── Routes ────────────────────────────────────────────────────────────

@teacher_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username", "")
        p = request.form.get("password", "")
        token = teacher_bp.teacher_auth.login(u, p)
        if token:
            session["teacher_token"] = token
            session["teacher_name"]  = u
            teacher_bp.audit_log.record(
                actor=u, action="teacher_login",
                ip=request.remote_addr, success=True
            )
            return redirect(url_for("teacher.dashboard"))
        teacher_bp.audit_log.record(
            actor=u, action="teacher_login",
            ip=request.remote_addr, success=False
        )
        return render_template_string(_LOGIN, error="Invalid credentials")
    return render_template_string(_LOGIN, error=None)


@teacher_bp.route("/logout")
def logout():
    actor = session.get("teacher_name", "unknown")
    session.pop("teacher_token", None)
    session.pop("teacher_name",  None)
    teacher_bp.audit_log.record(actor=actor, action="teacher_logout")
    return redirect(url_for("teacher.login"))


@teacher_bp.route("/")
@_teacher_required
def dashboard():
    sm  = teacher_bp.session_manager
    rss = teacher_bp.raw_session_store

    all_ids  = set(rss.list_students()) | set(sm.all_student_ids())
    students = []
    total_attempts = total_correct = 0

    for sid in sorted(all_ids):
        summary  = rss.student_summary(sid)
        data     = sm.get_or_create(sid)
        crystals = sm.get_crystals(sid)
        students.append({
            "student_id": sid,
            "topic":      data["current_topic"].replace("_", " "),
            "alpha":      data["position"].alpha,
            "crystals":   len(crystals),
            "attempts":   summary["total_attempts"],
            "accuracy":   summary["accuracy"],
            "last_seen":  summary.get("last_seen", "—"),
        })
        total_attempts += summary["total_attempts"]
        total_correct  += summary["correct"]

    today = time.strftime("%Y-%m-%d")
    active_today = sum(
        1 for s in students
        if s["last_seen"].startswith(today)
    )

    return render_template_string(
        _DASHBOARD,
        students=students,
        date=today,
        stats={
            "total":        len(students),
            "active_today": active_today,
            "accuracy":     round(total_correct / max(total_attempts, 1) * 100, 1),
            "crystals":     sum(s["crystals"] for s in students),
        },
    )


@teacher_bp.route("/student/<student_id>")
@_teacher_required
def student_detail(student_id: str):
    sm      = teacher_bp.session_manager
    rss     = teacher_bp.raw_session_store
    data    = sm.get_or_create(student_id)
    summary = rss.student_summary(student_id)
    crystals = sm.get_crystals(student_id)
    notes    = _load_notes(student_id)

    return render_template_string(
        _STUDENT_DETAIL,
        student_id=student_id,
        summary=summary,
        crystals=crystals,
        position=data["position"],
        topic=data["current_topic"].replace("_", " "),
        domain=data["current_domain"],
        notes=notes,
    )


@teacher_bp.route("/student/<student_id>/crystal/<crystal_id>/edit",
                  methods=["POST"])
@_teacher_required
def edit_crystal(student_id: str, crystal_id: str):
    sm   = teacher_bp.session_manager
    data = sm.get_or_create(student_id)
    crystal = data["crystallizations"].get(crystal_id)

    if crystal:
        old_q = crystal.question
        crystal.question       = request.form.get("question",       crystal.question)[:500]
        crystal.correct_answer = request.form.get("correct_answer", crystal.correct_answer)[:200]
        crystal.bridge         = request.form.get("bridge",         crystal.bridge)[:500]
        crystal.explanation    = request.form.get("explanation",    crystal.explanation)[:1000]
        crystal.edit_history.append({
            "ts":      time.time(),
            "teacher": session.get("teacher_name", "unknown"),
            "old_q":   old_q,
        })
        sm.save_crystal(student_id, crystal)
        teacher_bp.audit_log.record(
            actor=session.get("teacher_name", "unknown"),
            action="edit_crystal",
            target=f"{student_id}/{crystal_id}",
            ip=request.remote_addr,
        )

    return redirect(url_for("teacher.student_detail", student_id=student_id))


@teacher_bp.route("/student/<student_id>/crystal/<crystal_id>/flag")
@_teacher_required
def flag_reinforcement(student_id: str, crystal_id: str):
    sm   = teacher_bp.session_manager
    data = sm.get_or_create(student_id)
    crystal = data["crystallizations"].get(crystal_id)
    if crystal:
        crystal.reference_count = max(crystal.reference_count, 4)
        sm.save_crystal(student_id, crystal)
        teacher_bp.audit_log.record(
            actor=session.get("teacher_name", "unknown"),
            action="flag_reinforcement",
            target=f"{student_id}/{crystal_id}",
            ip=request.remote_addr,
        )
    return redirect(url_for("teacher.student_detail", student_id=student_id))


@teacher_bp.route("/student/<student_id>/note", methods=["POST"])
@_teacher_required
def add_note(student_id: str):
    text = request.form.get("note", "").strip()
    if text:
        teacher = session.get("teacher_name", "unknown")
        _save_note(student_id, text, teacher)
        teacher_bp.audit_log.record(
            actor=teacher, action="add_note",
            target=student_id, ip=request.remote_addr,
        )
    return redirect(url_for("teacher.student_detail", student_id=student_id))


@teacher_bp.route("/metrics")
@_teacher_required
def metrics_view():
    return render_template_string(
        _METRICS,
        m=teacher_bp.dispatcher.metrics,
        geo=teacher_bp.geometry_manifest.summary(),
    )


@teacher_bp.route("/api/students")
@_teacher_required
def api_students():
    """JSON endpoint for future React/Vue dashboard."""
    sm  = teacher_bp.session_manager
    rss = teacher_bp.raw_session_store
    all_ids = set(rss.list_students()) | set(sm.all_student_ids())
    out = []
    for sid in sorted(all_ids):
        data    = sm.get_or_create(sid)
        summary = rss.student_summary(sid)
        out.append({
            "student_id": sid,
            "topic":      data["current_topic"],
            "domain":     data["current_domain"],
            "position":   data["position"].to_dict(),
            "crystals":   len(sm.get_crystals(sid)),
            **summary,
        })
    return jsonify(out)


def register_teacher_blueprint(
    app,
    teacher_auth,
    session_manager,
    raw_session_store,
    dispatcher,
    geometry_manifest,
    audit_log,
):
    """
    Wire dependencies into the blueprint namespace.
    Call from fotnssj.py §8 after all globals are created.
    """
    teacher_bp.teacher_auth      = teacher_auth
    teacher_bp.session_manager   = session_manager
    teacher_bp.raw_session_store = raw_session_store
    teacher_bp.dispatcher        = dispatcher
    teacher_bp.geometry_manifest = geometry_manifest
    teacher_bp.audit_log         = audit_log
    app.register_blueprint(teacher_bp)