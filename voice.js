const voice = {
  turns: [], stream: null, context: null, processor: null, frames: [],
  timer: null, audioUrl: null, trace: null
};

document.querySelector('[data-tab="voice"]').addEventListener("click", async () => {
  try {
    const {data} = await api("/admin/local");
    const select = el("voiceModel");
    const previous = select.value;
    select.replaceChildren(...data.filter(m => m.chat).map(m => new Option(m.name, m.name)));
    if (Array.from(select.options).some(o => o.value === previous)) select.value = previous;
    else if (Array.from(select.options).some(o => o.value === "llama3.1:latest")) select.value = "llama3.1:latest";
  } catch (error) {
    problem(error);
  }
});

function waveRecording(frames) {
  const length = frames.reduce((total, frame) => total + frame.length, 0);
  if (!length) throw Error("Record a short phrase first.");
  const buffer = new ArrayBuffer(44 + length * 2);
  const view = new DataView(buffer);
  function tag(offset, value) {
    for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
  }
  const rate = 16000;
  tag(0, "RIFF"); view.setUint32(4, buffer.byteLength - 8, true);
  tag(8, "WAVE"); tag(12, "fmt "); view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  tag(36, "data"); view.setUint32(40, length * 2, true);
  let offset = 44;
  for (const frame of frames) {
    for (const sample of frame) {
      view.setInt16(offset, Math.max(-1, Math.min(1, sample)) * 32767, true);
      offset += 2;
    }
  }
  return buffer;
}

async function releaseMicrophone() {
  clearTimeout(voice.timer);
  voice.processor?.disconnect();
  voice.stream?.getTracks().forEach(track => track.stop());
  const context = voice.context;
  voice.stream = voice.processor = voice.context = null;
  if (context && context.state !== "closed") await context.close();
}

const record = el("recordVoice");
record.onclick = async () => {
  record.disabled = true;
  el("voiceSend").disabled = true;
  try {
    if (!voice.stream) {
      if (!navigator.mediaDevices?.getUserMedia) throw Error("Open the local app in a browser that supports microphone access.");
      voice.stream = await navigator.mediaDevices.getUserMedia({audio:{channelCount:1}});
      voice.context = new AudioContext({sampleRate:16000});
      voice.frames = [];
      voice.processor = voice.context.createScriptProcessor(4096, 1, 1);
      voice.processor.onaudioprocess = event => voice.frames.push(event.inputBuffer.getChannelData(0).slice());
      voice.context.createMediaStreamSource(voice.stream).connect(voice.processor);
      voice.processor.connect(voice.context.destination);
      await voice.context.resume();
      record.textContent = "Stop recording";
      el("voiceStatus").textContent = "Recording up to 25 seconds";
      voice.timer = setTimeout(() => record.click(), 25000);
      return;
    }
    await releaseMicrophone();
    record.textContent = "Record";
    el("voiceStatus").textContent = "Transcribing locally…";
    const response = await fetch("/admin/voice/transcribe", {
      method:"POST", headers:{"X-Relay-Admin":"dashboard","Content-Type":"audio/wav"}, body:waveRecording(voice.frames)
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.detail);
    el("voiceText").value = result.text;
    el("voiceText").focus();
    el("voiceStatus").textContent = "Microphone off. Review the transcript before sending.";
  } catch (error) {
    await releaseMicrophone();
    record.textContent = "Record";
    el("voiceStatus").textContent = error.message;
  } finally {
    record.disabled = false;
    el("voiceSend").disabled = Boolean(voice.stream);
    if (!voice.stream) voice.frames = [];
  }
};

function resetAudio() {
  const audio = el("voiceAudio");
  audio.pause();
  audio.removeAttribute("src");
  if (voice.audioUrl) URL.revokeObjectURL(voice.audioUrl);
  voice.audioUrl = null;
  audio.hidden = true;
}

el("voiceSpeak").onclick = async () => {
  const text = el("voiceReply").textContent.slice(0, 2000);
  const controls = ["voiceSpeak","voiceReset","voiceSend","recordVoice"];
  controls.forEach(id => el(id).disabled = true);
  try {
    resetAudio();
    el("voiceStatus").textContent = "Generating speech locally…";
    const response = await fetch("/admin/voice/speak", {
      method:"POST", headers:{"X-Relay-Admin":"dashboard","Content-Type":"application/json"},
      body:JSON.stringify({text})
    });
    if (!response.ok) throw Error((await response.json()).detail);
    voice.audioUrl = URL.createObjectURL(await response.blob());
    const audio = el("voiceAudio");
    audio.src = voice.audioUrl;
    audio.hidden = false;
    await audio.play().catch(() => {});
    el("voiceStatus").textContent = "Audio ready";
  } catch (error) { el("voiceStatus").textContent = error.message; }
  finally { controls.forEach(id => el(id).disabled = false); }
};

el("voiceForm").onsubmit = async event => {
  event.preventDefault();
  const model = el("voiceModel").value;
  const content = el("voiceText").value.trim();
  if (!model || !content) {
    el("voiceStatus").textContent = "Select a local model and enter a message.";
    return;
  }
  const controls = ["voiceSend","voiceReset","voiceModel","recordVoice","voiceSpeak"];
  controls.forEach(id => el(id).disabled = true);
  el("voiceStatus").textContent = "Waiting for the local model…";
  try {
    resetAudio();
    const messages = [{role:"system",content:"Give a concise, conversational reply suitable for reading aloud."},
      ...voice.turns.slice(-12), {role:"user",content}];
    const {run,data} = await api("/admin/voice/chat","POST",{model:"local/"+model,messages,max_tokens:160});
    const answer = data.choices[0].message.content;
    voice.turns = [...messages.slice(1),{role:"assistant",content:answer.slice(0,3000)}];
    voice.trace = run;
    el("voiceTrace").hidden = false;
    el("voiceReply").textContent = answer;
    el("voiceResult").hidden = false;
    el("voiceStatus").textContent = "Reply ready";
  } catch (error) {
    el("voiceStatus").textContent = error.message;
    if (error.run) { wantedTrace=error.run; voice.trace=error.run; }
  }
  finally { controls.forEach(id => el(id).disabled = false); }
};
el("voiceTrace").onclick = () => { wantedTrace=voice.trace; tab("analytics"); };
el("voiceReset").onclick = () => {
  resetAudio();
  voice.turns = [];
  el("voiceText").value = "";
  el("voiceResult").hidden = true;
};
