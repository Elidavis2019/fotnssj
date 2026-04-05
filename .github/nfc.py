# ════════════════════════════════════════════════════════════════════════
# NFC Station Management
# Admin Blueprint — mounted at /admin/stations
# Create, edit, deactivate, and QR-generate station links.
# ════════════════════════════════════════════════════════════════════════
import json
import time
import uuid
from flask import (
    Blueprint, render_template_string, request,
    session, redirect, url_for, Response,
)

nfc_bp = Blueprint("nfc", __name__, url_prefix="/admin/stations")

_STATION_MGMT = """<!DOCTYPE html><html><head>
<style>
body{font-family:system-ui;background:#18181b;color:#e4e4e7;padding:2rem;}
.card{background:#27272a;padding:1.5rem;border-radius:8px;margin-bottom:1.5rem;}
h1{margin-top:0;}h2{color:#a1a1aa;font-size:.9rem;text-transform:uppercase;
   letter-spacing:.05em;margin-top:0;}
table{width:100%;border-collapse:collapse;}
th{text-align:left;color:#71717a;font-size:.8rem;padding:.4rem;
   border-bottom:1px solid #3f3f46;}
td{padding:.5rem;border-bottom:1px solid #27272a;font-size:.9rem;}
.btn{display:inline-block;padding:.35rem .75rem;border-radius:4px;
     font-size:.8rem;border:none;cursor:pointer;text-decoration:none;}
.btn-blue{background:#3b82f6;color:white;}
.btn-red{background:#dc2626;color:white;}
.btn-green{background:#16a34a;color:white;}
.btn-gray{background:#52525b;color:white;}
input,select{background:#3f3f46;border:1px solid #52525b;color:#e4e4e7;
    padding:.5rem;border-radius:4px;width:100%;margin-bottom:.75rem;}
label{font-size:.85rem;color:#a1a1aa;display:block;margin-bottom:.2rem;}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:.4rem;}
.scan-count{color:#71717a;font-size:.8rem;}
.qr-link{font-family:monospace;font-size:.75rem;color:#60a5fa;word-break:break-all;}
.color-swatch{display:inline-block;width:16px;height:16px;border-radius:3px;
              vertical-align:middle;margin-right:.4rem;}
</style>
</head><body>
<h1>NFC Station Management</h1>

<div class="card">
  <h2>Add New Station</h2>
  <form method="POST" action="{{ url_for('nfc.create_station') }}">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;">
      <div>
        <label>Label</label>
        <input name="label" placeholder="Addition Station" required>
      </div>
      <div>
        <label>Location (physical)</label>
        <input name="location" placeholder="Back wall, table 3...">
      </div>
      <div>
        <label>Domain</label>
        <select name="domain" id="domain-sel" onchange="updateTopics()">
          {% for domain, topics in domains.items() %}
          <option value="{{ domain }}">{{ domain }}</option>
          {% endfor %}
        </select>
      </div>
      <div>
        <label>Topic</label>
        <select name="topic" id="topic-sel">
          {% for domain, topics in domains.items() %}
          {% for topic in topics %}
          <option value="{{ topic }}"
            data-domain="{{ domain }}">{{ topic.replace('_',' ') }}</option>
          {% endfor %}
          {% endfor %}
        </select>
      </div>
      <div>
        <label>Colour</label>
        <input type="color" name="color" value="#3b82f6"
               style="height:2.4rem;padding:.1rem;">
      </div>
    </div>
    <button class="btn btn-blue" type="submit">Create Station</button>
  </form>
</div>

<div class="card">
  <h2>Active Stations</h2>
  <table>
    <tr>
      <th></th><th>Label</th><th>Topic</th><th>Location</th>
      <th>Scans</th><th>NFC URL</th><th>Actions</th>
    </tr>
    {% for s in stations %}
    <tr>
      <td>
        <span class="color-swatch" style="background:{{ s.color }}"></span>
        <span class="dot" style="background:{{ '#22c55e' if s.active else '#ef4444' }}"></span>
      </td>
      <td><strong>{{ s.label }}</strong></td>
      <td>{{ s.topic.replace('_',' ') }} / {{ s.domain }}</td>
      <td>{{ s.location }}</td>
      <td><span class="scan-count">{{ s.scan_count }} scans</span></td>
      <td>
        <span class="qr-link">{{ base_url }}/station/{{ s.id }}</span>
      </td>
      <td>
        <a href="{{ url_for('nfc.station_qr', station_id=s.id) }}"
           class="btn btn-gray">QR</a>
        {% if s.active %}
        <a href="{{ url_for('nfc.deactivate', station_id=s.id) }}"
           class="btn btn-red" style="margin-left:.25rem;">Deactivate</a>
        {% else %}
        <a href="{{ url_for('nfc.activate', station_id=s.id) }}"
           class="btn btn-green" style="margin-left:.25rem;">Activate</a>
        {% endif %}
      </td>
    </tr>
    {% endfor %}
  </table>
</div>

<p><a href="{{ url_for('admin_dashboard') }}" style="color:#60a5fa;">← Admin</a></p>

<script>
const domainTopics = {{ domain_topics_json }};
function updateTopics() {
  const domain = document.getElementById("domain-sel").value;
  const sel    = document.getElementById("topic-sel");
  Array.from(sel.options).forEach(o => {
    o.style.display = o.dataset.domain === domain ? "" : "none";
  });
  const visible = Array.from(sel.options).find(o => o.dataset.domain === domain);
  if (visible) sel.value = visible.value;
}
updateTopics();
</script>
</body></html>"""

_QR_PAGE = """<!DOCTYPE html><html><head>
<style>
body{font-family:system-ui;background:#18181b;color:#e4e4e7;
     text-align:center;padding:2rem;}
.qr-container{background:#fff;display:inline-block;padding:1.5rem;
              border-radius:8px;margin:1rem 0;}
.url{font-family:monospace;color:#60a5fa;word-break:break-all;
     max-width:400px;margin:1rem auto;}
</style>
<script src="https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js"></script>
</head><body>
<h2>{{ label }}</h2>
<p style="color:#71717a;">{{ location }}</p>
<div class="qr-container">
  <div id="qr"></div>
</div>
<div class="url">{{ url }}</div>
<p style="color:#71717a;font-size:.85rem;">
  Topic: <strong>{{ topic }}</strong> | Domain: {{ domain }}
</p>
<p><a href="{{ back }}" style="color:#60a5fa;">← Back to Stations</a></p>
<script>
new QRCode(document.getElementById("qr"), {
  text: "{{ url }}",
  width: 256, height: 256,
  colorDark: "#000000", colorLight: "#ffffff",
});
</script>
</body></html>"""


def _admin_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not nfc_bp.admin_auth.validate_token(session.get("admin_token")):
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)
    return wrapper


@nfc_bp.route("/")
@_admin_required
def index():
    km       = nfc_bp.knowledge_model
    registry = nfc_bp.station_registry

    domains = {
        d: km._domains[d].get("progression", [])
        for d in km._domains
    }
    domain_topics_json = json.dumps(domains)
    stations = sorted(
        list(registry._stations.values()),
        key=lambda s: (not s.active, s.label)
    )

    base_url = request.host_url.rstrip("/")

    return render_template_string(
        _STATION_MGMT,
        stations=stations,
        domains=domains,
        domain_topics_json=domain_topics_json,
        base_url=base_url,
    )


@nfc_bp.route("/create", methods=["POST"])
@_admin_required
def create_station():
    registry = nfc_bp.station_registry
    label    = request.form.get("label",    "Station").strip()[:100]
    location = request.form.get("location", "").strip()[:200]
    domain   = request.form.get("domain",   "arithmetic")
    topic    = request.form.get("topic",    "addition_basic")
    color    = request.form.get("color",    "#3b82f6")

    # Validate color
    import re
    if not re.match(r"^#[0-9a-fA-F]{6}$", color):
        color = "#3b82f6"

    from fotnssj import Station
    station = Station(
        id=f"station-{uuid.uuid4().hex[:8]}",
        topic=topic, domain=domain,
        label=label, location=location, color=color,
    )
    with registry._lock:
        registry._stations[station.id] = station
    registry._save()

    nfc_bp.audit_log.record(
        actor="admin", action="create_station",
        target=station.id, detail=f"{label} → {topic}",
        ip=request.remote_addr,
    )
    return redirect(url_for("nfc.index"))


@nfc_bp.route("/<station_id>/deactivate")
@_admin_required
def deactivate(station_id: str):
    registry = nfc_bp.station_registry
    s = registry.get(station_id)
    if s:
        s.active = False
        registry._save()
        nfc_bp.audit_log.record(
            actor="admin", action="deactivate_station",
            target=station_id, ip=request.remote_addr,
        )
    return redirect(url_for("nfc.index"))


@nfc_bp.route("/<station_id>/activate")
@_admin_required
def activate(station_id: str):
    registry = nfc_bp.station_registry
    s = registry.get(station_id)
    if s:
        s.active = True
        registry._save()
        nfc_bp.audit_log.record(
            actor="admin", action="activate_station",
            target=station_id, ip=request.remote_addr,
        )
    return redirect(url_for("nfc.index"))


@nfc_bp.route("/<station_id>/qr")
@_admin_required
def station_qr(station_id: str):
    s = nfc_bp.station_registry.get(station_id)
    if not s:
        return "Station not found", 404
    url = f"{request.host_url.rstrip('/')}/station/{station_id}"
    return render_template_string(
        _QR_PAGE,
        label=s.label, location=s.location,
        topic=s.topic.replace("_", " "), domain=s.domain,
        url=url,
        back=url_for("nfc.index"),
    )


def register_nfc_blueprint(app, admin_auth, station_registry,
                            knowledge_model, audit_log):
    nfc_bp.admin_auth        = admin_auth
    nfc_bp.station_registry  = station_registry
    nfc_bp.knowledge_model   = knowledge_model
    nfc_bp.audit_log         = audit_log
    app.register_blueprint(nfc_bp)