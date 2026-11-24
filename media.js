const mediaMode = el("mediaMode");
const mediaModel = el("mediaModel");
const mediaRun = el("mediaRun");
const mediaStatus = el("mediaStatus");
let outputURL;
let mediaLoading = false;
let mediaConnections = [];

function updateMediaHint() {
  const current = mediaConnections.find(item => "media/" + item.id === mediaModel.value);
  const local = current && /^http:\/\/(127\.0\.0\.1|localhost|\[::1\])(?=[:/]|$)/i.test(current.base);
  el("mediaHint").textContent = !current
    ? "Add a connection with this capability in Providers."
    : local ? "Runs on this computer." : "Hosted generation can use provider credits. Check the model’s pricing.";
}

function clearMediaOutput() {
  el("mediaOutput").replaceChildren();
  el("mediaResult").hidden = true;
  if (outputURL) URL.revokeObjectURL(outputURL);
  outputURL = undefined;
}

async function loadMedia() {
  if (mediaLoading) return;
  const mode = mediaMode.value;
  const lastModel = mediaModel.value;
  const {data} = await api("/admin/providers");
  if (mode !== mediaMode.value) return;
  mediaConnections = data.filter(provider => provider.capability === mode);
  mediaModel.replaceChildren(...mediaConnections.map(provider =>
    new Option(provider.label + " · " + provider.model, "media/" + provider.id)));
  if (mediaConnections.some(provider => "media/" + provider.id === lastModel)) mediaModel.value = lastModel;
  mediaRun.disabled = el("mediaCopyModel").disabled = mediaConnections.length === 0;
  updateMediaHint();
  el("mediaSpeechOptions").hidden = mode !== "speech";
  el("mediaVoice").required = mode === "speech";
  el("mediaAudioInput").hidden = mode !== "transcription";
  el("mediaAudio").required = mode === "transcription";
  el("mediaInputLabel").hidden = mode === "transcription";
  el("mediaInput").required = mode !== "transcription";
  el("mediaVideoOptions").hidden = el("mediaJob").hidden = mode !== "video";
}

mediaMode.onchange = () => {
  clearMediaOutput();
  mediaRun.disabled = true;
  mediaStatus.textContent = "";
  loadMedia().catch(problem);
};
mediaModel.onchange = updateMediaHint;

el("mediaCopyModel").onclick = async () => {
  try {
    await navigator.clipboard.writeText(mediaModel.value);
    mediaStatus.textContent = "API model ID copied.";
  } catch (error) { mediaStatus.textContent = error.message; }
};

async function requestBinary(path, payload) {
  const writing = payload !== undefined;
  const response = await fetch(path, {
    method: writing ? "POST" : "GET",
    headers: {"X-Relay-Admin": "dashboard", "Content-Type": "application/json"},
    body: writing ? JSON.stringify(payload) : undefined
  });
  if (!response.ok) {
    const data = await response.json();
    throw Error(data.error?.message || data.detail || "Media request failed.");
  }
  return response.blob();
}

function displayOutput(element) {
  el("mediaOutput").replaceChildren(element);
  el("mediaResult").hidden = false;
}

function showImage(data) {
  const image = node("img", "");
  image.alt = "Generated artwork";
  image.referrerPolicy = "no-referrer";
  if (data.url) {
    const source = new URL(data.url);
    if (source.protocol !== "https:") throw Error("Provider returned an unsupported image URL.");
    image.src = source.href;
  } else {
    const type = ["image/png", "image/jpeg", "image/webp"].includes(data.media_type) ? data.media_type : "image/png";
    image.src = "data:" + type + ";base64," + data.b64_json;
  }
  displayOutput(image);
}

async function readMediaAudio(file) {
  const format = file.name.split(".").at(-1).toLowerCase();
  if (!["wav", "mp3", "flac", "m4a", "ogg", "webm", "aac"].includes(format) || !file.size || file.size > 3_000_000) {
    throw Error("Select a supported audio file up to 3 MB.");
  }
  const data = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.slice(reader.result.indexOf(",") + 1));
    reader.onerror = () => reject(Error("Could not read the audio file."));
    reader.readAsDataURL(file);
  });
  return {data, format};
}

el("mediaForm").onsubmit = async event => {
  event.preventDefault();
  const mode = mediaMode.value;
  const input = el("mediaInput").value.trim();
  const file = el("mediaAudio").files[0];
  if (!(mode === "transcription" ? file : input) || !mediaModel.value || mediaLoading) return;
  clearMediaOutput();
  mediaLoading = mediaRun.disabled = mediaMode.disabled = mediaModel.disabled = true;
  mediaStatus.textContent = "Contacting the selected model…";
  const request = {model: mediaModel.value};
  try {
    if (mode === "speech") {
      const audio = node("audio", "");
      audio.controls = true;
      const blob = await requestBinary("/admin/media/speech", {
        ...request, input, voice: el("mediaVoice").value.trim(), response_format: el("mediaFormat").value
      });
      outputURL = audio.src = URL.createObjectURL(blob);
      displayOutput(audio);
    } else if (mode === "transcription") {
      const {data} = await api("/admin/media/transcription", "POST", {...request, input_audio: await readMediaAudio(file)});
      displayOutput(node("pre", data.text || "No speech returned."));
    } else if (mode === "embeddings") {
      const {data} = await api("/admin/media/embeddings", "POST", {...request, input});
      const vector = data.data[0].embedding;
      displayOutput(node("pre", vector.length + " dimensions\n\n" + JSON.stringify(vector, null, 2)));
    } else if (mode === "images") {
      const {data} = await api("/admin/media/images", "POST", {...request, prompt: input});
      showImage(data.data[0]);
    } else {
      const duration = el("mediaDuration").value;
      const aspectRatio = el("mediaAspect").value;
      const {data} = await api("/admin/media/video", "POST", {
        ...request, prompt: input, duration: duration ? Number(duration) : undefined,
        aspect_ratio: aspectRatio || undefined
      });
      el("mediaJobId").value = data.id;
      showVideoStatus(data);
      mediaStatus.textContent = "Submitted. Check status below.";
      return;
    }
    mediaStatus.textContent = "Complete.";
  } catch (error) {
    mediaStatus.textContent = error.message;
  } finally {
    mediaLoading = mediaRun.disabled = mediaMode.disabled = mediaModel.disabled = false;
  }
};

function showVideoStatus(data) {
  el("mediaVideoStatus").textContent = data.error || "Video status · " + data.status.replaceAll("_", " ");
  el("mediaDownload").hidden = data.status !== "completed";
}

el("mediaJobId").oninput = () => {
  el("mediaDownload").hidden = true;
  el("mediaVideoStatus").textContent = "";
};

el("mediaJob").onsubmit = async event => {
  event.preventDefault();
  const id = el("mediaJobId").value.trim();
  if (!/^[0-9a-f]{32}$/.test(id)) return;
  const button = el("mediaPoll");
  button.disabled = true;
  try {
    const {data} = await api("/admin/media/video/" + id);
    if (el("mediaJobId").value === id) showVideoStatus(data);
  } catch (error) { el("mediaVideoStatus").textContent = error.message; }
  finally { button.disabled = false; }
};

el("mediaDownload").onclick = async () => {
  const id = el("mediaJobId").value.trim();
  if (!/^[0-9a-f]{32}$/.test(id)) return;
  const button = el("mediaDownload");
  button.disabled = true;
  try {
    const blob = await requestBinary("/admin/media/video/" + id + "/content");
    if (el("mediaJobId").value !== id) return;
    clearMediaOutput();
    outputURL = URL.createObjectURL(blob);
    const file = node("a", "Save video");
    file.href = outputURL;
    file.download = "muxdeck-video." + (blob.type === "video/webm" ? "webm" : "mp4");
    file.click();
    const preview = node("video", "");
    preview.src = outputURL;
    preview.controls = true;
    displayOutput(preview);
  } catch (error) { el("mediaVideoStatus").textContent = error.message; }
  finally { button.disabled = false; }
};
