const sources = new Map();
const handles = new Map();
let history = [], handoffEvents = [], pendingFile = "", timer, loadingModels = false;
const starterModels = ["smollm2:135m","qwen2.5-coder:1.5b","granite3.3:2b","llama3.2:3b"];

function showJob(job) {
  el("job").textContent = job.status === "idle" ? "" : [job.model, job.status, job.detail,
    job.total ? Math.round(100*(job.completed||0)/job.total)+"% of layer" : ""].filter(Boolean).join(" · ");
  clearTimeout(timer);
  if (job.status === "running") timer = setTimeout(() => pollInstall().catch(problem), 1000);
}
async function pollInstall() {
  const {data} = await api("/admin/install");
  showJob(data);
  if (data.status === "ready") await localList();
}
async function startInstall(name) {
  try { el("notice").textContent=""; showJob((await api("/admin/install","POST",{name})).data); await pollInstall(); }
  catch (e) { problem(e); }
}
for (const name of starterModels) {
  const b=node("button","Install "+name); b.className="secondary"; b.onclick=()=>startInstall(name); el("catalog").append(b);
}
el("installForm").onsubmit=e=>{e.preventDefault();startInstall(el("modelRef").value.trim());};
el("searchForm").onsubmit=async e=>{
  e.preventDefault();
  const out=el("searchResults"), button=e.target.querySelector("button");
  out.textContent="Searching…";button.disabled=true;
  try {
    const {data}=await api("/admin/catalog?q="+encodeURIComponent(el("searchQuery").value.trim()));
    out.replaceChildren();
    if(!data.length)out.textContent="No public matches found. Try a shorter model name.";
    for(const item of data){
      const row=node("div","");row.className="panel row";
      const card=node("a",item.repository);
      card.href="https://huggingface.co/"+item.repository;card.target="_blank";card.rel="noopener noreferrer";
      const install=node("button","Install");install.onclick=()=>startInstall(item.name);
      row.append(card,install);out.append(row);
    }
  }catch(err){out.textContent=err.message}finally{button.disabled=false}
};
async function localList() {
  if (loadingModels) return;
  loadingModels=true;
  try {
    const {data} = await api("/admin/local");
    const performance = el("models").hidden ? [] : (await api("/admin/local/performance").catch(() => ({data:[]}))).data;
    const byModel = new Map(performance.map(model => [model.model,model]));
    const summary=el("modelSummary");
    summary.replaceChildren();
    for (const [label,value] of [
      ["installed",data.length],
      ["chat-capable",data.filter(model=>model.chat).length],
      ["total size",(data.reduce((sum,model)=>sum+model.bytes,0)/1e9).toFixed(2)+" GB"]
    ]) {
      const stat=node("div","");
      stat.append(node("strong",value),node("small",label));
      summary.append(stat);
    }
    const select=el("chatModel"), previous=select.value;
    const installed=el("installed");
    const table=node("table","");
    table.setAttribute("aria-label","Installed models");
    const headings=table.createTHead().insertRow();
    for (const label of ["Model","Size","Capability","Success · 7d","Median latency · 7d",""]) {
      const cell=node("th",label);
      cell.scope="col";
      headings.append(cell);
    }
    const rows=table.createTBody();
    installed.replaceChildren(table);
    select.replaceChildren();
    for(const m of data) {
      const row=rows.insertRow();
      const name=node("th","");
      name.scope="row";
      const identity=node("span","");
      identity.className="model-name";
      const dot=node("span","");
      dot.className="status-dot";
      dot.dataset.tone=m.chat?"good":"";
      dot.setAttribute("aria-hidden","true");
      identity.append(dot,node("span",m.name));
      name.append(identity);
      row.append(name);
      row.insertCell().textContent=(m.bytes/1e9).toFixed(2)+" GB";
      const capability=row.insertCell();
      const kind=node("span",m.chat?"Chat":"Other");
      kind.className="model-kind";
      capability.append(kind);
      const measured=byModel.get(m.name);
      const success=row.insertCell(), latency=row.insertCell();
      if (measured?.calls) {
        const fraction=(measured.calls-measured.failed)/measured.calls;
        const indicator=node("span","");
        indicator.className="model-metric";
        const signal=node("span","");
        signal.className="model-signal";
        signal.setAttribute("aria-hidden","true");
        for(let i=1;i<=5;i++) {
          const point=node("i","");
          point.dataset.on=i<=Math.round(fraction*5);
          signal.append(point);
        }
        indicator.title=measured.calls+" recorded model calls";
        indicator.append(signal,node("span",Math.round(fraction*100)+"%"));
        success.append(indicator);
        latency.textContent=(measured.median_ms/1000).toFixed(2)+" s";
      } else {
        success.textContent="No data";
        latency.textContent="—";
      }
      const action=row.insertCell();
      if(m.chat) {
        capability.className="model-status";
        select.add(new Option(m.name,m.name));
        const use=node("button","Open in playground");
        use.className="secondary";
        use.onclick=()=>{select.value=m.name; clearHistory();tab("playground");};
        action.append(use);
      }
    }
    if(!data.length) {
      const empty=rows.insertRow().insertCell();
      empty.colSpan=6;
      empty.textContent="Install a model to use it in the playground.";
    }
    if(data.some(m=>m.chat && m.name===previous)) select.value=previous;
    else if(data.some(m=>m.chat && m.name==="qwen2.5-coder:1.5b")) select.value="qwen2.5-coder:1.5b";
    if(!select.options.length) select.add(new Option("Install a chat model first",""));
  } finally { loadingModels=false; }
}
function clearHistory(resetHandoff = true) {
  if (resetHandoff === true) {
    handoffEvents = [];
    el("prepareHandoff").hidden = true;
    el("handoffPanel").hidden = true;
  }
  history=[];pendingFile="";el("thread").replaceChildren();el("proposal").hidden=true;el("chatTrace").hidden=true;
}
function renderFiles() {
  const list=el("fileList"), select=el("editTarget"); list.replaceChildren();select.replaceChildren(new Option("Answer question",""));
  for(const [name] of sources) {
    select.add(new Option("Edit "+name,name)); const b=node("button","Remove "+name);b.className="secondary";
    b.onclick=()=>{sources.delete(name);handles.delete(name);clearHistory();renderFiles();};list.append(b);
  }
}
async function importFiles(files, pickedHandles = []) {
  try {
    const merged=new Map(sources);
    for(const f of files) {
      if(f.size>160000) throw Error(f.name+" exceeds the text limit.");
      if(merged.has(f.name)) throw Error("Remove the existing "+f.name+" before replacing it.");
      const content=new TextDecoder("utf-8",{fatal:true}).decode(await f.arrayBuffer());
      if(content.includes("\0")) throw Error("Choose UTF-8 text or source files.");
      merged.set(f.name,content);
    }
    if(merged.size>12 || Array.from(merged.values()).reduce((n,v)=>n+v.length,0)>40000) throw Error("Reduce the selected files to fit the import limit.");
    for(const [name,value] of merged)sources.set(name,value);
    for(const handle of pickedHandles)handles.set(handle.name,handle);
    clearHistory();renderFiles();el("notice").textContent="";
  } catch(err){problem(err)} finally {el("files").value=""}
};
el("files").onchange=e=>importFiles(Array.from(e.target.files));
const openDisk=node("button","Open editable files");
openDisk.type="button";openDisk.className="secondary";el("files").parentElement.after(openDisk);
openDisk.hidden=!window.showOpenFilePicker;
openDisk.onclick=async()=>{
  try {
    const picked=await window.showOpenFilePicker({multiple:true});
    await importFiles(await Promise.all(picked.map(h=>h.getFile())),picked);
  }catch(e){if(e.name!=="AbortError")problem(e)}
};
const applyDisk=node("button","Apply to opened file");
applyDisk.className="secondary";el("saveFile").after(applyDisk);
let approving = false;
async function approveDraft(action) {
  if (!pendingFile || approving) return;
  approving = true;
  const name = pendingFile;
  const content = el("after").value;
  const actions = [el("saveFile"),applyDisk];
  actions.forEach(button => button.disabled = true);
  try {
    await api("/admin/playground/check","POST",{name,content});
    if (pendingFile !== name || el("after").value !== content) {
      throw Error("The draft changed during validation. Review it and try again.");
    }
    await action(name,content);
  } catch (error) { problem(error); }
  finally {
    approving = false;
    actions.forEach(button => button.disabled = false);
  }
}
applyDisk.onclick=()=>approveDraft(async (name,content)=>{
  const handle=handles.get(name);
  if(!handle)return;
  if(!confirm("Save the reviewed replacement to "+name+"?"))return;
  const original=await (await handle.getFile()).text();
  if(pendingFile!==name || el("after").value!==content || original!==sources.get(name)) {
    throw Error("The draft or original file changed. Review it again before saving.");
  }
  const writer=await handle.createWritable({mode:"exclusive"});
  try { await writer.write(content); await writer.close(); }
  catch(error) { await writer.abort().catch(()=>{}); throw error; }
  sources.set(name,content);
  rememberHandoff("Tool", "The user approved and saved the replacement to "+name+". Project tests were not run.");
  clearHistory(false);renderFiles();
});
el("chatModel").onchange=()=>clearHistory();el("resetChat").onclick=()=>clearHistory();
el("discard").onclick=()=>{
  if (pendingFile) rememberHandoff("Tool","The user discarded the proposed replacement for "+pendingFile+".");
  pendingFile="";el("proposal").hidden=true;
};
el("saveFile").onclick=()=>approveDraft((name,text)=>{
  const url=URL.createObjectURL(new Blob([text],{type:"text/plain;charset=utf-8"}));
  const a=document.createElement("a");a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  rememberHandoff("Tool","The user requested download of the reviewed replacement for "+name+". Project tests were not run.");
});
let playgroundRun="";
el("chatTrace").onclick=()=>{wantedTrace=playgroundRun;tab("analytics")};
el("chatForm").onsubmit=async e=>{
  e.preventDefault();
  const model=el("chatModel").value,question=el("question").value.trim(),target=el("editTarget").value;
  if(!model || !question){problem(Error("Select a local model and enter a message."));return}
  rememberHandoff("User",question);
  const controls=el("playground").querySelectorAll("button,select,input,textarea");
  controls.forEach(c=>c.disabled=true);
  el("sendChat").textContent="Running…";el("notice").textContent="";el("proposal").hidden=true;pendingFile="";
  const messages=[];
  for(const [name,content] of sources)messages.push({role:"user",content:"Imported file "+JSON.stringify(name)+"\n"+content});
  messages.push(...history,{role:"user",content:question+(target?"\nReturn only the complete replacement text for "+JSON.stringify(target)+", without Markdown fences.":"")});
  try{
    const {data,run}=await api("/admin/playground","POST",{model:"local/"+model,messages,edit_file:target||null,max_tokens:target?4096:1024});
    playgroundRun=run;el("chatTrace").hidden=false;
    const choice=data.choices[0],answer=choice.message.content;
    if (target) {
      rememberHandoff("Tool", "The playground generated a proposed replacement for "+target+
        ". "+data.file_check+". Awaiting user review. Request "+run+".");
    } else {
      rememberHandoff("Assistant",answer);
    }
    history.push({role:"user",content:question},{role:"assistant",content:answer});
    const card=node("article","");card.className="panel";card.append(node("h2",question));
    if(target && choice.finish_reason==="stop"){
      applyDisk.hidden=!handles.has(target);
      pendingFile=target;el("before").value=sources.get(target);el("after").value=answer.replace(/^```[^\n]*\n([\s\S]*?)\n```\s*$/,"$1");el("proposal").hidden=false;
      card.append(node("p",data.file_check+". Review the proposed change to "+target+" below."));
    }else{card.append(node("pre",answer));if(target)card.append(node("p","Incomplete generation. File export is disabled for this response."));}
    el("thread").append(card);el("question").value="";
  }catch(err){
    problem(err);
    rememberHandoff("Tool","The playground request failed."+ (err.run ? " Request "+err.run+"." : ""));
    if(err.run){playgroundRun=err.run;el("chatTrace").hidden=false}
  }
  finally{controls.forEach(c=>c.disabled=false);el("sendChat").textContent="Send";}
};
function rememberHandoff(role,message) {
  const clean = message.replace(/\s+/g," ").slice(0,3000);
  handoffEvents.push(role+": "+clean);
  handoffEvents = handoffEvents.slice(-40);
  el("prepareHandoff").hidden = false;
}

el("prepareHandoff").onclick = () => {
  const firstRequest = handoffEvents.findIndex(line => line.startsWith("User: "));
  const events = handoffEvents.filter((line,index) => index !== firstRequest);
  const lines = [];
  if (firstRequest >= 0) lines.push(handoffEvents[firstRequest]);
  if (sources.size) lines.push("Tool: Imported filenames: "+JSON.stringify([...sources.keys()])+".");
  const budget = 12000 - lines.join("\n").length - 1;
  const recent = [];
  let length = 0;
  for (let i=events.length-1; i>=0; i--) {
    if (length+events[i].length+1 > budget) break;
    recent.unshift(events[i]);
    length+=events[i].length+1;
  }
  el("handoffTranscript").value = [...lines,...recent].join("\n");
  el("handoffStatus").textContent = recent.length < events.length ? "Older turns omitted to fit the transcript limit." : "";
  el("handoffPreview").hidden = true;
  el("handoffPanel").hidden = false;
  el("handoffTranscript").focus();
};

el("generateHandoff").onclick = async () => {
  const transcript = el("handoffTranscript").value.trim();
  if (!transcript) return;
  const button = el("generateHandoff");
  const status = el("handoffStatus");
  button.disabled = true;
  el("handoffPreview").hidden = true;
  status.textContent = "Generating with local Agent Handoff…";
  try {
    const {data} = await api("/admin/playground/handoff","POST",{transcript});
    if (el("handoffPanel").hidden || transcript !== el("handoffTranscript").value.trim()) {
      status.textContent = "Transcript changed. Generate again to update the brief.";
      return;
    }
    el("handoffMarkdown").value = data.markdown;
    el("handoffPreview").hidden = false;
    status.textContent = "Ready for review";
  } catch (error) {status.textContent=error.message;}
  finally {button.disabled=false;}
};
el("handoffTranscript").oninput = () => {el("handoffPreview").hidden=true;};
el("downloadHandoff").onclick = () => {
  const markdown = el("handoffMarkdown").value;
  if (!markdown.trim()) return;
  const url = URL.createObjectURL(new Blob([markdown],{type:"text/markdown;charset=utf-8"}));
  const link = node("a","");
  link.href=url;link.download="HANDOFF.md";link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
};
for(const name of ["models","playground"])document.querySelector('[data-tab="'+name+'"]').addEventListener("click",()=>{localList().catch(problem);if(name==="models")pollInstall().catch(problem)});
tab("models");localList().catch(problem);pollInstall().catch(problem);
el("refreshModels").onclick=()=>localList().catch(problem);
el("addModels").onclick=()=>{
  el("modelTools").open=true;
  el("modelRef").focus();
};
