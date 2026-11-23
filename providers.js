const healthNames = {
  healthy: "Healthy", rejected: "Invalid key", denied: "Access denied",
  missing: "Model not found", limited: "Rate limited", error: "Check failed"
};

async function list() {
  const {data} = await api("/admin/providers");
  const target = el("providerList");
  target.replaceChildren();
  if (!data.length) {
    const empty = node("p", "Add a provider to route requests.");
    empty.style.padding = "14px";
    target.append(empty);
    return;
  }
  const table = node("table", "");
  table.setAttribute("aria-label", "Provider connections");
  const heading = table.createTHead().insertRow();
  for (const label of ["Connection", "Tier", "Health", "Actions"]) {
    const cell = node("th", label);
    cell.scope = "col";
    heading.append(cell);
  }
  const body = table.createTBody();
  for (const provider of data) {
    const row = body.insertRow();
    row.insertCell().append(node("strong",provider.label),node("code",provider.model));
    row.insertCell().textContent = provider.tier;
    const label = node("span", "");
    const dot = node("span","");
    dot.className="status-dot";
    dot.dataset.tone=provider.state==="healthy"?"good":provider.state==="limited"?"warn":provider.state?"bad":"";
    dot.setAttribute("aria-hidden","true");
    label.append(dot,node("span",healthNames[provider.state] ?? "Unchecked"));
    label.className = "health";
    label.dataset.state = provider.state ?? "unchecked";
    const health = row.insertCell();
    health.append(label);
    if (provider.checked_at) {
      const date = new Date(provider.checked_at * 1000).toLocaleString();
      health.append(node("small", [provider.http_status && "HTTP " + provider.http_status,
        provider.duration_ms + " ms", date].filter(Boolean).join(" · ")));
      health.title = provider.detail;
    }
    const actions = node("div", "");
    actions.className = "provider-actions";
    const check = node("button","Check");
    const remove = node("button","Remove");
    check.className = remove.className = "secondary";
    check.onclick = async () => {
      check.disabled = remove.disabled = true;
      check.textContent = "Checking…";
      try {
        const {data: result} = await api("/admin/providers/"+provider.id+"/check","POST");
        await list();
        if (el("providers").hidden === false && result.state !== "healthy") problem(Error(result.detail));
        else el("notice").textContent = "";
      } catch (error) {
        problem(error);
        check.disabled = remove.disabled = false;
        check.textContent = "Check";
      }
    };
    remove.onclick = async () => {
      if (!confirm("Remove "+provider.label+" from routing?")) return;
      check.disabled = remove.disabled = true;
      try { await api("/admin/providers/"+provider.id,"DELETE"); await list(); }
      catch (error) { problem(error); check.disabled = remove.disabled = false; }
    };
    actions.append(check,remove);
    row.insertCell().append(actions);
  }
  target.append(table);
}

el("providerForm").onsubmit = async event => {
  event.preventDefault();
  const status = el("providerStatus");
  const save = el("saveProvider");
  save.disabled = true;
  status.textContent = "Sending a short test request to the provider…";
  try {
    const {data} = await api("/admin/providers","POST",{
      label:el("label").value,base:el("base").value,model:el("model").value,
      key:el("secret").value,tier:el("providerTier").value
    });
    preset();
    status.textContent = "Saved. "+data.health.detail;
    await list();
  } catch (error) { status.textContent = error.message; }
  finally {save.disabled = false;}
};
