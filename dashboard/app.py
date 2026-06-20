"""Dashboard for the autonomous research agent (v0.4).

Adds full traceability:
- Per-iteration scorecards (composite score + 12+ deterministic metrics)
- Trend lines per metric across iterations ("is it getting better?")
- Tool × iteration heatmap (which tool was used when)
- Skill × iteration heatmap (which skill was used when)
- Per-iteration step-by-step timeline (drill-down modal)
- Delta arrows vs previous iteration
- Composite score chart with target bands

Run with:
    python dashboard/app.py                            # http://localhost:5050
    python dashboard/app.py --port 8000                # custom port
    python dashboard/app.py --host 0.0.0.0 --port 5050 # expose on LAN
    DASHBOARD_PORT=8080 python dashboard/app.py        # via env var

Reads config.yaml `dashboard.host` / `dashboard.port` if present (CLI > env > config).
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template_string

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.benchmark import score_all  # noqa: E402

HISTORY_DIR = ROOT / "history"
OUTPUTS_DIR = ROOT / "outputs"
SKILLS_DIR = ROOT / "skills"

app = Flask(__name__)


# ---------- helpers ----------

def _safe_name(name: str) -> bool:
    return ".." not in name and "/" not in name and "\\" not in name


def _load_jsonl(p: Path, limit: int | None = None) -> list[dict[str, Any]]:
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()
    if limit is not None:
        lines = lines[-limit:]
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


# ---------- data loaders ----------

def list_scorecards() -> list[dict[str, Any]]:
    """Read scorecard.json from each iteration. Recompute if missing."""
    if not HISTORY_DIR.exists():
        return []
    # First, prefer cached scorecard.json on disk
    cards: list[dict[str, Any]] = []
    have_all = True
    for d in sorted(HISTORY_DIR.glob("iteration_*")):
        if not d.is_dir():
            continue
        sc = d / "scorecard.json"
        if sc.exists():
            try:
                cards.append(json.loads(sc.read_text(encoding="utf-8")))
                continue
            except Exception:
                pass
        have_all = False
        break

    if have_all and cards:
        return cards

    # Otherwise recompute on the fly
    log_path = OUTPUTS_DIR / "agent_log.jsonl"
    return score_all(HISTORY_DIR, agent_log_path=log_path if log_path.exists() else None)


def list_experiments() -> list[dict[str, Any]]:
    if not HISTORY_DIR.exists():
        return []
    return [
        {"name": f.stem, "size": f.stat().st_size}
        for f in sorted(HISTORY_DIR.glob("*.md"))
    ]


def list_skills() -> list[dict[str, str]]:
    if not SKILLS_DIR.exists():
        return []
    out = []
    for f in sorted(SKILLS_DIR.glob("*.md")):
        if f.name.lower() == "readme.md":
            continue
        text = f.read_text(encoding="utf-8")
        m = re.search(r"USE WHEN:\s*(.+)", text)
        out.append({"name": f.stem, "description": m.group(1).strip() if m else ""})
    return out


def iteration_timeline(iter_num: int, limit: int = 1000) -> list[dict[str, Any]]:
    """Step-by-step log events for a single iteration."""
    events = _load_jsonl(OUTPUTS_DIR / "agent_log.jsonl")
    out = []
    for ev in events:
        if ev.get("iteration") != iter_num:
            continue
        if ev.get("type") == "step":
            action = ev.get("action", {}) or {}
            out.append({
                "step": ev.get("step"),
                "ts": ev.get("ts"),
                "tool": action.get("tool"),
                "skill": (action.get("args") or {}).get("name") if action.get("tool") == "use_skill" else None,
                "thought": (action.get("thought") or "")[:200],
                "summary": (ev.get("summary") or "")[:300],
                "duration_s": ev.get("duration_s"),
            })
        elif ev.get("type") == "reflect":
            r = ev.get("result", {}) or {}
            out.append({
                "step": ev.get("step"),
                "ts": ev.get("ts"),
                "tool": "(reflect)",
                "thought": (r.get("assessment") or "")[:200],
                "summary": (r.get("next_actions") or r.get("adjusted_notes") or "")[:300],
            })
    return out[-limit:]


def tool_heatmap(cards: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a matrix: rows=tool, cols=iteration_name, values=call count."""
    all_tools: set[str] = set()
    per_iter: dict[str, dict[str, int]] = {}
    for c in cards:
        usage = c.get("tool_usage", {}) or {}
        per_iter[c["iteration"]] = usage
        all_tools.update(usage.keys())
    tools = sorted(all_tools)
    iters = [c["iteration"] for c in cards]
    matrix = [[per_iter.get(it, {}).get(t, 0) for it in iters] for t in tools]
    return {"tools": tools, "iterations": iters, "matrix": matrix}


def skill_heatmap(cards: list[dict[str, Any]]) -> dict[str, Any]:
    all_skills: set[str] = set()
    per_iter: dict[str, dict[str, int]] = {}
    for c in cards:
        usage = c.get("skill_usage", {}) or {}
        per_iter[c["iteration"]] = usage
        all_skills.update(usage.keys())
    skills = sorted(all_skills)
    iters = [c["iteration"] for c in cards]
    matrix = [[per_iter.get(it, {}).get(s, 0) for it in iters] for s in skills]
    return {"skills": skills, "iterations": iters, "matrix": matrix}


def latest_final() -> str:
    p = OUTPUTS_DIR / "final.md"
    if not p.exists():
        return "_No final.md yet — run the agent first._"
    return p.read_text(encoding="utf-8")[:20000]


# ---------- routes ----------

@app.route("/api/scorecards")
def api_scorecards():
    return jsonify(list_scorecards())


@app.route("/api/tool-heatmap")
def api_tool_heatmap():
    return jsonify(tool_heatmap(list_scorecards()))


@app.route("/api/skill-heatmap")
def api_skill_heatmap():
    return jsonify(skill_heatmap(list_scorecards()))


@app.route("/api/iteration/<name>")
def api_iteration(name: str):
    if not _safe_name(name):
        return jsonify({"error": "bad name"}), 400
    iter_dir = HISTORY_DIR / name
    if not iter_dir.exists():
        return jsonify({"error": "not found"}), 404
    iter_num = int(re.sub(r"\D", "", name) or "0")
    sc_path = iter_dir / "scorecard.json"
    scorecard = (
        json.loads(sc_path.read_text(encoding="utf-8")) if sc_path.exists() else {}
    )
    summary = (iter_dir / "summary.md").read_text(encoding="utf-8") if (iter_dir / "summary.md").exists() else ""
    final = (iter_dir / "final.md").read_text(encoding="utf-8")[:50000] if (iter_dir / "final.md").exists() else ""
    prompt = (iter_dir / "prompt.md").read_text(encoding="utf-8") if (iter_dir / "prompt.md").exists() else ""
    return jsonify({
        "name": name,
        "scorecard": scorecard,
        "summary": summary,
        "final": final,
        "prompt": prompt,
        "timeline": iteration_timeline(iter_num),
    })


@app.route("/api/experiments")
def api_experiments():
    return jsonify(list_experiments())


@app.route("/api/experiment/<name>")
def api_experiment(name: str):
    if not _safe_name(name):
        return jsonify({"error": "bad name"}), 400
    path = HISTORY_DIR / f"{name}.md"
    if not path.exists():
        return jsonify({"error": "not found"}), 404
    return jsonify({"name": name, "content": path.read_text(encoding="utf-8")})


@app.route("/api/skills")
def api_skills():
    return jsonify(list_skills())


@app.route("/api/system-metrics")
def api_system_metrics():
    return jsonify(_load_jsonl(OUTPUTS_DIR / "system_metrics.jsonl", limit=500))


@app.route("/api/agent-log")
def api_agent_log():
    return jsonify(_load_jsonl(OUTPUTS_DIR / "agent_log.jsonl", limit=300))


@app.route("/api/compression")
def api_compression():
    """Headroom-ai compression savings (last 500 calls + aggregate)."""
    rows = _load_jsonl(OUTPUTS_DIR / "compression_log.jsonl", limit=500)
    tb = sum(int(r.get("tokens_before") or 0) for r in rows)
    ta = sum(int(r.get("tokens_after") or 0) for r in rows)
    saved = tb - ta
    ratio = (saved / tb) if tb else 0.0
    return jsonify(
        {
            "calls": len(rows),
            "tokens_before": tb,
            "tokens_after": ta,
            "tokens_saved": saved,
            "compression_ratio": round(ratio, 4),
            "samples": rows[-50:],
        }
    )


@app.route("/")
def index():
    return render_template_string(INDEX_HTML, latest_final=latest_final())


# ---------- HTML ----------

INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Ollama Research Agent — Traceability Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/marked@12/marked.min.js"></script>
  <style>
    :root {
      --bg:#0e1117; --panel:#161b22; --muted:#8b949e; --fg:#c9d1d9;
      --accent:#58a6ff; --good:#3fb950; --warn:#d29922; --bad:#f85149;
      --border:#30363d; --heat0:#0d1117; --heat-max:#58a6ff;
    }
    * { box-sizing: border-box; }
    body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
           margin:0; background:var(--bg); color:var(--fg); }
    header { padding:1rem 1.5rem; background:var(--panel); border-bottom:1px solid var(--border);
             display:flex; align-items:center; justify-content:space-between; }
    header h1 { margin:0; font-size:1.2rem; }
    header .sub { color:var(--muted); font-size:0.85rem; }
    .grid { display:grid; grid-template-columns:repeat(12, 1fr); gap:1rem; padding:1rem; }
    .card { background:var(--panel); border:1px solid var(--border); border-radius:8px;
            padding:1rem; overflow:hidden; }
    .card h2 { margin:0 0 0.5rem 0; font-size:0.95rem; color:var(--accent);
               border-bottom:1px solid var(--border); padding-bottom:0.4rem; }
    .col-12{grid-column:span 12} .col-8{grid-column:span 8} .col-6{grid-column:span 6}
    .col-4{grid-column:span 4} .col-3{grid-column:span 3}
    @media (max-width:1100px){ .col-8,.col-6,.col-4,.col-3{grid-column:span 12} }
    table { width:100%; border-collapse:collapse; font-size:0.85rem; }
    th, td { text-align:left; padding:0.4rem 0.5rem; border-bottom:1px solid var(--border); }
    th { color:var(--muted); font-weight:normal; }
    tr.clickable { cursor:pointer; }
    tr.clickable:hover { background:#1c2128; }
    .right { text-align:right; font-variant-numeric:tabular-nums; }
    .pill { display:inline-block; padding:0.1rem 0.5rem; border-radius:12px;
            font-size:0.72rem; background:var(--border); }
    .pill.good { background:rgba(63,185,80,0.2); color:var(--good); }
    .pill.warn { background:rgba(210,153,34,0.2); color:var(--warn); }
    .pill.bad  { background:rgba(248,81,73,0.2); color:var(--bad); }
    .delta-pos { color:var(--good); }
    .delta-neg { color:var(--bad); }
    .delta-zero { color:var(--muted); }
    canvas { max-height:260px !important; }
    a { color:var(--accent); cursor:pointer; text-decoration:none; }
    a:hover { text-decoration:underline; }
    pre, code { background:#1c2128; padding:0.1rem 0.3rem; border-radius:4px; font-size:0.85em; }
    pre { padding:0.6rem; overflow:auto; max-height:280px; }
    .muted { color:var(--muted); font-size:0.85rem; }
    /* heatmap */
    .heat { display:grid; gap:2px; overflow:auto; }
    .heat-cell { width:34px; height:22px; display:flex; align-items:center;
                 justify-content:center; font-size:0.7rem; color:#fff; border-radius:3px;
                 background:#1c2128; }
    .heat-row { display:flex; gap:2px; align-items:center; }
    .heat-label { width:130px; font-size:0.75rem; color:var(--muted); padding-right:0.5rem;
                  text-align:right; }
    .heat-header { width:34px; font-size:0.7rem; color:var(--muted); text-align:center;
                   transform:rotate(-30deg); transform-origin:left; height:24px; }
    /* modal */
    #modal { display:none; position:fixed; inset:0; background:rgba(0,0,0,0.7); z-index:1000; }
    #modal .body { background:var(--panel); margin:2rem auto; padding:1.5rem;
                   max-width:1100px; max-height:90vh; overflow:auto; border-radius:8px;
                   border:1px solid var(--border); }
    #modal .close { float:right; cursor:pointer; color:var(--muted); }
    .metric-row { display:flex; justify-content:space-between; padding:0.25rem 0;
                  border-bottom:1px dashed var(--border); font-size:0.85rem; }
    .metric-row:last-child { border-bottom:none; }
    .tabs { display:flex; gap:0.25rem; margin-bottom:0.75rem; border-bottom:1px solid var(--border); }
    .tab { padding:0.4rem 0.8rem; cursor:pointer; color:var(--muted);
           border-bottom:2px solid transparent; }
    .tab.active { color:var(--accent); border-bottom-color:var(--accent); }
    .composite-big { font-size:2.5rem; font-weight:bold; color:var(--accent); }
    .composite-label { color:var(--muted); font-size:0.85rem; }
    .stat-tile { text-align:center; padding:0.75rem 0.25rem; }
    .stat-tile .v { font-size:1.6rem; font-weight:bold; }
    .stat-tile .l { color:var(--muted); font-size:0.75rem; text-transform:uppercase; }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>🧠 Research Agent — Traceability Dashboard</h1>
      <div class="sub">Iteration-over-iteration scoring · tool &amp; skill heatmaps · drill-down timelines</div>
    </div>
    <div><button onclick="loadAll()">⟳ refresh</button></div>
  </header>

  <div class="grid">

    <!-- TOP: composite + summary tiles -->
    <div class="card col-3">
      <h2>🏆 Latest composite score</h2>
      <div id="composite-box" style="text-align:center; padding:1rem 0;">
        <div class="composite-big" id="composite-val">–</div>
        <div class="composite-label">/ 100 (weighted)</div>
        <div id="composite-delta" style="margin-top:0.5rem;"></div>
      </div>
    </div>

    <div class="card col-9">
      <h2>📈 Composite score over iterations (higher = better)</h2>
      <canvas id="score-chart"></canvas>
    </div>

    <!-- Iterations table -->
    <div class="card col-12">
      <h2>📊 Iteration scorecards (click a row to drill down)</h2>
      <table id="iter-table">
        <thead><tr>
          <th>Iter</th>
          <th class="right">Score</th>
          <th class="right">Δ</th>
          <th class="right">Sections</th>
          <th class="right">Sources</th>
          <th class="right">Citations</th>
          <th class="right">Tools</th>
          <th class="right">Skills</th>
          <th class="right">Calls</th>
          <th class="right">Fail%</th>
          <th class="right">Steps</th>
          <th class="right">Min</th>
          <th>Status</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>

    <!-- Trends -->
    <div class="card col-6">
      <h2>📐 Output trends (chars, citations, sections)</h2>
      <canvas id="output-chart"></canvas>
    </div>

    <div class="card col-6">
      <h2>⚙️ Operational trends (tool diversity, success ratio, skill diversity)</h2>
      <canvas id="ops-chart"></canvas>
    </div>

    <!-- Heatmaps -->
    <div class="card col-6">
      <h2>🛠 Tool usage × iteration</h2>
      <div id="tool-heat" class="heat"></div>
      <div class="muted" style="margin-top:0.5rem;">Darker = more calls. Scroll horizontally for many iterations.</div>
    </div>

    <div class="card col-6">
      <h2>🎯 Skill usage × iteration</h2>
      <div id="skill-heat" class="heat"></div>
    </div>

    <!-- Resource panels -->
    <div class="card col-6">
      <h2>💾 RAM &amp; CPU (live)</h2>
      <canvas id="resource-chart"></canvas>
    </div>

    <div class="card col-6">
      <h2>🔥 Thermals (live)</h2>
      <canvas id="thermal-chart"></canvas>
      <div class="muted" id="thermal-note"></div>
    </div>

    <!-- Skills + experiments -->
    <div class="card col-6">
      <h2>🎓 Available skills</h2>
      <table id="skills-table">
        <thead><tr><th>Name</th><th>When to use</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>

    <div class="card col-6">
      <h2>🔬 Experiment notes</h2>
      <ul id="experiments" style="padding-left:1.2rem; margin:0;"></ul>
    </div>

    <!-- Headroom compression savings (optional; empty if compression disabled) -->
    <div class="card col-12">
      <h2>🗜️ Prompt compression (headroom-ai)</h2>
      <div id="compression-summary" style="margin-bottom:.5rem; color:var(--muted);">
        Enable in <code>config.yaml</code> → <code>compression.enabled: true</code>
        and install <code>headroom-ai</code>.
      </div>
      <canvas id="chart-compression" height="80"></canvas>
    </div>

    <!-- Final preview -->
    <div class="card col-12">
      <h2>📄 Latest final.md</h2>
      <div id="final" style="max-height:500px; overflow:auto;"></div>
    </div>
  </div>

  <div id="modal" onclick="if(event.target.id==='modal')this.style.display='none'">
    <div class="body">
      <span class="close" onclick="document.getElementById('modal').style.display='none'">✕ close</span>
      <div id="modal-content"></div>
    </div>
  </div>

  <script>
    const FINAL_MD = {{ latest_final | tojson }};
    const charts = {};

    async function J(url) { const r = await fetch(url); return r.json(); }
    const esc = s => String(s ?? "").replace(/[&<>"']/g, c =>
        ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));

    function deltaStr(v, suffix='') {
      if (v === undefined || v === null || isNaN(v)) return '<span class="delta-zero">–</span>';
      const num = Number(v);
      const cls = num > 0 ? 'delta-pos' : (num < 0 ? 'delta-neg' : 'delta-zero');
      const sign = num > 0 ? '▲' : (num < 0 ? '▼' : '·');
      return `<span class="${cls}">${sign} ${Math.abs(num).toFixed(num%1===0?0:1)}${suffix}</span>`;
    }

    function statusPill(s, done) {
      if (done) return '<span class="pill good">done</span>';
      s = String(s || '').toLowerCase();
      if (s.includes('budget') || s.includes('signal')) return '<span class="pill warn">'+esc(s)+'</span>';
      if (s.includes('fail') || s.includes('ram') || s.includes('therm')) return '<span class="pill bad">'+esc(s)+'</span>';
      if (s === '(none)' || s === '') return '<span class="pill">running?</span>';
      return '<span class="pill">'+esc(s)+'</span>';
    }

    function chart(id, type, data, opts={}) {
      if (charts[id]) charts[id].destroy();
      const ctx = document.getElementById(id);
      if (!ctx) return;
      charts[id] = new Chart(ctx.getContext('2d'), {
        type, data,
        options: Object.assign({
          responsive: true,
          plugins: { legend: { labels: { color: '#c9d1d9' } } },
          scales: {
            x: { ticks: { color: '#8b949e', maxTicksLimit: 10 }, grid: { color: '#22272e' } },
            y: { ticks: { color: '#c9d1d9' }, grid: { color: '#22272e' } },
          },
        }, opts),
      });
    }

    async function loadScorecards() {
      const cards = await J('/api/scorecards');
      const tbody = document.querySelector('#iter-table tbody');
      if (!cards.length) {
        tbody.innerHTML = '<tr><td colspan="13" class="muted">No iterations yet — run main.py to generate one.</td></tr>';
        document.getElementById('composite-val').textContent = '–';
        return;
      }
      tbody.innerHTML = cards.map(c => {
        const d = c.delta_vs_prev || {};
        const callsTotal = c.total_tool_calls || 0;
        const failPct = callsTotal ? ((c.total_tool_failures||0)/callsTotal*100).toFixed(0) : '0';
        return `<tr class="clickable" onclick="openIteration('${esc(c.iteration)}')">
          <td><strong>${esc(c.iteration)}</strong></td>
          <td class="right"><strong>${(c.composite_score||0).toFixed(1)}</strong></td>
          <td class="right">${deltaStr(d.composite_score)}</td>
          <td class="right">${c.n_sections||0}</td>
          <td class="right">${c.n_unique_sources||0}</td>
          <td class="right">${c.n_citations||0}</td>
          <td class="right">${c.tool_diversity||0}</td>
          <td class="right">${c.skill_diversity||0}</td>
          <td class="right">${callsTotal}</td>
          <td class="right">${failPct}%</td>
          <td class="right">${c.steps||0}</td>
          <td class="right">${(c.elapsed_min||0).toFixed?.(1) || c.elapsed_min || 0}</td>
          <td>${statusPill(c.shutdown_reason, c.done)}</td>
        </tr>`;
      }).join('');

      const last = cards[cards.length-1];
      document.getElementById('composite-val').textContent = (last.composite_score||0).toFixed(1);
      const d = last.delta_vs_prev?.composite_score;
      document.getElementById('composite-delta').innerHTML = d !== undefined ?
        ('vs prev: ' + deltaStr(d)) : '<span class="muted">first iteration</span>';

      // Composite score line
      const labels = cards.map(c => c.iteration.replace('iteration_',''));
      chart('score-chart', 'line', {
        labels,
        datasets: [
          { label: 'composite score', data: cards.map(c=>c.composite_score), borderColor: '#58a6ff',
            backgroundColor: 'rgba(88,166,255,0.15)', fill: true, tension: 0.3, pointRadius: 5 },
        ],
      }, { scales: { y: { suggestedMin: 0, suggestedMax: 100,
                          ticks: { color: '#c9d1d9' }, grid: { color: '#22272e' } },
                     x: { ticks: { color: '#8b949e' }, grid: { color: '#22272e' } } } });

      // Output trends
      chart('output-chart', 'line', {
        labels,
        datasets: [
          { label: 'output chars', data: cards.map(c=>c.output_chars), borderColor: '#3fb950', tension:0.3, yAxisID:'y' },
          { label: 'citations',    data: cards.map(c=>c.n_citations),  borderColor: '#d29922', tension:0.3, yAxisID:'y1' },
          { label: 'sections',     data: cards.map(c=>c.n_sections),   borderColor: '#f85149', tension:0.3, yAxisID:'y1' },
        ],
      }, { scales: {
            x: { ticks: { color: '#8b949e' }, grid: { color: '#22272e' } },
            y:  { position:'left',  ticks: { color: '#c9d1d9' }, grid: { color: '#22272e' } },
            y1: { position:'right', ticks: { color: '#c9d1d9' }, grid: { drawOnChartArea: false } },
          } });

      // Operational trends
      chart('ops-chart', 'line', {
        labels,
        datasets: [
          { label: 'tool diversity',  data: cards.map(c=>c.tool_diversity),       borderColor: '#58a6ff', tension:0.3 },
          { label: 'skill diversity', data: cards.map(c=>c.skill_diversity),      borderColor: '#d29922', tension:0.3 },
          { label: 'success ratio',   data: cards.map(c=>(c.tool_success_ratio||0)*100), borderColor: '#3fb950', tension:0.3 },
        ],
      });
    }

    function renderHeat(container, rowLabels, colLabels, matrix) {
      const el = document.getElementById(container);
      const maxVal = Math.max(1, ...matrix.flat());
      let html = '<div class="heat-row"><div class="heat-label"></div>' +
        colLabels.map(c=>`<div class="heat-header">${esc(c.replace('iteration_',''))}</div>`).join('') +
        '</div>';
      rowLabels.forEach((r, i) => {
        html += '<div class="heat-row"><div class="heat-label">'+esc(r)+'</div>';
        matrix[i].forEach(v => {
          const alpha = v === 0 ? 0 : (0.15 + 0.85*(v/maxVal));
          html += `<div class="heat-cell" title="${esc(r)}: ${v}" `+
            `style="background:rgba(88,166,255,${alpha.toFixed(2)})">${v||''}</div>`;
        });
        html += '</div>';
      });
      el.innerHTML = html || '<span class="muted">empty</span>';
    }

    async function loadHeatmaps() {
      const t = await J('/api/tool-heatmap');
      renderHeat('tool-heat', t.tools, t.iterations, t.matrix);
      const s = await J('/api/skill-heatmap');
      renderHeat('skill-heat', s.skills, s.iterations, s.matrix);
    }

    async function loadMetrics() {
      const data = await J('/api/system-metrics');
      if (!data.length) { document.getElementById('thermal-note').textContent='No system_metrics.jsonl yet.'; return; }
      const labels = data.map(d=> new Date(d.ts*1000).toLocaleTimeString());
      chart('resource-chart', 'line', { labels, datasets: [
        { label:'RAM %', data:data.map(d=>d.ram_pct), borderColor:'#58a6ff', tension:0.2 },
        { label:'CPU %', data:data.map(d=>d.cpu_pct), borderColor:'#3fb950', tension:0.2 },
        { label:'Proc RSS MB', data:data.map(d=>d.proc_rss_mb), borderColor:'#d29922', tension:0.2, yAxisID:'y1' },
      ]}, { scales:{
              x:{ticks:{color:'#8b949e', maxTicksLimit:8}, grid:{color:'#22272e'}},
              y:{ticks:{color:'#c9d1d9'}, grid:{color:'#22272e'}},
              y1:{position:'right', ticks:{color:'#c9d1d9'}, grid:{drawOnChartArea:false}},
      }});
      const temps = data.map(d=>d.max_temp_c);
      if (temps.some(v=>v!=null)) {
        chart('thermal-chart','line',{labels, datasets:[{label:'°C', data:temps, borderColor:'#f85149', tension:0.2}]});
        const peak = Math.max(...temps.filter(v=>v!=null));
        document.getElementById('thermal-note').textContent =
          `Peak: ${peak.toFixed(1)} °C · ${data.length} samples · abort at 95 °C`;
      } else {
        document.getElementById('thermal-note').textContent = 'No thermal sensors readable (likely not on Linux).';
      }
    }

    async function loadSkillsAndExperiments() {
      const sk = await J('/api/skills');
      document.querySelector('#skills-table tbody').innerHTML = sk.map(s=>
        `<tr><td><code>${esc(s.name)}</code></td><td>${esc(s.description)}</td></tr>`
      ).join('') || '<tr><td colspan="2" class="muted">No skills</td></tr>';
      const ex = await J('/api/experiments');
      document.getElementById('experiments').innerHTML = ex.map(e=>
        `<li><a onclick="openExperiment('${esc(e.name)}')">${esc(e.name)}</a>
         <span class="muted">(${e.size} bytes)</span></li>`
      ).join('') || '<li class="muted">No experiments logged.</li>';
    }

    function tab(name, label) { return `<div class="tab" data-tab="${name}" onclick="setTab('${name}')">${label}</div>`; }
    let _modalIterTimeline = [];
    function setTab(name) {
      document.querySelectorAll('#modal .tab').forEach(t => t.classList.toggle('active', t.dataset.tab===name));
      document.querySelectorAll('#modal .tab-content').forEach(t => t.style.display = t.dataset.tab===name?'block':'none');
    }

    async function openIteration(name) {
      const d = await J('/api/iteration/' + encodeURIComponent(name));
      const sc = d.scorecard || {};
      const tl = d.timeline || [];
      const delta = sc.delta_vs_prev || {};

      const tiles = [
        ['composite', sc.composite_score?.toFixed(1) || '–', delta.composite_score],
        ['sections',  sc.n_sections || 0, delta.n_sections],
        ['sources',   sc.n_unique_sources || 0, delta.n_unique_sources],
        ['citations', sc.n_citations || 0, delta.n_citations],
        ['tools',     sc.tool_diversity || 0, delta.tool_diversity],
        ['skills',    sc.skill_diversity || 0, delta.skill_diversity],
      ].map(([l,v,d]) => `<div class="stat-tile"><div class="v">${v}</div>
          <div class="l">${l}</div><div>${d!==undefined?deltaStr(d):''}</div></div>`).join('');

      const allMetrics = Object.entries(sc)
        .filter(([k,v]) => typeof v !== 'object' || v === null)
        .map(([k,v]) => `<div class="metric-row"><span>${esc(k)}</span><span>${esc(v)}</span></div>`)
        .join('');

      const timelineHTML = tl.length ? `<table>
        <thead><tr><th>Step</th><th>Tool</th><th>Skill</th><th>Thought</th><th>Result</th><th class="right">s</th></tr></thead>
        <tbody>${tl.map(e=>`<tr>
          <td>${e.step||''}</td>
          <td><code>${esc(e.tool)}</code></td>
          <td>${e.skill?'<code>'+esc(e.skill)+'</code>':''}</td>
          <td><span class="muted">${esc(e.thought)}</span></td>
          <td>${esc(e.summary)}</td>
          <td class="right">${e.duration_s?e.duration_s.toFixed(1):''}</td>
        </tr>`).join('')}</tbody></table>` :
        '<div class="muted">No step events in agent_log.jsonl for this iteration.</div>';

      document.getElementById('modal-content').innerHTML = `
        <h2>${esc(name)} <span class="muted" style="font-size:0.7em">${esc(sc.ts||'')}</span></h2>
        <div style="display:grid; grid-template-columns:repeat(6,1fr); gap:0.5rem; margin-bottom:1rem;">${tiles}</div>
        <div class="tabs">
          ${tab('timeline','Timeline ('+tl.length+')')}
          ${tab('metrics','All metrics')}
          ${tab('output','Output')}
          ${tab('summary','Summary')}
          ${tab('prompt','Prompt snapshot')}
        </div>
        <div class="tab-content" data-tab="timeline" style="display:block">${timelineHTML}</div>
        <div class="tab-content" data-tab="metrics" style="display:none">${allMetrics}</div>
        <div class="tab-content" data-tab="output" style="display:none">${marked.parse(d.final || '_no final.md_')}</div>
        <div class="tab-content" data-tab="summary" style="display:none"><pre>${esc(d.summary)}</pre></div>
        <div class="tab-content" data-tab="prompt" style="display:none"><pre>${esc(d.prompt)}</pre></div>
      `;
      document.getElementById('modal').style.display = 'block';
    }

    async function openExperiment(name) {
      const d = await J('/api/experiment/' + encodeURIComponent(name));
      document.getElementById('modal-content').innerHTML =
        '<h2>'+esc(name)+'</h2>' + marked.parse(d.content || '');
      document.getElementById('modal').style.display = 'block';
    }

    async function loadCompression() {
      const d = await J('/api/compression');
      const sum = document.getElementById('compression-summary');
      if (!d.calls) {
        sum.innerHTML = 'No compression calls logged yet. Enable in <code>config.yaml</code> → '
          + '<code>compression.enabled: true</code> and install <code>headroom-ai</code>.';
        return;
      }
      const pct = (d.compression_ratio * 100).toFixed(1);
      sum.innerHTML = `<b>${d.calls}</b> calls · <b>${d.tokens_before.toLocaleString()}</b> → `
        + `<b>${d.tokens_after.toLocaleString()}</b> tokens · saved <b>${d.tokens_saved.toLocaleString()}</b> `
        + `(<b>${pct}%</b>)`;
      const labels = d.samples.map((_, i) => i + 1);
      const before = d.samples.map(s => s.tokens_before || 0);
      const after  = d.samples.map(s => s.tokens_after  || 0);
      if (charts.compression) charts.compression.destroy();
      charts.compression = new Chart(document.getElementById('chart-compression'), {
        type: 'line',
        data: { labels, datasets: [
          { label: 'before', data: before, borderColor:'#888', tension:.2 },
          { label: 'after',  data: after,  borderColor:'#3aa676', tension:.2, fill:true,
            backgroundColor:'rgba(58,166,118,.15)' },
        ]},
        options: { responsive:true, plugins:{ legend:{ labels:{ color:'#aaa' }}},
                   scales:{ x:{ ticks:{ color:'#aaa' }}, y:{ ticks:{ color:'#aaa' }}}}
      });
    }

    function loadAll() {
      loadScorecards();
      loadHeatmaps();
      loadMetrics();
      loadSkillsAndExperiments();
      loadCompression();
      document.getElementById('final').innerHTML = marked.parse(FINAL_MD);
    }

    loadAll();
    setInterval(loadMetrics, 30000);
    setInterval(loadScorecards, 60000);
    setInterval(loadCompression, 60000);
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    # Load defaults from config.yaml if present
    cfg_host, cfg_port = "127.0.0.1", 5050
    cfg_path = ROOT / "config.yaml"
    if cfg_path.exists():
        try:
            import yaml
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            d = cfg.get("dashboard", {}) or {}
            cfg_host = d.get("host", cfg_host)
            cfg_port = int(d.get("port", cfg_port))
        except Exception as e:
            print(f"warning: could not read dashboard.* from config.yaml: {e}", file=sys.stderr)

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("DASHBOARD_HOST", cfg_host),
                    help="bind address (default 127.0.0.1; use 0.0.0.0 to expose on LAN)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("DASHBOARD_PORT", cfg_port)),
                    help="port to listen on (default 5050)")
    args = ap.parse_args()

    # Friendly summary of what we'll show
    n_iters = len(list(HISTORY_DIR.glob("iteration_*"))) if HISTORY_DIR.exists() else 0
    has_metrics = (OUTPUTS_DIR / "system_metrics.jsonl").exists()
    print("=" * 60)
    print(f" Ollama Research Agent — Dashboard")
    print(f" history/ iterations: {n_iters}{'  (seed with: python scripts/seed_demo_history.py)' if n_iters == 0 else ''}")
    print(f" system metrics:      {'present' if has_metrics else 'none yet'}")
    print(f" Open: http://{args.host if args.host != '0.0.0.0' else 'localhost'}:{args.port}")
    print("=" * 60)

    try:
        app.run(host=args.host, port=args.port, debug=False)
    except OSError as e:
        if e.errno in (errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", 10048)):
            print(
                f"\n✗ Port {args.port} is already in use.\n"
                f"  Pick another: python dashboard/app.py --port 8080\n"
                f"  Or find what is using it: (linux)  ss -ltnp | grep :{args.port}\n"
                f"                            (mac)    lsof -i :{args.port}\n"
                f"                            (windows) Get-NetTCPConnection -LocalPort {args.port}",
                file=sys.stderr,
            )
            sys.exit(2)
        raise
