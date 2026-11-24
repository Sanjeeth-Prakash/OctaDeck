const healthNames = {
  healthy: "Healthy", rejected: "Invalid key", denied: "Access denied",
  missing: "Model not found", limited: "Rate limited", billing: "Billing required", error: "Check failed"
};
const capabilities = {
  chat: "Chat", embeddings: "Embeddings", speech: "Speech", transcription: "Transcription", images: "Image", video: "Video"
};
let providerCatalog;
let discoveryRevision = 0;

async function loadProviderCatalog() {
  if (providerCatalog) return;
  const {data} = await api("/admin/provider-catalog");
  providerCatalog = new Map(data.map(item => [item.name, item]));
  el("preset").replaceChildren(...data.map(item => new Option(item.name, item.name)));
  setProviderPreset();
}

function updateDiscovery() {
  discoveryRevision++;
  const selected = providerCatalog.get(el("preset").value);
  const mode = el("capability").value;
  el("discoverRow").hidden = !(selected.discovery.includes(mode) && el("base").value.trim() === selected.base);
  el("modelResults").hidden = true;
  el("modelChoices").replaceChildren();
  el("saveProvider").textContent = mode === "chat" ? "Save and check" : "Save connection";
  el("providerCheckNote").textContent = mode === "chat"
    ? "Sends one short request. May use provider quota."
    : "Runs only when you choose Generate in Media.";
}

function setProviderPreset() {
  const selected = providerCatalog.get(el("preset").value);
  el("base").value = selected.base;
  el("label").value = selected.name === "Custom" ? "" : selected.name;
  el("model").value = selected.model;
  el("secret").value = "";
  el("providerStatus").textContent = "";
  el("presetNote").textContent = selected.note;
  el("presetDocs").hidden = !selected.docs;
  if (selected.docs) el("presetDocs").href = selected.docs;
  else el("presetDocs").removeAttribute("href");
  el("capability").replaceChildren(...selected.modes.map(mode => new Option(capabilities[mode], mode)));
  updateDiscovery();
}

el("preset").onchange = setProviderPreset;
el("base").oninput = updateDiscovery;
el("secret").oninput = updateDiscovery;
el("capability").onchange = () => {
  el("model").value = "";
  updateDiscovery();
};
el("modelChoices").onchange = () => {
  if (el("modelChoices").value) el("model").value = el("modelChoices").value;
};

el("discoverModels").onclick = async () => {
  const requestRevision = ++discoveryRevision;
  const loading = el("discoverModels");
  const status = el("providerStatus");
  loading.disabled = true;
  status.textContent = "Fetching the provider’s model list…";
  try {
    const {data} = await api("/admin/provider-models", "POST", {
      preset: el("preset").value, capability: el("capability").value, key: el("secret").value
    });
    if (requestRevision !== discoveryRevision) return;
    el("modelChoices").replaceChildren(new Option("Choose a model", ""), ...data.map(item =>
      new Option(item.id + (item.free_alias ? " · Free alias" : ""), item.id)));
    el("modelResults").hidden = !data.length;
    status.textContent = data.length ? "Select a model or enter its ID." : "The provider returned no models.";
  } catch (error) {
    if (requestRevision === discoveryRevision) status.textContent = error.message;
  } finally {
    loading.disabled = false;
  }
};

async function list() {
  await loadProviderCatalog();
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
  for (const label of ["Connection", "Capability", "Health", "Actions"]) {
    const cell = node("th", label);
    cell.scope = "col";
    heading.append(cell);
  }
  const body = table.createTBody();
  for (const provider of data) {
    const row = body.insertRow();
    row.insertCell().append(node("strong",provider.label),node("code",provider.model));
    row.insertCell().textContent = provider.capability === "chat" ? "Chat · " + provider.tier : capabilities[provider.capability];
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
    if (provider.capability === "chat") actions.append(check);
    actions.append(remove);
    row.insertCell().append(actions);
  }
  target.append(table);
}

el("providerForm").onsubmit = async event => {
  event.preventDefault();
  const status = el("providerStatus");
  const save = el("saveProvider");
  save.disabled = true;
  const capability = el("capability").value;
  status.textContent = capability === "chat" ? "Sending a short test request to the provider…" : "Saving connection…";
  try {
    const {data} = await api("/admin/providers","POST",{
      label:el("label").value,base:el("base").value,model:el("model").value,
      key:el("secret").value,tier:el("providerTier").value,capability
    });
    setProviderPreset();
    status.textContent = data.health ? "Saved. " + data.health.detail : "Saved. Open Media to run this model.";
    await list();
  } catch (error) { status.textContent = error.message; }
  finally {save.disabled = false;}
};
