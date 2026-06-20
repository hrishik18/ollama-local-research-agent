"""Dashboard for the autonomous research agent.

Single-file Flask app that visualizes:
- All past iterations (from history/iteration_NNN/)
- Tool usage and step counts per iteration
- System metrics over time (RAM, CPU, thermals)
- Most recent final.md preview
- Skills available + experiments folder

Run with:
    python dashboard/app.py
    # then open http://localhost:5050

Designed for the 4GB-RAM target: no heavy frontend framework, plain HTML + Chart.js
via CDN. The whole app is one file.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template_string

ROOT = Path(__file__).resolve().parent.parent
HISTORY_DIR = ROOT / "history"
OUTPUTS_DIR = ROOT / "outputs"
SKILLS_DIR = ROOT / "skills"

app = Flask(__name__)


# ---------- data loaders ----------

def list_iterations() -> list[dict[str, Any]]:
    """Parse summary.md from each history/iteration_*/ folder."""
    if not HISTORY_DIR.exists():
        return []
    results = []
    for d in sorted(HISTORY_DIR.glob("iteration_*")):
        if not d.is_dir():
            continue
        summary_path = d / "summary.md"
        if not summary_path.exists():
            continue
        text = summary_path.read_text(encoding="utf-8")
        meta = _parse_summary(text)
        meta["iteration"] = d.name
        meta["has_final"] = (d / "final.md").exists()
        meta["has_prompt"] = (d / "prompt.md").exists()
        results.append(meta)
    return results


def _parse_summary(text: str) -> dict[str, Any]:
    """Extract bullet-list metadata from the iteration summary.md."""
    meta: dict[str, Any] = {}
    for line in text.splitlines():
        m = re.match(r"-\s+(\w+):\s+(.+)", line.strip())
        if m:
            key, val = m.group(1), m.group(2).strip()
            # Try JSON-decode for objects/lists
            try:
                meta[key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                meta[key] = val
    return meta


def list_experiments() -> list[dict[str, str]]:
    """Free-form experiment markdown files at the top of history/."""
    if not HISTORY_DIR.exists():
        return []
    return [
        {"name": f.stem, "size": f.stat().st_size}
        for f in sorted(HISTORY_DIR.glob("*.md"))
    ]


def load_system_metrics(limit: int = 500) -> list[dict[str, Any]]:
    """Tail outputs/system_metrics.jsonl."""
    p = OUTPUTS_DIR / "system_metrics.jsonl"
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()[-limit:]
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def load_agent_log(limit: int = 200) -> list[dict[str, Any]]:
    p = OUTPUTS_DIR / "agent_log.jsonl"
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()[-limit:]
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def list_skills() -> list[dict[str, str]]:
    if not SKILLS_DIR.exists():
        return []
    out = []
    for f in sorted(SKILLS_DIR.glob("*.md")):
        if f.name.lower() == "readme.md":
            continue
        text = f.read_text(encoding="utf-8")
        desc_match = re.search(r"USE WHEN:\s*(.+)", text)
        out.append({
            "name": f.stem,
            "description": desc_match.group(1).strip() if desc_match else "",
        })
    return out


def latest_final() -> str:
    p = OUTPUTS_DIR / "final.md"
    if not p.exists():
        return "_No final.md yet — run the agent first._"
    return p.read_text(encoding="utf-8")[:20000]


# ---------- routes ----------

@app.route("/api/iterations")
def api_iterations():
    return jsonify(list_iterations())


@app.route("/api/system-metrics")
def api_metrics():
    return jsonify(load_system_metrics())


@app.route("/api/agent-log")
def api_log():
    return jsonify(load_agent_log())


@app.route("/api/experiments")
def api_experiments():
    return jsonify(list_experiments())


@app.route("/api/skills")
def api_skills():
    return jsonify(list_skills())


@app.route("/api/experiment/<name>")
def api_experiment(name: str):
    path = HISTORY_DIR / f"{name}.md"
    if not path.exists() or ".." in name or "/" in name:
        return jsonify({"error": "not found"}), 404
    return jsonify({"name": name, "content": path.read_text(encoding="utf-8")})


@app.route("/api/iteration-final/<name>")
def api_iter_final(name: str):
    if ".." in name or "/" in name:
        return jsonify({"error": "bad name"}), 400
    path = HISTORY_DIR / name / "final.md"
    if not path.exists():
        return jsonify({"error": "not found"}), 404
    return jsonify({"name": name, "content": path.read_text(encoding="utf-8")[:50000]})


@app.route("/")
def index():
    return render_template_string(INDEX_HTML, latest_final=latest_final())


# ---------- HTML ----------

INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Ollama Research Agent — Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/marked@12/marked.min.js"></script>
  <style>
    :root {
      --bg:#0e1117; --panel:#161b22; --muted:#8b949e; --fg:#c9d1d9;
      --accent:#58a6ff; --good:#3fb950; --warn:#d29922; --bad:#f85149;
      --border:#30363d;
    }
    * { box-sizing: border-box; }
    body { font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
           margin:0; padding:0; background:var(--bg); color:var(--fg); }
    header { padding:1rem 1.5rem; background:var(--panel); border-bottom:1px solid var(--border); }
    header h1 { margin:0; font-size:1.3rem; }
    header .sub { color:var(--muted); font-size:0.85rem; margin-top:0.25rem; }
    .grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
            gap:1rem; padding:1rem; }
    .card { background:var(--panel); border:1px solid var(--border); border-radius:8px;
            padding:1rem; overflow:hidden; }
    .card h2 { margin-top:0; font-size:1rem; color:var(--accent); border-bottom:1px solid var(--border);
               padding-bottom:0.5rem; }
    .stat { display:flex; justify-content:space-between; padding:0.25rem 0;
            border-bottom:1px dashed var(--border); font-size:0.9rem; }
    .stat:last-child { border-bottom:none; }
    .stat span:last-child { color:var(--muted); }
    .pill { display:inline-block; padding:0.1rem 0.5rem; border-radius:12px;
            font-size:0.75rem; background:var(--border); margin-right:0.25rem; }
    .pill.good { background:rgba(63,185,80,0.2); color:var(--good); }
    .pill.warn { background:rgba(210,153,34,0.2); color:var(--warn); }
    .pill.bad { background:rgba(248,81,73,0.2); color:var(--bad); }
    table { width:100%; border-collapse:collapse; font-size:0.85rem; }
    th, td { text-align:left; padding:0.4rem; border-bottom:1px solid var(--border); }
    th { color:var(--muted); font-weight:normal; }
    a { color:var(--accent); text-decoration:none; cursor:pointer; }
    a:hover { text-decoration:underline; }
    pre, code { background:#1c2128; padding:0.15rem 0.35rem; border-radius:4px;
                font-size:0.85em; }
    pre { padding:0.75rem; overflow:auto; max-height:300px; }
    .final-preview { max-height:600px; overflow:auto; padding-right:0.5rem; }
    .final-preview h1, .final-preview h2, .final-preview h3 { color:var(--accent); }
    canvas { max-height:240px !important; }
    .muted { color:var(--muted); }
    .right { text-align:right; }
    button { background:var(--border); color:var(--fg); border:none; padding:0.3rem 0.7rem;
             border-radius:4px; cursor:pointer; font-size:0.8rem; }
    button:hover { background:#444c56; }
    #modal { display:none; position:fixed; top:0; left:0; width:100%; height:100%;
             background:rgba(0,0,0,0.7); z-index:1000; }
    #modal .body { background:var(--panel); margin:3rem auto; padding:1.5rem;
                   max-width:900px; max-height:80vh; overflow:auto; border-radius:8px;
                   border:1px solid var(--border); }
    #modal .close { float:right; cursor:pointer; color:var(--muted); }
  </style>
</head>
<body>
  <header>
    <h1>🧠 Ollama Local Research Agent — Dashboard</h1>
    <div class="sub">Iterations · System health · Tool usage · Final outputs</div>
  </header>

  <div class="grid">
    <div class="card">
      <h2>📊 Iterations</h2>
      <table id="iter-table">
        <thead><tr>
          <th>Iter</th><th class="right">Steps</th><th class="right">Min</th>
          <th>Status</th><th>Sections</th><th></th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>

    <div class="card">
      <h2>🔬 Experiments</h2>
      <ul id="experiments" style="padding-left:1.2rem; margin:0;"></ul>
    </div>

    <div class="card">
      <h2>🛠 Tool Usage (latest iteration)</h2>
      <canvas id="tool-chart"></canvas>
    </div>

    <div class="card">
      <h2>💾 RAM &amp; CPU over time</h2>
      <canvas id="resource-chart"></canvas>
    </div>

    <div class="card">
      <h2>🔥 Thermals over time</h2>
      <canvas id="thermal-chart"></canvas>
      <div class="muted" style="font-size:0.8rem; margin-top:0.5rem;" id="thermal-note"></div>
    </div>

    <div class="card">
      <h2>🎓 Skills</h2>
      <table id="skills-table">
        <thead><tr><th>Name</th><th>When</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>

    <div class="card" style="grid-column:1/-1">
      <h2>📄 Latest final.md</h2>
      <div class="final-preview" id="final"></div>
    </div>
  </div>

  <div id="modal" onclick="if(event.target.id==='modal')this.style.display='none'">
    <div class="body">
      <span class="close" onclick="document.getElementById('modal').style.display='none'">✕ close</span>
      <div id="modal-content"></div>
    </div>
  </div>

  <script>
    const FINAL = {{ latest_final | tojson }};

    async function getJSON(url) { const r = await fetch(url); return r.json(); }

    function escapeHtml(s) {
      return s.replace(/[&<>"']/g, c =>
        ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
    }

    function statusPill(s) {
      if (!s) return '<span class="pill">unknown</span>';
      if (s === 'done') return '<span class="pill good">done</span>';
      if (s.startsWith('stopped')) return '<span class="pill warn">'+escapeHtml(s)+'</span>';
      if (s.includes('failed') || s.includes('monitor')) return '<span class="pill bad">'+escapeHtml(s)+'</span>';
      return '<span class="pill">'+escapeHtml(s)+'</span>';
    }

    async function loadIterations() {
      const data = await getJSON('/api/iterations');
      const tbody = document.querySelector('#iter-table tbody');
      tbody.innerHTML = data.map(it => `
        <tr>
          <td>${escapeHtml(it.iteration)}</td>
          <td class="right">${it.steps || '-'}</td>
          <td class="right">${it.elapsed_min || '-'}</td>
          <td>${statusPill(it.shutdown_reason || (it.done==='True' ? 'done' : ''))}</td>
          <td>${(it.sections_written && it.sections_written.length) || 0}</td>
          <td>${it.has_final ? '<a onclick="showFinal(\''+escapeHtml(it.iteration)+'\')">view</a>' : ''}</td>
        </tr>
      `).join('') || '<tr><td colspan="6" class="muted">No iterations yet.</td></tr>';

      // Tool usage chart from latest iter
      if (data.length) {
        const last = data[data.length - 1];
        const usage = last.tool_usage || {};
        renderBar('tool-chart', Object.keys(usage), Object.values(usage), 'calls');
      }
    }

    async function loadExperiments() {
      const data = await getJSON('/api/experiments');
      document.getElementById('experiments').innerHTML = data.map(e =>
        `<li><a onclick="showExperiment('${escapeHtml(e.name)}')">${escapeHtml(e.name)}</a>
           <span class="muted">(${e.size} bytes)</span></li>`
      ).join('') || '<li class="muted">No experiments logged.</li>';
    }

    async function loadSkills() {
      const data = await getJSON('/api/skills');
      document.querySelector('#skills-table tbody').innerHTML = data.map(s =>
        `<tr><td><code>${escapeHtml(s.name)}</code></td><td>${escapeHtml(s.description)}</td></tr>`
      ).join('') || '<tr><td colspan="2" class="muted">No skills found.</td></tr>';
    }

    function renderBar(canvasId, labels, values, label) {
      const ctx = document.getElementById(canvasId).getContext('2d');
      if (window['_chart_'+canvasId]) window['_chart_'+canvasId].destroy();
      window['_chart_'+canvasId] = new Chart(ctx, {
        type: 'bar',
        data: { labels, datasets: [{ label, data: values, backgroundColor: '#58a6ff' }] },
        options: { plugins: { legend: { display: false } },
                   scales: { x: { ticks: { color: '#c9d1d9' } }, y: { ticks: { color: '#c9d1d9' } } } }
      });
    }

    function renderLine(canvasId, labels, datasets) {
      const ctx = document.getElementById(canvasId).getContext('2d');
      if (window['_chart_'+canvasId]) window['_chart_'+canvasId].destroy();
      window['_chart_'+canvasId] = new Chart(ctx, {
        type: 'line',
        data: { labels, datasets },
        options: { plugins: { legend: { labels: { color: '#c9d1d9' } } },
                   scales: { x: { ticks: { color: '#8b949e', maxTicksLimit: 8 } },
                             y: { ticks: { color: '#c9d1d9' } } } }
      });
    }

    async function loadMetrics() {
      const data = await getJSON('/api/system-metrics');
      if (!data.length) {
        document.getElementById('thermal-note').textContent = 'No system_metrics.jsonl yet.';
        return;
      }
      const labels = data.map(d => new Date(d.ts * 1000).toLocaleTimeString());
      renderLine('resource-chart', labels, [
        { label: 'RAM %', data: data.map(d => d.ram_pct), borderColor: '#58a6ff', tension: 0.2 },
        { label: 'CPU %', data: data.map(d => d.cpu_pct), borderColor: '#3fb950', tension: 0.2 },
        { label: 'Proc RSS MB', data: data.map(d => d.proc_rss_mb), borderColor: '#d29922',
          yAxisID: 'y1', tension: 0.2 },
      ]);

      const tempLabels = labels;
      const tempVals = data.map(d => d.max_temp_c);
      if (tempVals.some(v => v != null)) {
        renderLine('thermal-chart', tempLabels, [
          { label: 'Max temp °C', data: tempVals, borderColor: '#f85149', tension: 0.2 }
        ]);
        const peak = Math.max(...tempVals.filter(v => v != null));
        document.getElementById('thermal-note').textContent =
          `Peak: ${peak.toFixed(1)} °C · ${data.length} samples · abort at 95 °C`;
      } else {
        document.getElementById('thermal-note').textContent =
          'No thermal sensors readable (likely not on Linux or sensors unavailable).';
      }
    }

    function showFinal(iter) {
      fetch('/api/iteration-final/' + encodeURIComponent(iter))
        .then(r => r.json()).then(d => {
          document.getElementById('modal-content').innerHTML =
            '<h2>' + escapeHtml(iter) + ' — final.md</h2>' + marked.parse(d.content || '');
          document.getElementById('modal').style.display = 'block';
        });
    }

    function showExperiment(name) {
      fetch('/api/experiment/' + encodeURIComponent(name))
        .then(r => r.json()).then(d => {
          document.getElementById('modal-content').innerHTML =
            '<h2>' + escapeHtml(name) + '</h2>' + marked.parse(d.content || '');
          document.getElementById('modal').style.display = 'block';
        });
    }

    document.getElementById('final').innerHTML = marked.parse(FINAL);
    loadIterations();
    loadExperiments();
    loadSkills();
    loadMetrics();
    setInterval(loadMetrics, 30000);   // refresh metrics every 30s
    setInterval(loadIterations, 60000); // refresh iterations every minute
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    port = 5050
    print(f"Open http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)
