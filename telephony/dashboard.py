"""
telephony/dashboard.py

The leasing team dashboard: open http://localhost:8000/dashboard
(or the ngrok URL + /dashboard from any device).

- GET /dashboard    -> single-page UI (no build step, no frameworks)
- GET /api/calls    -> JSON of all saved conversations

Each call renders as a card: priority badge, one-line summary, outcome,
booking, follow-up actions -- with full transcript and QA scorecard on
expand. Read-only by design: the dashboard renders the audit log, it
never edits it.
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from db.database import Database

router = APIRouter()


@router.get("/api/calls")
async def api_calls():
    return {"calls": Database().list_conversations()}


DASHBOARD_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lena — Leasing Dashboard</title>
<style>
  :root { --bg:#f6f7f9; --card:#ffffff; --ink:#1a1d21; --muted:#6b7280;
          --line:#e5e7eb; --hot:#dc2626; --warm:#d97706; --cold:#6b7280;
          --ok:#16a34a; --bad:#dc2626; --accent:#2563eb; }
  * { box-sizing:border-box; margin:0; }
  body { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         background:var(--bg); color:var(--ink); padding:24px; }
  h1 { font-size:22px; margin-bottom:4px; }
  .sub { color:var(--muted); font-size:14px; margin-bottom:20px; }
  .stats { display:flex; gap:12px; margin-bottom:20px; flex-wrap:wrap; }
  .stat { background:var(--card); border:1px solid var(--line); border-radius:10px;
          padding:12px 18px; min-width:120px; }
  .stat .n { font-size:22px; font-weight:700; }
  .stat .l { font-size:12px; color:var(--muted); }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px;
          padding:16px 18px; margin-bottom:12px; cursor:pointer; }
  .card:hover { border-color:var(--accent); }
  .row { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
  .badge { font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.5px;
           padding:3px 8px; border-radius:20px; color:#fff; }
  .b-hot{background:var(--hot)} .b-warm{background:var(--warm)} .b-cold{background:var(--cold)}
  .b-pass{background:var(--ok)} .b-fail{background:var(--bad)}
  .oneline { font-size:15px; font-weight:600; margin:8px 0 4px; }
  .meta { font-size:13px; color:var(--muted); }
  .detail { display:none; margin-top:14px; border-top:1px solid var(--line); padding-top:14px; }
  .card.open .detail { display:block; }
  .cols { display:grid; grid-template-columns:1fr 1fr; gap:18px; }
  @media (max-width:760px){ .cols{grid-template-columns:1fr} }
  h3 { font-size:13px; text-transform:uppercase; letter-spacing:.5px;
       color:var(--muted); margin:10px 0 6px; }
  .transcript { max-height:320px; overflow-y:auto; font-size:13.5px; line-height:1.5; }
  .t-agent { color:var(--accent); margin-bottom:6px; }
  .t-caller { margin-bottom:6px; }
  .t-tool { color:var(--muted); font-style:italic; font-size:12px; margin-bottom:6px; }
  ul { padding-left:18px; font-size:13.5px; } li { margin-bottom:3px; }
  .kv { font-size:13.5px; margin-bottom:3px; }
  .kv b { display:inline-block; min-width:110px; }
  .empty { text-align:center; color:var(--muted); padding:60px 0; }
  .flag { color:var(--bad); font-size:13px; }
</style>
</head>
<body>
<h1>Lena — Leasing Dashboard</h1>
<div class="sub">Cedar Grove Apartments · every call summarized, graded, and audit-logged</div>
<div class="stats" id="stats"></div>
<div id="calls"><div class="empty">Loading…</div></div>
<script>
function esc(s){ return String(s ?? "").replace(/[&<>"]/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }

function card(c){
  const s = c.summary || {};
  const qa = c.qa_scorecard || {};
  const pr = (s.priority||"cold").toLowerCase();
  const when = new Date(c.created_at).toLocaleString();
  const booking = s.booking ? `<span class="meta">📅 ${esc(s.booking)}</span>` : "";
  const who = s.caller_name ? `${esc(s.caller_name)}${s.caller_phone ? " · "+esc(s.caller_phone):""}` : (s.caller_phone||"Unknown caller");
  const guard = (c.guardrail_events||[]).length;
  const passed = qa.passed;
  return `<div class="card" onclick="this.classList.toggle('open')">
    <div class="row">
      <span class="badge b-${pr}">${pr}</span>
      ${passed!==undefined?`<span class="badge ${passed?'b-pass':'b-fail'}">QA ${passed?'pass':'fail'}</span>`:""}
      <span class="meta">${esc(when)}</span>
      <span class="meta">· ${esc(who)}</span>
      ${booking}
      ${guard? `<span class="flag">🛡 ${guard} blocked</span>`:""}
      ${(c.sms||[]).length? `<span class="meta">📱 SMS ${c.sms[0].status}</span>`:""}
    </div>
    <div class="oneline">${esc(s.one_line || "No summary available")}</div>
    <div class="meta">Outcome: ${esc(s.outcome||"—")} · Sentiment: ${esc(s.sentiment||"—")}</div>
    <div class="detail">
      <div class="cols">
        <div>
          <h3>Follow-up actions</h3>
          <ul>${(s.follow_up_actions||[]).map(a=>`<li>${esc(a)}</li>`).join("") || "<li>None</li>"}</ul>
          <h3>Questions asked</h3>
          <ul>${(s.key_questions||[]).map(a=>`<li>${esc(a)}</li>`).join("") || "<li>None</li>"}</ul>
          <h3>Concerns</h3>
          <ul>${(s.objections_or_concerns||[]).map(a=>`<li>${esc(a)}</li>`).join("") || "<li>None</li>"}</ul>
          <h3>Compliance</h3>
          <div class="kv"><b>Disclosure:</b> ${qa.deterministic?.ai_disclosure_in_first_message ? "✅ given" : "⚠️ check"}</div>
          <div class="kv"><b>Guardrail:</b> ${guard} block(s)</div>
          <div class="kv"><b>Triggers:</b> ${esc((qa.deterministic?.triggers_detected||[]).join(", ")||"none")}</div>
          <div class="kv"><b>Empathy:</b> ${esc(qa.llm_judge?.empathy_score_1_to_5 ?? "—")}/5</div>
          <div class="kv"><b>Cost:</b> $${esc(c.cost?.llm_cost_usd ?? "—")}</div>
          <div class="kv"><b>Audit hash:</b> ${esc((c.record_hash||"").slice(0,16))}…</div>
          ${(c.sms||[]).map(m=>`<h3>SMS follow-up (${esc(m.status)}${m.mode==="log"?" · log mode":""})</h3><div class="kv">To ${esc(m.to_phone)}: ${esc(m.body)}</div>`).join("")}
        </div>
        <div>
          <h3>Transcript</h3>
          <div class="transcript">
            ${c.transcript.map(t=>{
              if(t.role==="tool") return `<div class="t-tool">[tool: ${esc(t.tool)}]</div>`;
              const cls = t.role==="agent" ? "t-agent" : "t-caller";
              const name = t.role==="agent" ? "Lena" : "Caller";
              return `<div class="${cls}"><b>${name}:</b> ${esc(t.content)}</div>`;
            }).join("")}
          </div>
        </div>
      </div>
    </div>
  </div>`;
}

fetch("/api/calls").then(r=>r.json()).then(d=>{
  const calls = d.calls || [];
  const hot = calls.filter(c=>c.summary?.priority==="hot").length;
  const booked = calls.filter(c=>c.summary?.booking).length;
  const passed = calls.filter(c=>c.qa_scorecard?.passed).length;
  document.getElementById("stats").innerHTML = `
    <div class="stat"><div class="n">${calls.length}</div><div class="l">Total calls</div></div>
    <div class="stat"><div class="n">${hot}</div><div class="l">Hot leads</div></div>
    <div class="stat"><div class="n">${booked}</div><div class="l">Viewings booked</div></div>
    <div class="stat"><div class="n">${calls.length?passed+"/"+calls.length:"—"}</div><div class="l">QA passed</div></div>`;
  document.getElementById("calls").innerHTML =
    calls.length ? calls.map(card).join("") :
    '<div class="empty">No calls yet — make a call and finish it, then refresh.</div>';
});
</script>
</body>
</html>"""


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML
