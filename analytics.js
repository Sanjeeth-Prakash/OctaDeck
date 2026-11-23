const analyticsFilters = ["analyticsMode", "analyticsOutcome", "analyticsModel"];
let visibleRuns = [];
let selectedTrace = "";
let revision = 0;

const failedStep = run => run.attempts.some(attempt => attempt.outcome !== "ok");
const seconds = ms => ms == null ? "—" : (ms / 1000).toFixed(2) + " s";
const number = value => value == null ? "—" : value.toLocaleString();

async function analytics() {
  const request = ++revision;
  const [mode, outcome, model] = analyticsFilters.map(id => el(id).value);
  const trace = wantedTrace;
  if (trace) {
    analyticsFilters.forEach(id => { el(id).value = ""; });
    el("analyticsWindow").value = "90d";
  }
  const params = new URLSearchParams({window: el("analyticsWindow").value});
  if (trace) params.set("trace", trace);
  else for (const [key,value] of Object.entries({mode,outcome,model})) if (value) params.set(key,value);
  el("exportAnalytics").disabled = true;
  const {data} = await api("/admin/analytics/report?" + params);
  if (request !== revision) return;
  if (trace) {
    selectedTrace = trace;
    wantedTrace = "";
  }
  visibleRuns = data.traces;
  const select = el("analyticsModel");
  const previous = trace ? "" : model;
  select.replaceChildren(new Option("All models", ""), ...data.model_options.map(id => new Option(id,id)));
  if (data.model_options.includes(previous)) select.value = previous;
  el("analyticsCount").textContent = "Showing "+visibleRuns.length+" of "+number(data.summary.requests)+" matching requests";
  el("exportAnalytics").disabled = !visibleRuns.length;
  renderSummary(data.summary);
  renderActivity(data);
  renderModelMetrics(data.models);
  renderTraces();
}

function renderSummary(summary) {
  const finished = summary.successful + summary.failed;
  const metrics = [
    ["Requests", number(summary.requests), number(summary.recovered)+" recovered"],
    ["Success rate", finished ? Math.round(100 * summary.successful / finished) + "%" : "—", number(summary.failed)+" failed"],
    ["Request latency", seconds(summary.p95_ms), "p95 · p50 "+seconds(summary.p50_ms)],
    ["Reported tokens", number(summary.tokens), number(summary.input_tokens)+" input · "+number(summary.output_tokens)+" output"]
  ];
  const stats = el("stats");
  stats.replaceChildren();
  for (const [label,value,detail] of metrics) {
    const card = node("div","");
    card.className = "stat";
    card.append(node("span",label),node("strong",value),node("small",detail));
    stats.append(card);
  }
}

function renderActivity({timeline,cutoff,bucket}) {
  const chart = el("activity");
  chart.replaceChildren();
  const axis = el("activityAxis");
  axis.replaceChildren();
  if (!timeline.length) {
    chart.append(node("p","No requests in this time range."));
    return;
  }
  const top = Math.max(...timeline.map(point => point.requests));
  const slots = new Map(timeline.map(point => [point.slot,point]));
  const totalSlots = Math.ceil((Date.now()/1000 - cutoff)/bucket);
  for (let i=0; i<totalSlots; i++) {
    const {requests,failed} = slots.get(i) ?? {requests:0,failed:0};
    const bar = node("span","");
    bar.title = new Date((cutoff+i*bucket)*1000).toLocaleString()+" · "+requests+" requests · "+failed+" failed";
    bar.dataset.failed = failed > 0;
    bar.style.height = (requests ? Math.max(3,Math.round(requests/top*85)) : 0)+"px";
    chart.append(bar);
  }
  axis.append(node("span",new Date(cutoff*1000).toLocaleDateString()),
              node("span","Peak "+top+" per "+(bucket===3600 ? "hour" : bucket===86400 ? "day" : "week")),
              node("span","Now"));
}

function renderModelMetrics(models) {
  const table = el("modelMetrics");
  table.replaceChildren();
  if (!models.length) {
    const cell = table.insertRow().insertCell();
    cell.colSpan = 5;
    cell.textContent = "No model calls in this view.";
  }
  for (const model of models) {
    const row = table.insertRow();
    const heading = node("th",model.provider+" / "+model.model);
    heading.scope = "row";
    row.append(heading);
    for (const value of [model.calls,model.failed,seconds(model.median_ms),number(model.tokens)]) {
      row.insertCell().textContent = value;
    }
  }
}

function renderTraces() {
  const out = el("traces");
  out.replaceChildren();
  if (!visibleRuns.length) out.append(node("p", "No requests match this view."));
  for (const run of visibleRuns) {
    const trace = node("details", "");
    trace.open = run.id === (selectedTrace || visibleRuns[0].id);
    const status = run.status === "ok" && failedStep(run) ? "recovered" : run.status;
    const heading = node("summary", "");
    heading.append(node("strong", run.tier + " · " + run.mode),
                   node("span", new Date(run.started * 1000).toLocaleString() + " · " + status));
    trace.append(heading, node("p", run.reason), node("small", "Request " + run.id));
    for (const attempt of run.attempts) {
      const step = node("pre", attempt.stage + " → " + attempt.provider + " / " + attempt.model + "\n" +
        attempt.outcome + " · " + attempt.duration_ms + " ms · " + (attempt.tokens ?? "unknown") + " tokens");
      if (attempt.outcome !== "ok") step.className = "trace-failure";
      trace.append(step);
    }
    out.append(trace);
  }
}

function csvCell(value) {
  const text = String(value ?? "");
  const safe = /^[\s\uFEFF]*[=+@-]|^[\t\r\n]/.test(text) ? "'" + text : text;
  return '"' + safe.replaceAll('"', '""') + '"';
}
el("exportAnalytics").onclick = () => {
  const rows = [["request_id","started_utc","type","tier","status","request_ms","routing_reason",
                 "stage","provider","model","stage_outcome","stage_ms","tokens","input_tokens","output_tokens"]];
  for (const run of visibleRuns) {
    const request = [run.id, new Date(run.started * 1000).toISOString(), run.mode, run.tier,
                     run.status, run.duration_ms, run.reason];
    const attempts = run.attempts.length ? run.attempts : [{}];
    for (const step of attempts) rows.push([...request, step.stage, step.provider, step.model,
                                          step.outcome, step.duration_ms, step.tokens, step.input_tokens, step.output_tokens]);
  }
  const csv = rows.map(row => row.map(csvCell).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob(["\uFEFF", csv], {type: "text/csv;charset=utf-8"}));
  const link = node("a", "");
  link.href = url;
  link.download = "model-relay-traces.csv";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
for (const id of [...analyticsFilters,"analyticsWindow"]) {
  el(id).addEventListener("change", () => { selectedTrace=""; analytics().catch(problem); });
}
el("resetAnalytics").onclick = () => {
  analyticsFilters.forEach(id => { el(id).value = ""; });
  selectedTrace = "";
  analytics().catch(problem);
};
el("refresh").onclick = () => analytics().catch(problem);
