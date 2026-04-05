# ════════════════════════════════════════════════════════════════════════
# FOTNSSJ Viewer Portal
# Read-only. No auth required — but mounts on a separate container
# that only has checkpoint_data and state_data volumes (read-only).
# Shows the class knowledge graph: topics, crystals, positions.
# ════════════════════════════════════════════════════════════════════════
import math
import time
from flask import Blueprint, render_template_string, jsonify, request

viewer_bp = Blueprint("viewer", __name__, url_prefix="/view")

_VIEWER_BASE = """<!DOCTYPE html><html><head>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="60">
<style>
*{box-sizing:border-box;}
body{font-family:system-ui;background:#030712;color:#f1f5f9;margin:0;}
header{background:#0c1445;padding:1rem 2rem;
       display:flex;justify-content:space-between;align-items:center;}
header h1{margin:0;font-size:1.1rem;color:#818cf8;}
header span{font-size:.8rem;color:#475569;}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));
      gap:1rem;padding:1.5rem;}
.card{background:#0f172a;border-radius:10px;padding:1.25rem;
      border:1px solid #1e293b;}
.card h3{margin:0 0 .5rem;font-size:.9rem;color:#94a3b8;
          text-transform:uppercase;letter-spacing:.05em;}
.student-name{font-size:1.1rem;font-weight:bold;margin-bottom:.5rem;}
.topic-pill{display:inline-block;background:#1e3a5f;color:#93c5fd;
            padding:.2rem .6rem;border-radius:20px;font-size:.8rem;
            margin-bottom:.75rem;}
.axis-row{display:flex;align-items:center;gap:.5rem;margin-bottom:.4rem;
          font-size:.85rem;}
.axis-label{width:60px;color:#64748b;flex-shrink:0;}
.axis-bar{flex:1;height:8px;background:#1e293b;border-radius:4px;overflow:hidden;}
.axis-fill{height:100%;border-radius:4px;transition:width .3s;}
.fill-alpha{background:linear-gradient(to right,#4f46e5,#818cf8);}
.fill-cave {background:linear-gradient(to right,#065f46,#34d399);}
.fill-l    {background:linear-gradient(to right,#7c2d12,#fb923c);}
.axis-val{width:48px;text-align:right;color:#94a3b8;font-size:.8rem;}
.crystals{margin-top:.75rem;padding-top:.75rem;border-top:1px solid #1e293b;}
.crystal-chip{display:inline-block;background:#1e3a5f;color:#bfdbfe;
              padding:.15rem .5rem;border-radius:4px;font-size:.75rem;
              margin:.15rem .15rem 0 0;}
.no-crystals{font-size:.8rem;color:#334155;font-style:italic;}
.accuracy-bar{display:flex;align-items:center;gap:.5rem;margin-top:.5rem;}
.acc-track{flex:1;height:6px;background:#1e293b;border-radius:3px;}
.acc-fill{height:6px;border-radius:3px;}
.legend{padding:.75rem 1.5rem;display:flex;gap:1.5rem;flex-wrap:wrap;
        background:#0c1445;font-size:.8rem;color:#64748b;}
.legend span{display:flex;align-items:center;gap:.4rem;}
.dot{width:10px;height:10px;border-radius:50%;}
</style>
</head>
<body>
<header>
  <h1>FOTNSSJ — Class Knowledge Map</h1>
  <span>Auto-refreshes every 60s &nbsp;|&nbsp;
        {{ student_count }} students &nbsp;|&nbsp;
        {{ crystal_count }} crystals &nbsp;|&nbsp;
        {{ now }}</span>
</header>
<div class="legend">
  <span><div class="dot" style="background:#818cf8"></div> α = Bandwidth / Difficulty</span>
  <span><div class="dot" style="background:#34d399"></div> Cave = Stability Depth</span>
  <span><div class="dot" style="background:#fb923c"></div> L = Angular Momentum</span>
</div>
<div class="grid">
  {% for s in students %}
  <div class="card">
    <h3>Student</h3>
    <div class="student-name">{{ s.student_id }}</div>
    <span class="topic-pill">{{ s.topic }}</span>

    <div class="axis-row">
      <span class="axis-label">α</span>
      <div class="axis-bar">
        <div class="axis-fill fill-alpha"
             style="width:{{ [s.alpha*10,100]|min }}%"></div>
      </div>
      <span class="axis-val">{{ "%.2f"|format(s.alpha) }}</span>
    </div>
    <div class="axis-row">
      <span class="axis-label">Cave</span>
      <div class="axis-bar">
        <div class="axis-fill fill-cave"
             style="width:{{ [s.cave*10,100]|min }}%"></div>
      </div>
      <span class="axis-val">{{ "%.2f"|format(s.cave) }}</span>
    </div>
    <div class="axis-row">
      <span class="axis-label">L_net</span>
      <div class="axis-bar">
        <div class="axis-fill fill-l"
             style="width:{{ [s.l_net*10,100]|min }}%"></div>
      </div>
      <span class="axis-val">{{ "%.2f"|format(s.l_net) }}</span>
    </div>

    <div class="accuracy-bar">
      <span style="font-size:.75rem;color:#64748b;width:60px;">Accuracy</span>
      <div class="acc-track">
        <div class="acc-fill"
             style="width:{{ s.accuracy }}%;
                    background:{{ '#22c55e' if s.accuracy>=80
                                  else '#eab308' if s.accuracy>=50
                                  else '#ef4444' }}">
        </div>
      </div>
      <span style="font-size:.75rem;color:#94a3b8;width:36px;">
        {{ s.accuracy }}%
      </span>
    </div>

    <div class="crystals">
      {% if s.crystal_topics %}
        {% for t in s.crystal_topics %}
        <span class="crystal-chip">{{ t }}</span>
        {% endfor %}
      {% else %}
        <span class="no-crystals">No crystals yet</span>
      {% endif %}
    </div>
  </div>
  {% endfor %}
</div>
</body></html>"""

_TOPIC_VIEW = """<!DOCTYPE html><html><head>
<style>
body{font-family:system-ui;background:#030712;color:#f1f5f9;
     margin:0;padding:2rem;}
h1{color:#818cf8;}
.bar-row{display:flex;align-items:center;gap:1rem;margin-bottom:.5rem;}
.label{width:200px;font-size:.9rem;color:#94a3b8;
        white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.bar{height:20px;background:#818cf8;border-radius:3px;min-width:2px;}
.count{font-size:.85rem;color:#64748b;}
</style></head><body>
<h1>Topic Distribution</h1>
<p style="color:#475569;">How many students are at each topic</p>
{% for t in topics %}
<div class="bar-row">
  <div class="label">{{ t.name }}</div>
  <div class="bar" style="width:{{ t.count * 40 }}px"></div>
  <div class="count">{{ t.count }} student{{ 's' if t.count != 1 }}</div>
</div>
{% endfor %}
<p style="margin-top:2rem;">
  <a href="{{ url_for('viewer.index') }}" style="color:#818cf8;">← Class Map</a>
</p>
</body></html>"""


@viewer_bp.route("/")
def index():
    sm  = viewer_bp.session_manager
    rss = viewer_bp.raw_session_store

    all_ids  = set(rss.list_students()) | set(sm.all_student_ids())
    students = []
    total_crystals = 0

    for sid in sorted(all_ids):
        data     = sm.get_or_create(sid)
        summary  = rss.student_summary(sid)
        crystals = sm.get_crystals(sid)
        total_crystals += len(crystals)

        students.append({
            "student_id":    sid,
            "topic":         data["current_topic"].replace("_", " "),
            "alpha":         data["position"].alpha,
            "cave":          data["position"].cave_depth,
            "l_net":         data["position"].L_net,
            "accuracy":      summary["accuracy"],
            "crystal_topics": list({c.topic.replace("_", " ") for c in crystals}),
        })

    return render_template_string(
        _VIEWER_BASE,
        students=students,
        student_count=len(students),
        crystal_count=total_crystals,
        now=time.strftime("%H:%M:%S"),
    )


@viewer_bp.route("/topics")
def topics():
    sm = viewer_bp.session_manager
    from collections import Counter
    counts = Counter()
    for sid in sm.all_student_ids():
        data = sm.get_or_create(sid)
        counts[data["current_topic"]] += 1

    topic_list = [
        {"name": t.replace("_", " "), "count": c}
        for t, c in sorted(counts.items(), key=lambda x: x[1], reverse=True)
    ]
    return render_template_string(_TOPIC_VIEW, topics=topic_list)


@viewer_bp.route("/api/snapshot")
def api_snapshot():
    """JSON snapshot for external dashboards."""
    sm  = viewer_bp.session_manager
    rss = viewer_bp.raw_session_store
    all_ids = set(rss.list_students()) | set(sm.all_student_ids())
    out = []
    for sid in sorted(all_ids):
        data    = sm.get_or_create(sid)
        summary = rss.student_summary(sid)
        crystals = sm.get_crystals(sid)
        out.append({
            "student_id": sid,
            "topic":      data["current_topic"],
            "domain":     data["current_domain"],
            "position":   data["position"].to_dict(),
            "accuracy":   summary["accuracy"],
            "attempts":   summary["total_attempts"],
            "crystals":   len(crystals),
        })
    return jsonify({"students": out, "timestamp": time.time()})


def register_viewer_blueprint(app, session_manager, raw_session_store):
    viewer_bp.session_manager   = session_manager
    viewer_bp.raw_session_store = raw_session_store
    app.register_blueprint(viewer_bp)